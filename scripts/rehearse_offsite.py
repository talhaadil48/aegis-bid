import argparse
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
from botocore.exceptions import ClientError

from aegis.offsite import restore_directory, s3_client, upload_directory
from scripts.restore_sandbox import restore


def main(directory):
    password = secrets.token_hex(24)
    env = {**os.environ, "OFFSITE_TEST_PASSWORD": password}
    compose = [
        "docker",
        "compose",
        "--env-file",
        ".env",
        "-p",
        "aegis-offsite-test",
        "-f",
        "infra/compose.offsite-test.yaml",
    ]
    subprocess.run([*compose, "up", "-d", "--build"], env=env, check=True)
    os.environ.update(AWS_ACCESS_KEY_ID="localbackup", AWS_SECRET_ACCESS_KEY=password, AWS_DEFAULT_REGION="us-east-1")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if httpx.get("http://127.0.0.1:19000/minio/health/live", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    client = s3_client("http://127.0.0.1:19000", local_test=True)
    bucket = "aegis-rehearsal-" + uuid4().hex[:16]
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    key = secrets.token_bytes(32)
    receipt = upload_directory(client, bucket, directory, key, days=1)
    locked = receipt["index"]
    delete_blocked = False
    try:
        client.delete_object(Bucket=bucket, Key=locked["key"], VersionId=locked["version_id"])
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("AccessDenied", "InvalidRequest"):
            raise
        delete_blocked = True
    client.put_object(Bucket=bucket, Key=locked["key"], Body=b"corrupted latest version")
    destination = Path("restore-output") / ("offsite-" + uuid4().hex)
    file_report = restore_directory(client, receipt, destination, key)
    database_report = restore(destination, "docs/evidence/offsite-database")
    report = {
        "status": "PASS" if delete_blocked and database_report["status"] == "PASS" else "FAIL",
        "object_lock_delete_blocked": delete_blocked,
        "newer_corrupt_index_ignored": file_report["status"] == "PASS",
        "cipher": "AES-256-GCM",
        "receipt": receipt,
        "database_report": database_report,
        "scope": "S3-compatible local MinIO protocol rehearsal; not physically offsite, no independent cloud account provisioned",
    }
    Path("docs/evidence/offsite-local.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    subprocess.run([*compose, "stop"], env=env, check=True)
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    main(parser.parse_args().directory)
