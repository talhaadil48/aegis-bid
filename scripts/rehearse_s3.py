"""Real AWS S3 offsite exercise. Creates a dedicated private, retained test repository."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from psycopg.types.json import Jsonb

from aegis.db import connection
from aegis.offsite import restore_directory, upload_directory
from scripts.restore_sandbox import restore


def main(directory, region="ap-southeast-1"):
    manifest = json.loads((Path(directory) / "manifest.json").read_text())
    if not manifest.get("files") or not manifest.get("snapshot_id"):
        raise ValueError("A completed export manifest is required before creating a repository")
    session = boto3.Session()
    config = Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 2})
    client = session.client("s3", region_name=region, config=config)
    if not client.meta.endpoint_url.startswith("https://") or not client.meta.endpoint_url.split("/")[2].endswith(
        ".amazonaws.com"
    ):
        raise ValueError("This proof must use the real AWS HTTPS S3 endpoint")
    account = session.client("sts", region_name=region, config=config).get_caller_identity()["Account"]
    run_id = uuid4().hex
    bucket = "aegisbid-proof-" + run_id[:20]
    client.create_bucket(
        Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region}, ObjectLockEnabledForBucket=True
    )
    client.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            k: True for k in ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"]
        },
    )
    client.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    client.put_object_lock_configuration(
        Bucket=bucket,
        ObjectLockConfiguration={
            "ObjectLockEnabled": "Enabled",
            "Rule": {"DefaultRetention": {"Mode": "COMPLIANCE", "Days": 30}},
        },
    )
    # Key custody is outside the repository and application containers.
    custody = Path.home() / ".aegisbid"
    keys = custody / "backup-keys"
    receipts = custody / "receipts"
    keys.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = secrets.token_bytes(32)
    key_path = keys / (run_id + ".key")
    with key_path.open("x") as stream:
        stream.write(key.hex())
    key_path.chmod(0o600)
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(key_path), "/inheritance:r", "/grant:r", os.getlogin() + ":F"],
            check=True,
            capture_output=True,
        )
    receipt = upload_directory(client, bucket, directory, key, days=30)
    with (receipts / (run_id + ".json")).open("x") as stream:
        json.dump(receipt, stream, indent=2)
    deletion_denied = False
    try:
        client.delete_object(Bucket=bucket, Key=receipt["index"]["key"], VersionId=receipt["index"]["version_id"])
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("AccessDenied", "InvalidRequest"):
            raise
        deletion_denied = True
    started = time.monotonic()
    destination = Path("restore-output") / ("aws-" + run_id)
    files = restore_directory(client, receipt, destination, key)
    database = restore(destination, "docs/evidence/s3-database")
    report = {
        "status": "PASS" if deletion_denied and database["status"] == "PASS" else "FAIL",
        "timestamp": datetime.now(UTC).isoformat(),
        "region": region,
        "endpoint": client.meta.endpoint_url,
        "account_fingerprint": hashlib.sha256(account.encode()).hexdigest()[:16],
        "bucket": bucket,
        "compliance_version_deletion_denied": deletion_denied,
        "private_public_access_block": True,
        "client_encryption": "AES-256-GCM",
        "server_encryption": "AES256",
        "retained_until": receipt["retained_until"],
        "receipt": receipt,
        "file_verification": files,
        "database_verification": database,
        "offsite_restore_and_verify_s": time.monotonic() - started,
        "key_custody": "User home .aegisbid/backup-keys, outside repository and application containers",
        "scope": "Actual remote AWS S3 backup and isolated recovery; primary application is local. Repository is in the configured AWS account, not a separately administered account. Test objects remain protected for 30 days; no compute infrastructure created.",
    }
    Path("docs/evidence/s3-offsite.json").write_text(json.dumps(report, indent=2))
    with connection() as c:
        c.execute(
            "INSERT INTO backup_jobs(job_id,status,artifact_path,metadata) VALUES(%s,%s,%s,%s)",
            ("s3-" + run_id, "OFFSITE_VERIFIED", "s3://" + bucket + "/" + receipt["index"]["key"], Jsonb(report)),
        )
    print(json.dumps(report, indent=2))
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--region", default="ap-southeast-1")
    args = parser.parse_args()
    main(args.directory, args.region)
