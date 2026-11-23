import io
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag

from aegis.offsite import decrypt, encrypt, relative_path, restore_directory, sha256, upload_directory


class Objects:
    def __init__(self):
        self.objects = {}

    def get_bucket_versioning(self, **_):
        return {"Status": "Enabled"}

    def get_object_lock_configuration(self, **_):
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}

    def put_object(self, **args):
        version = str(uuid4())
        self.objects[args["Key"], version] = {**args, "Body": args["Body"].read()}
        return {"VersionId": version}

    def head_object(self, **args):
        return {"Metadata": self.objects[args["Key"], args["VersionId"]]["Metadata"]}

    def get_object_retention(self, **args):
        obj = self.objects[args["Key"], args["VersionId"]]
        return {"Retention": {"Mode": obj["ObjectLockMode"], "RetainUntilDate": obj["ObjectLockRetainUntilDate"]}}

    def get_object(self, **args):
        return {"Body": io.BytesIO(self.objects[args["Key"], args["VersionId"]]["Body"])}


def test_encryption_authentication_and_existing_file_safety(tmp_path):
    key = b"k" * 32
    source = tmp_path / "plain"
    source.write_bytes(b"private ledger" * 10000)
    cipher = tmp_path / "cipher"
    encrypt(source, cipher, key, "object-key")
    assert b"private ledger" not in cipher.read_bytes()
    recovered = tmp_path / "recovered"
    decrypt(cipher, recovered, key, "object-key")
    assert recovered.read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        decrypt(cipher, recovered, key, "object-key")
    assert recovered.read_bytes() == source.read_bytes()
    tampered = bytearray(cipher.read_bytes())
    tampered[-1] ^= 1
    cipher.write_bytes(tampered)
    with pytest.raises(InvalidTag):
        decrypt(cipher, tmp_path / "tampered", key, "object-key")
    assert not (tmp_path / "tampered").exists()


def test_locked_roundtrip_with_version_pinning(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "ledger.dump").write_bytes(b"authoritative data")
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": str(uuid4()),
                "checkpoint": datetime.now(UTC).isoformat(),
                "files": {"ledger.dump": sha256(source / "ledger.dump")},
            }
        )
    )
    objects = Objects()
    key = b"k" * 32
    receipt = upload_directory(objects, "backup", source, key)
    assert receipt["files"] == 2
    report = restore_directory(objects, receipt, tmp_path / "restore", key)
    assert report["status"] == "PASS"
    assert (tmp_path / "restore" / "ledger.dump").read_bytes() == b"authoritative data"
    with pytest.raises(ValueError, match="key"):
        restore_directory(objects, receipt, tmp_path / "wrong", b"x" * 32)
    with pytest.raises(ValueError, match="not exist"):
        restore_directory(objects, receipt, tmp_path / "restore", key)


@pytest.mark.parametrize("name", ["../../secret", "/etc/passwd", "C:/data", "..\\secret", "foo/../bar"])
def test_restore_path_guard(name):
    with pytest.raises(ValueError):
        relative_path(name)
