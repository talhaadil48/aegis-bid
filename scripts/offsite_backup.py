import argparse
import json
import os
from pathlib import Path

from aegis.offsite import key_from_environment, restore_directory, s3_client, upload_directory

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["upload", "restore"])
    p.add_argument("directory")
    p.add_argument("--receipt", required=True)
    p.add_argument("--bucket", default=os.getenv("BACKUP_BUCKET"))
    p.add_argument("--endpoint", default=os.getenv("BACKUP_ENDPOINT"))
    p.add_argument("--retention-days", type=int, default=30)
    args = p.parse_args()
    client = s3_client(args.endpoint)
    key = key_from_environment()
    if args.action == "upload":
        if not args.bucket:
            p.error("BACKUP_BUCKET or --bucket required")
        report = upload_directory(client, args.bucket, args.directory, key, args.retention_days)
        with Path(args.receipt).open("x") as f:
            f.write(json.dumps(report, indent=2))
    else:
        report = restore_directory(client, json.loads(Path(args.receipt).read_text()), args.directory, key)
    print(json.dumps(report, indent=2))
