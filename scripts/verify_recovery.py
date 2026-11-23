import argparse
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aegis.db import connection
from scripts.backup_export import digest


def verify_restore(directory, url, started_at, backup_id=None):
    path = Path(directory)
    manifest = json.loads((path / "manifest.json").read_text())
    errors = []
    for name, checksum in manifest["files"].items():
        if Path(name).name != name or digest(path / name) != checksum:
            errors.append("Artifact checksum mismatch: " + name)
    with connection(url) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        counts = {
            table: c.execute(f"SELECT count(*) n FROM {table}").fetchone()["n"]
            for table in ["auctions", "bid_requests", "bid_decisions", "auction_events", "winners"]
        }
        if counts != manifest["counts"]:
            errors.append("Restored table counts differ from snapshot")
        rows = c.execute(
            "SELECT auction_id,max(event_seq) event_seq FROM auction_events GROUP BY auction_id ORDER BY auction_id"
        ).fetchall()
        if [{**r, "auction_id": str(r["auction_id"])} for r in rows] != manifest["anchors"]:
            errors.append("Restored ledger positions differ")
        auctions = c.execute("SELECT * FROM auctions").fetchall()
        from fastapi.encoders import jsonable_encoder

        from aegis.evidence import pseudonym
        from aegis.rules import ZERO_HASH
        from aegis.verifier import verify

        for a in auctions:
            events = c.execute(
                "SELECT event_seq,payload,prev_hash,event_hash FROM auction_events WHERE auction_id=%s ORDER BY event_seq",
                (a["id"],),
            ).fetchall()
            winners = c.execute("SELECT * FROM winners WHERE auction_id=%s ORDER BY rank", (a["id"],)).fetchall()
            # Database hash consistency and independent rule replay; not a claim of external signed trust.
            report = verify(
                jsonable_encoder(
                    {
                        "schema_version": 1,
                        "auction": a,
                        "events": events,
                        "winners": [
                            {
                                "bidder": pseudonym(w["bidder_id"]),
                                "amount_cents": w["final_amount_cents"],
                                "rank": w["rank"],
                            }
                            for w in winners
                        ],
                        "anchor": events[-1]["event_hash"] if events else ZERO_HASH,
                        "signature": None,
                    }
                )
            )
            errors.extend(f"{a['id']}: {e}" for e in report["errors"])
    finished = datetime.now(UTC)
    return {
        "run_id": str(uuid4()),
        "backup_id": backup_id or manifest["snapshot_id"],
        "status": "FAIL" if errors else "PASS",
        "checksum_verified": not any("checksum" in e for e in errors),
        "counts": counts,
        "errors": errors,
        "restore_started_at": started_at.isoformat(),
        "finished_at": finished.isoformat(),
        "rto_s": (finished - started_at).total_seconds(),
        "protected_checkpoint": manifest["checkpoint"],
        "rpo_s": None,
        "scope": "Isolated logical snapshot restore and independent ledger replay; RPO requires actual failure timestamp; no external signed anchor checked",
    }


def write_certificate(report, destination):
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(report, indent=2))
    path.with_suffix(".html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>AegisBid recovery certificate</title><body style="font:16px system-ui;max-width:960px;margin:40px auto"><h1>Proof of Recovery · '
        + html.escape(report["status"])
        + '</h1><pre style="white-space:pre-wrap">'
        + html.escape(json.dumps(report, indent=2))
        + "</pre></body></html>"
    )


if __name__ == "__main__":
    import os

    p = argparse.ArgumentParser()
    p.add_argument("directory")
    p.add_argument("--output", default="docs/evidence/recovery")
    args = p.parse_args()
    report = verify_restore(args.directory, os.environ["RESTORE_DATABASE_URL"], datetime.now(UTC))
    write_certificate(report, args.output)
    print(json.dumps(report, indent=2))
    raise SystemExit(report["status"] != "PASS")
