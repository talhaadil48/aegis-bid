"""Encrypted, version-pinned, Object-Lock-protected S3 backup transport."""

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from uuid import UUID

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"AEGIS01\n"
CHUNK = 1024 * 1024


def key_from_environment():
    key = bytes.fromhex(os.environ["BACKUP_ENCRYPTION_KEY"])
    if len(key) != 32:
        raise ValueError("BACKUP_ENCRYPTION_KEY must contain 64 hex digits")
    return key


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def relative_path(value):
    path = PurePosixPath(value)
    if not value or not re.fullmatch(r"[A-Za-z0-9_./-]+", value) or path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe backup relative path")
    return path


def encrypt(source, destination, key, context):
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte backup key")
    nonce = os.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(context.encode())
    with Path(source).open("rb") as src, Path(destination).open("xb") as dst:
        dst.write(MAGIC + nonce)
        dst.writelines(cipher.update(block) for block in iter(lambda: src.read(CHUNK), b""))
        dst.write(cipher.finalize())
        dst.write(cipher.tag)


def decrypt(source, destination, key, context):
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte backup key")
    path = Path(destination)
    created = False
    try:
        with Path(source).open("rb") as src:
            if src.read(len(MAGIC)) != MAGIC:
                raise ValueError("Invalid encrypted backup format")
            nonce = src.read(12)
            size = src.seek(0, 2) - len(MAGIC) - 12 - 16
            if size < 0:
                raise ValueError("Truncated encrypted backup")
            src.seek(-16, 2)
            tag = src.read(16)
            src.seek(len(MAGIC) + 12)
            cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            cipher.authenticate_additional_data(context.encode())
            with path.open("xb") as dst:
                created = True
                remaining = size
                while remaining:
                    block = src.read(min(CHUNK, remaining))
                    if not block:
                        raise ValueError("Truncated encrypted content")
                    dst.write(cipher.update(block))
                    remaining -= len(block)
                dst.write(cipher.finalize())
            path.chmod(0o600)
    except BaseException:
        # Remove only the newly created plaintext file after failed authentication.
        if created:
            path.unlink(missing_ok=True)
        raise


def s3_client(endpoint=None, local_test=False):
    if endpoint and not endpoint.startswith("https://"):
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        if not local_test or parsed.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("Offsite endpoint must use HTTPS")
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=endpoint, config=Config(signature_version="s3v4", s3={"addressing_style": "path"})
    )


def require_protected_bucket(client, bucket):
    if client.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
        raise ValueError("Offsite bucket requires versioning")
    if (
        client.get_object_lock_configuration(Bucket=bucket).get("ObjectLockConfiguration", {}).get("ObjectLockEnabled")
        != "Enabled"
    ):
        raise ValueError("Offsite bucket requires Object Lock")


def upload_object(client, bucket, object_key, path, until, key_id):
    checksum = sha256(path)
    with Path(path).open("rb") as body:
        response = client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=body,
            ChecksumAlgorithm="SHA256",
            Metadata={"sha256": checksum, "key-id": key_id},
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=until,
        )
    version = response.get("VersionId")
    if not version or version == "null":
        raise ValueError("Object upload did not return a version ID")
    head = client.head_object(Bucket=bucket, Key=object_key, VersionId=version)
    retention = client.get_object_retention(Bucket=bucket, Key=object_key, VersionId=version)["Retention"]
    if (
        head.get("Metadata", {}).get("sha256") != checksum
        or retention.get("Mode") != "COMPLIANCE"
        or retention["RetainUntilDate"] < until
    ):
        raise ValueError("Object integrity metadata or compliance retention not confirmed")
    return {"key": object_key, "version_id": version, "cipher_sha256": checksum}


def upload_directory(client, bucket, directory, key, days=30):
    if days < 1:
        raise ValueError("Positive retention period required")
    require_protected_bucket(client, bucket)
    root = Path(directory).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    snapshot = str(UUID(manifest["snapshot_id"]))
    prefix = "aegis/" + snapshot
    until = datetime.now(UTC).replace(microsecond=0) + timedelta(days=days)
    key_id = hashlib.sha256(key).hexdigest()[:16]
    entries = {}
    # Source must be a prepared consistent export, never a live PGDATA directory.
    names = {**manifest["files"], "manifest.json": sha256(root / "manifest.json")}
    with tempfile.TemporaryDirectory() as temporary:
        for index, (name, expected) in enumerate(names.items()):
            relative_path(name)
            source = root / name
            if source.is_symlink() or not source.resolve().is_relative_to(root) or sha256(source) != expected:
                raise ValueError("Source artifact checksum or path mismatch")
            object_key = prefix + "/data/" + name + ".gcm"
            encrypted = Path(temporary) / str(index)
            encrypt(source, encrypted, key, object_key)
            if sha256(source) != expected:
                raise ValueError("Source artifact changed during encryption")
            entries[name] = {
                **upload_object(client, bucket, object_key, encrypted, until, key_id),
                "plain_sha256": expected,
            }
        index = {
            "schema_version": 1,
            "snapshot_id": snapshot,
            "checkpoint": manifest["checkpoint"],
            "key_id": key_id,
            "retained_until": until.isoformat(),
            "files": entries,
        }
        plain = Path(temporary) / "index.json"
        plain.write_text(json.dumps(index, sort_keys=True))
        index_key = prefix + "/index.gcm"
        encrypted = Path(temporary) / "index.gcm"
        encrypt(plain, encrypted, key, index_key)
        marker = upload_object(client, bucket, index_key, encrypted, until, key_id)
    # Index is published last. Incomplete uploads never become committed snapshots.
    return {
        "snapshot_id": snapshot,
        "bucket": bucket,
        "index": marker,
        "key_id": key_id,
        "files": len(entries),
        "checkpoint": manifest["checkpoint"],
        "completed_at": datetime.now(UTC).isoformat(),
        "retained_until": until.isoformat(),
    }


def download_object(client, bucket, entry, destination):
    response = client.get_object(Bucket=bucket, Key=entry["key"], VersionId=entry["version_id"])
    with Path(destination).open("xb") as stream:
        try:
            stream.writelines(iter(lambda: response["Body"].read(CHUNK), b""))
        finally:
            response["Body"].close()
    if sha256(destination) != entry["cipher_sha256"]:
        raise ValueError("Downloaded encrypted object checksum mismatch")


def restore_directory(client, receipt, destination, key):
    root = Path(destination)
    if root.exists():
        raise ValueError("Restore destination must not exist")
    if receipt["key_id"] != hashlib.sha256(key).hexdigest()[:16]:
        raise ValueError("Wrong independent decryption key")
    with tempfile.TemporaryDirectory() as temporary:
        encrypted = Path(temporary) / "index.gcm"
        download_object(client, receipt["bucket"], receipt["index"], encrypted)
        plain = Path(temporary) / "index.json"
        decrypt(encrypted, plain, key, receipt["index"]["key"])
        index = json.loads(plain.read_text())
        if index["schema_version"] != 1 or index["snapshot_id"] != receipt["snapshot_id"]:
            raise ValueError("Backup index identity mismatch")
        root.mkdir(parents=True, mode=0o700)
        for number, (name, entry) in enumerate(index["files"].items()):
            relative_path(name)
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            encrypted = Path(temporary) / str(number)
            download_object(client, receipt["bucket"], entry, encrypted)
            decrypt(encrypted, target, key, entry["key"])
            if sha256(target) != entry["plain_sha256"]:
                target.unlink()
                raise ValueError("Restored plaintext checksum mismatch")
    return {
        "status": "PASS",
        "snapshot_id": index["snapshot_id"],
        "files": len(index["files"]),
        "restored_at": datetime.now(UTC).isoformat(),
        "scope": "Version-pinned authenticated decryption and file verification; database recovery must run separately",
    }
