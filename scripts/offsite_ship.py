"""Backup-host service: commit complete export snapshots to an independent repository."""

import argparse
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from aegis.offsite import key_from_environment, s3_client, upload_directory

log = logging.getLogger("aegis.offsite")


def ship_pending(client, bucket, staging, receipts, key):
    receipts = Path(receipts)
    receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    shipped = 0
    for manifest_path in sorted(Path(staging).glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
            snapshot = str(UUID(manifest["snapshot_id"]))
            destination = receipts / (snapshot + ".json")
            if destination.exists():
                continue
            report = upload_directory(client, bucket, manifest_path.parent, key)
            temporary = destination.with_suffix(".tmp")
            with temporary.open("w") as stream:
                stream.write(json.dumps(report, indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            temporary.replace(destination)
            shipped += 1
            (receipts / "last-success.json").write_text(
                json.dumps(
                    {
                        "completed_at": datetime.now(UTC).isoformat(),
                        "snapshot_id": snapshot,
                        "checkpoint": manifest["checkpoint"],
                    }
                )
            )
        except (ValueError, KeyError, OSError):
            log.exception("Incomplete or invalid staged export: %s", manifest_path.parent.name)
    return shipped


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--staging", required=True)
    p.add_argument("--receipts", required=True)
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    client = s3_client(os.getenv("BACKUP_ENDPOINT"))
    key = key_from_environment()
    while True:
        ship_pending(client, os.environ["BACKUP_BUCKET"], args.staging, args.receipts, key)
        if args.once:
            break
        time.sleep(30)
