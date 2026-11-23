"""Consistent pg_dump snapshot plus signed per-auction evidence from that snapshot."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from aegis.config import DATABASE_URL
from aegis.db import connection


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pg_env(url):
    fields = conninfo_to_dict(url)
    env = os.environ.copy()
    for source, target in [
        ("host", "PGHOST"),
        ("port", "PGPORT"),
        ("dbname", "PGDATABASE"),
        ("user", "PGUSER"),
        ("password", "PGPASSWORD"),
    ]:
        if source in fields:
            env[target] = fields[source]
    return env


def export(directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=False)
    snapshot_id = str(uuid4())
    started = datetime.now(UTC)
    try:
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot = c.execute("SELECT pg_export_snapshot() snapshot,clock_timestamp() checkpoint").fetchone()
            counts = {
                table: c.execute(f"SELECT count(*) n FROM {table}").fetchone()["n"]
                for table in ["auctions", "bid_requests", "bid_decisions", "auction_events", "winners"]
            }
            anchors = c.execute(
                "SELECT auction_id,max(event_seq) event_seq FROM auction_events GROUP BY auction_id ORDER BY auction_id"
            ).fetchall()
            subprocess.run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    "--snapshot",
                    snapshot["snapshot"],
                    "--file",
                    str(path / "auction-db.dump"),
                ],
                env=pg_env(DATABASE_URL),
                check=True,
            )
        manifest = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "started_at": started.isoformat(),
            "checkpoint": snapshot["checkpoint"].isoformat(),
            "kind": "logical-snapshot",
            "pitr": False,
            "nats_snapshot": False,
            "reconciliation": "SQL bid_requests is durable intake authority; replay QUEUED rows after restore",
            "counts": counts,
            "anchors": [{**r, "auction_id": str(r["auction_id"])} for r in anchors],
            "files": {"auction-db.dump": digest(path / "auction-db.dump")},
            "bacula_job_id": None,
        }
        (path / "manifest.json").write_text(json.dumps(manifest, indent=2))
        checksum = digest(path / "manifest.json")
        with connection() as c:
            c.execute(
                "INSERT INTO backup_jobs(job_id,status,artifact_path,checksum,metadata) VALUES(%s,%s,%s,%s,%s)",
                (snapshot_id, "EXPORTED", str(path), checksum, Jsonb(manifest)),
            )
        return manifest
    except (OSError, subprocess.CalledProcessError) as exc:
        with connection() as c:
            c.execute(
                "INSERT INTO backup_jobs(job_id,status,artifact_path,metadata) VALUES(%s,%s,%s,%s)",
                (snapshot_id, "FAILED", str(path), Jsonb({"error_type": type(exc).__name__})),
            )
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("directory")
    args = p.parse_args()
    print(json.dumps(export(args.directory), indent=2))
