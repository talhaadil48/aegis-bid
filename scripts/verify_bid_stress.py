"""Replay saved signed evidence against every original HTTP request, without a database."""

import argparse
import csv
import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path

from aegis.verifier import verify


def verify_run(directory):
    root = Path(directory)
    summary = json.loads((root / "summary.json").read_text())
    public = (root / "audit-public-key.txt").read_bytes()
    with gzip.open(root / "signed-auction.json.gz", "rt", encoding="utf-8") as stream:
        document = json.load(stream)
    audit = verify(document, public)
    rows = []
    for path in sorted(root.glob("requests-*.csv.gz")):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            rows.extend(csv.DictReader(stream))
    events = {
        e["payload"]["request_id"]: e["payload"] for e in document["events"] if e["payload"]["type"] == "bid.decision"
    }
    expected = summary["sql"]["requested_bidders"]
    start, end = [datetime.fromisoformat(summary[key]) for key in ("window_start", "window_close")]
    errors = list(audit["errors"])
    if audit["status"] != "PASS":
        errors.append("Trusted signed replay failed")
    if len(rows) != len(events) or len(rows) != expected or len({r["bidder_id"] for r in rows}) != expected:
        errors.append("Population or decision cardinality mismatch")
    if len({r["request_id"] for r in rows}) != expected:
        errors.append("Duplicate client UUIDs")
    for row in rows:
        event = events.get(row["request_id"])
        if not event:
            errors.append("HTTP request missing from signed ledger")
            continue
        if event["bidder"] != hashlib.sha256(row["bidder_id"].encode()).hexdigest() or event["amount_cents"] != int(
            row["amount_cents"]
        ):
            errors.append("Authenticated bidder or integer amount mismatch")
        if not start <= datetime.fromisoformat(event["admitted_at"]) < end:
            errors.append("Durable server admission outside final ten seconds")
        if (
            row["error"]
            or row["http_status"] not in ("200", "202")
            or not start <= datetime.fromisoformat(row["written_at"]) < end
        ):
            errors.append("Client did not successfully offer this bid in the window")
    reports = [json.loads(p.read_text()) for p in root.glob("shard-*.json")]
    if summary.get("profile", "live_and_http") != "http_only" and (
        sum(r["active_at_window_start"] for r in reports) != expected
        or sum(r["active_at_end"] for r in reports) != expected
    ):
        errors.append("Distinct live population was not held")
    return {
        "status": "FAIL" if errors else "PASS",
        "distinct_bidders": expected,
        "http_requests_matched_to_signed_events": len(rows),
        "signed_winners": len(document["winners"]),
        "errors": sorted(set(errors)),
        "scope": "Offline client CSV to signed ledger replay; database crash telemetry and SQL commit-time counters are separate recorded observations",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    args = parser.parse_args()
    result = verify_run(args.directory)
    print(json.dumps(result, indent=2))
    raise SystemExit(result["status"] != "PASS")
