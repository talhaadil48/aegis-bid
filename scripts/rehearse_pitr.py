"""Real physical backup + archived WAL recovery into a new Compose project."""

import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo

from aegis import db
from aegis.engine import admit, close, process
from aegis.evidence import export_auction
from aegis.verifier import verify


def wait_database(url, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(url, connect_timeout=2) as c:
                if not c.execute("SELECT pg_is_in_recovery()").fetchone()[0]:
                    return
        except psycopg.OperationalError:
            pass
        time.sleep(1)
    raise TimeoutError("Isolated database did not become writable at recovery target")


def main():
    run_id = uuid4().hex
    project = "aegis-pitr-" + run_id[:8]
    env = {**os.environ, "BASE_NAME": "base-" + run_id, "RECOVERY_TARGET_NAME": "aegis_" + run_id}
    compose = ["docker", "compose", "--env-file", ".env", "-p", project, "-f", "infra/compose.pitr.yaml"]

    def docker(*args):
        return subprocess.run([*compose, *args], env=env, check=True, capture_output=True, text=True).stdout

    source = make_conninfo(
        host="127.0.0.1",
        port=os.getenv("PITR_SOURCE_PORT", "55433"),
        user="aegis",
        password=os.environ["POSTGRES_PASSWORD"],
        dbname="aegisbid",
    )
    restored = make_conninfo(
        host="127.0.0.1",
        port=os.getenv("PITR_RESTORE_PORT", "55434"),
        user="aegis",
        password=os.environ["POSTGRES_PASSWORD"],
        dbname="aegisbid",
    )
    original = db.DATABASE_URL
    try:
        docker("up", "-d", "--build", "primary")
        wait_database(source)
        db.DATABASE_URL = source
        db.migrate()
        aid, seller, bidder = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        with db.connection() as c:
            for uid, role in [(seller, "seller"), (bidder, "bidder")]:
                c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (uid, str(uid), "unused", role))
            c.execute(
                "INSERT INTO auctions(id,seller_id,title,stock,min_price_cents,increment_cents,opens_at,closes_at) VALUES(%s,%s,%s,3,100,10,%s,%s)",
                (aid, seller, "Continuous recovery rehearsal", now - timedelta(minutes=1), now + timedelta(minutes=10)),
            )
        admit(aid, bidder, uuid4(), 100)
        process(aid, "pitr-worker")
        docker("run", "--rm", "basebackup")
        # These decisions do not exist in the base backup. Recovery requires subsequent WAL.
        admit(aid, bidder, uuid4(), 110)
        process(aid, "pitr-worker")
        with db.connection() as c:
            c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
        close(aid, "pitr-worker")
        expected = export_auction(aid)
        with db.connection() as c:
            target = c.execute(
                "SELECT pg_create_restore_point(%s) lsn,clock_timestamp() time", (env["RECOVERY_TARGET_NAME"],)
            ).fetchone()
        incident_at = datetime.now(UTC)
        with db.connection() as c:
            c.execute("DELETE FROM auction_events WHERE auction_id=%s AND event_seq=1", (aid,))
        with db.connection() as c:
            c.execute("SELECT pg_switch_wal()")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            with db.connection() as c:
                row = c.execute("SELECT last_archived_time,last_failed_time FROM pg_stat_archiver").fetchone()
            if row["last_archived_time"] and row["last_archived_time"] >= target["time"]:
                break
            time.sleep(1)
        else:
            raise TimeoutError("Post-target WAL was not archived")
        start = time.monotonic()
        docker("--profile", "recovery", "up", "-d", "recovered")
        wait_database(restored)
        db.DATABASE_URL = restored
        actual = export_auction(aid)
        check = verify(actual)
        valid = actual == expected and not check["errors"]
        report = {
            "run_id": run_id,
            "project": project,
            "status": "PASS" if valid else "FAIL",
            "base_name": env["BASE_NAME"],
            "target_name": env["RECOVERY_TARGET_NAME"],
            "target_lsn": target["lsn"],
            "protected_checkpoint": target["time"].isoformat(),
            "incident_at": incident_at.isoformat(),
            "rpo_s": max(0, (incident_at - target["time"]).total_seconds()),
            "rto_s": time.monotonic() - start,
            "base_decisions": 1,
            "restored_decisions": check["decisions"],
            "restored_events": check["events"],
            "ledger_anchor_matches": actual["anchor"] == expected["anchor"],
            "verifier_errors": check["errors"],
            "scope": "Isolated physical PITR through archived WAL; selected named target; source corruption occurred only in new rehearsal project; excludes offsite retrieval and full-site rebuild",
        }
        Path("docs/evidence/pitr-local.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        raise SystemExit(not valid)
    finally:
        db.DATABASE_URL = original
        docker("stop", "recovered", "primary")


if __name__ == "__main__":
    main()
