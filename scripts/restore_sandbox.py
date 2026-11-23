"""Create a new database only; never overwrites or drops an existing database."""

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from aegis.config import DATABASE_URL
from aegis.db import connection
from scripts.backup_export import digest, pg_env
from scripts.verify_recovery import verify_restore, write_certificate


def restore(directory, output, admin_url=None):
    started = datetime.now(UTC)
    path = Path(directory)
    manifest = json.loads((path / "manifest.json").read_text())
    for name, checksum in manifest["files"].items():
        if Path(name).name != name or digest(path / name) != checksum:
            raise ValueError("Backup checksum mismatch or unsafe path")
    name = "aegis_restore_" + uuid4().hex
    target = conninfo_to_dict(admin_url or DATABASE_URL)
    target["dbname"] = name
    restore_url = make_conninfo(**target)
    with psycopg.connect(admin_url or DATABASE_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    subprocess.run(
        ["pg_restore", "--exit-on-error", "--no-owner", "--no-acl", "--dbname", name, str(path / "auction-db.dump")],
        env=pg_env(restore_url),
        check=True,
    )
    report = verify_restore(path, restore_url, started)
    report["isolated_database"] = name
    write_certificate(report, output)
    with connection() as c:
        c.execute(
            "INSERT INTO recovery_runs(run_id,backup_id,rpo_s,rto_s,verified,report_path) VALUES(%s,%s,%s,%s,%s,%s)",
            (report["run_id"], report["backup_id"], None, report["rto_s"], report["status"] == "PASS", str(output)),
        )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("directory")
    p.add_argument("--output", default="docs/evidence/recovery")
    args = p.parse_args()
    report = restore(args.directory, args.output, os.getenv("RESTORE_ADMIN_URL"))
    print(json.dumps(report, indent=2))
    raise SystemExit(report["status"] != "PASS")
