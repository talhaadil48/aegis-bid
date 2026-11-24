"""Local demonstration actions. Never contacts AWS or alters recorded evidence."""

import argparse
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv

BASE = "http://127.0.0.1:58000"
CACHE = Path(".cache")


@contextmanager
def client_for(username):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / "demo-cookies.json"
    tokens = json.loads(path.read_text()) if path.exists() else {}
    with httpx.Client(base_url=BASE, timeout=15) as client:
        if username in tokens:
            client.cookies.set("aegis_session", tokens[username])
            if client.get("/v1/auth/me").status_code == 200:
                yield client
                return
        result = client.post("/v1/auth/login", json={"username": username, "password": os.environ["DEMO_PASSWORD"]})
        result.raise_for_status()
        tokens[username] = client.cookies.get("aegis_session")
        path.write_text(json.dumps(tokens))
        path.chmod(0o600)
        yield client


def state():
    path = CACHE / "demo-state.json"
    if not path.exists():
        raise RuntimeError("Run --prepare first")
    return json.loads(path.read_text())


def prepare():
    now = datetime.now(UTC)
    title = "CEP demo " + now.strftime("%H:%M UTC")
    with client_for("admin") as client:
        response = client.post(
            "/v1/admin/auctions",
            json={
                "title": title,
                "stock": 3,
                "min_price_cents": 10000,
                "increment_cents": 500,
                "opens_at": (now - timedelta(seconds=5)).isoformat(),
                "closes_at": (now + timedelta(minutes=45)).isoformat(),
            },
        )
        response.raise_for_status()
        auction = response.json()
    (CACHE / "demo-state.json").write_text(json.dumps({"auction_id": auction["id"], "title": title}, indent=2))
    print(
        json.dumps(
            {
                "title": title,
                "auction_id": auction["id"],
                "reserve_cents": 10000,
                "increment_cents": 500,
                "stock": 3,
                "browser": "http://localhost:18080",
                "action": "Select this auction title in each browser profile.",
            },
            indent=2,
        )
    )


def outcomes(client, ids, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        rows = []
        for rid in ids:
            response = client.get("/v1/bid-requests/" + rid)
            response.raise_for_status()
            result = response.json()
            rows.append(
                {
                    "request_id": rid,
                    "state": result["state"],
                    "decision_seq": result["decision"]["decision_seq"] if result["decision"] else None,
                    "reason": result["decision"]["reason"] if result["decision"] else "Waiting",
                }
            )
        if all(row["state"] != "QUEUED" for row in rows):
            return rows
        time.sleep(0.15)
    raise TimeoutError("Decision still pending; show the real pending state and use recorded fallback evidence")


def race():
    demo = state()
    with client_for("admin") as admin, client_for("bidder1") as first, client_for("bidder2") as second:
        snapshot = admin.get("/v1/auctions/" + demo["auction_id"]).json()
        if snapshot["status"] != "OPEN" or datetime.fromisoformat(snapshot["closes_at"]) <= datetime.now(UTC):
            raise RuntimeError("Prepare a fresh open auction before the race")
        amount = snapshot["minimum_next_cents"]
        ids = [str(uuid4()), str(uuid4())]

        def submit(pair):
            client, rid = pair
            response = client.post(
                "/v1/auctions/" + demo["auction_id"] + "/bids", json={"request_id": rid, "amount_cents": amount}
            )
            response.raise_for_status()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(submit, zip([first, second], ids, strict=True)))
        rows = outcomes(admin, ids)
    passed = sorted(row["state"] for row in rows) == ["ACCEPTED", "REJECTED"]
    print(
        json.dumps(
            {
                "scenario": "Two authenticated bidders; same eligible price",
                "amount_cents": amount,
                "status": "PASS" if passed else "FAIL",
                "decisions": rows,
            },
            indent=2,
        )
    )
    if not passed:
        raise RuntimeError("Unexpected outcome; do not present this run as a successful race")


def recover():
    demo = state()
    compose = ["docker", "compose", "--env-file", ".env", "-f", "infra/compose.yaml"]
    with client_for("bidder1") as client:
        response = client.get("/v1/auctions/" + demo["auction_id"])
        response.raise_for_status()
        snapshot = response.json()
        if snapshot["status"] != "OPEN" or datetime.fromisoformat(snapshot["closes_at"]) <= datetime.now(UTC):
            raise RuntimeError("Prepare an open auction first")
        rid = str(uuid4())
        payload = {"request_id": rid, "amount_cents": snapshot["minimum_next_cents"]}
        worker = subprocess.run(
            [*compose, "ps", "-q", "worker"], check=True, capture_output=True, text=True
        ).stdout.strip()
        subprocess.run([*compose, "kill", "-s", "SIGKILL", "worker"], check=True)
        start = time.monotonic()
        try:
            for _ in range(20):
                response = client.post("/v1/auctions/" + demo["auction_id"] + "/bids", json=payload)
                response.raise_for_status()
            print("Intake state with worker stopped:", response.json()["state"], flush=True)
        finally:
            subprocess.run(["docker", "start", worker], check=True)
        rows = outcomes(client, [rid], timeout=30)
        response = client.get("/v1/me/bids")
        response.raise_for_status()
        matches = [row for row in response.json() if row["request_id"] == rid]
        result = {
            "scenario": "Real SIGKILL, 20 identical UUID retries, explicit restart",
            "final_state": rows[0]["state"],
            "matching_requests": len(matches),
            "decision_seq": rows[0]["decision_seq"],
            "elapsed_s": round(time.monotonic() - start, 3),
            "status": "PASS" if rows[0]["state"] == "ACCEPTED" and len(matches) == 1 else "FAIL",
        }
        (CACHE / "demo-recovery.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        if result["status"] != "PASS":
            raise RuntimeError("Recovery did not meet the demo invariant")


def evidence():
    root = Path("docs/evidence")
    specs = [
        (
            "Recorded 50k socket hold",
            "sockets-8be4e979f1bb4723bfcb86fe7a90f37a/summary.json",
            ["status", "simultaneously_held", "overlap_seconds", "handshake_errors", "scope"],
        ),
        (
            "Recorded HA node loss",
            "ha-local.json",
            [
                "status",
                "committed_decisions_preserved",
                "ledger_anchor_matches",
                "leader_epoch_fencing_passed",
                "recovery_s",
                "scope",
            ],
        ),
        (
            "Recorded physical PITR",
            "pitr-local.json",
            ["status", "base_decisions", "restored_decisions", "ledger_anchor_matches", "rto_s", "scope"],
        ),
        (
            "Recorded actual remote S3 restore",
            "s3-offsite.json",
            ["status", "region", "compliance_version_deletion_denied", "offsite_restore_and_verify_s", "scope"],
        ),
    ]
    for title, path, keys in specs:
        record = json.loads((root / path).read_text(encoding="utf-8-sig"))
        print(title)
        print(json.dumps({key: record[key] for key in keys}, indent=2))


def bidding():
    root = Path("docs/evidence")
    index = json.loads((root / "bidding-index.json").read_text())
    records = [
        ("Historical " + label.replace("_", " "), json.loads((root / selected["summary"]).read_text()))
        for label, selected in index["selected"].items()
    ]
    trials = [json.loads((root / trial["summary"]).read_text()) for trial in index["trials"]]
    for profile in ("http_only", "live_and_http"):
        candidates = [
            record
            for record in trials
            if record.get("profile") == profile and record.get("sql", {}).get("requested_bidders") == 50000
        ]
        if candidates:
            latest = max(candidates, key=lambda record: record["timestamp"])
            if not any(record["run_id"] == latest["run_id"] for _, record in records):
                records.append(("Latest " + profile, latest))
    print("RECORDED BIDDING EVIDENCE: historical passes and latest recorded trials")
    print("Eligible = SQL admission timestamp in final ten seconds; pooled HTTP; pre-issued real sessions.")
    print(f"{'Run':<9} {'Profile/fault':<23} {'Eligible':>8} {'Late':>7} {'Errors':>7} {'Gate':<5} {'Tail s':>8}")
    for _, record in records:
        sql = record["sql"]
        eligible = sql["durable_requests"] - sql["outside_server_admission_window"]
        profile = record["profile"] + "/" + record["scenario"]
        print(
            f"{record['run_id'][:8]:<9} {profile:<23} {eligible:>8,} "
            f"{sql['outside_server_admission_window']:>7,} {record['request_errors']:>7,} "
            f"{record['status']:<5} {sql['last_decision_after_deadline_s']:>8.3f}"
        )
    for label, record in records:
        sql = record["sql"]
        if label.startswith("Historical"):
            cutoff = sql["states_at_deadline"]
            final = sql["final_states"]
            print(
                f"{record['run_id'][:8]} cutoff A/R/Q: "
                f"{cutoff.get('ACCEPTED', 0):,}/{cutoff.get('REJECTED', 0):,}/{cutoff.get('QUEUED', 0):,}; "
                f"final A/R: {final.get('ACCEPTED', 0):,}/{final.get('REJECTED', 0):,}; "
                f"signed replay {record['audit']['status']}; {record['winner_count']} winners"
            )
            if record["scenario"] == "worker":
                fault = json.loads((root / ("bids-" + record["run_id"]) / "worker-crash.json").read_text())
                print(
                    f"Worker SIGKILL exit {fault['stopped']['ExitCode']}; "
                    f"epoch {fault['lease_before']['epoch']} -> {sql['lease_after']['epoch']}; "
                    f"checkpoint preserved={sql['pre_crash_checkpoint_preserved']}; "
                    f"stale holder fenced={sql['stale_worker_fenced']}"
                )
    print("Tail = last recorded decision after cutoff; timestamp reconstruction is not exact commit visibility.")
    print("Current repeatable 50k and combined-live capacity remain unproven. See report page 7.")


def verify_bidding():
    from scripts.verify_bid_stress import verify_run

    root = Path("docs/evidence")
    selected = json.loads((root / "bidding-index.json").read_text())["selected"]
    proof = selected.get("live_worker_failure") or selected["http_worker_failure"]
    result = verify_run(root / proof["directory"])
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise RuntimeError("Saved client requests did not match the signed evidence")


def closed_test():
    import pytest

    os.environ["RUN_INTEGRATION"] = "1"
    print("Live isolated API/database regression checks; separate test database, no full-load run.", flush=True)
    raise SystemExit(pytest.main(["-q", "tests/test_late_admission.py"]))


def late():
    aid = state()["auction_id"]
    with client_for("admin") as admin, client_for("bidder1") as bidder:
        response = admin.post(f"/v1/admin/auctions/{aid}/close")
        response.raise_for_status()
        until = time.monotonic() + 30
        while time.monotonic() < until:
            response = admin.get(f"/v1/auctions/{aid}")
            response.raise_for_status()
            if response.json()["status"] == "CLOSED":
                break
            time.sleep(0.15)
        else:
            raise TimeoutError("Auction still draining; do not claim final close")
        response = admin.get(f"/v1/audit/auctions/{aid}")
        response.raise_for_status()
        before = response.json()
        rid = str(uuid4())
        payload = {"request_id": rid, "amount_cents": 10000}
        response = bidder.post(f"/v1/auctions/{aid}/bids", json=payload)
        response.raise_for_status()
        outcome = response.json()["state"]
        response = bidder.get(f"/v1/bid-requests/{rid}")
        response.raise_for_status()
        owner_state = response.json()["state"]
        response = admin.get(f"/v1/audit/auctions/{aid}")
        response.raise_for_status()
        after = response.json()
    preserved = before["anchor"] == after["anchor"] and before["winners"] == after["winners"]
    passed = outcome == owner_state == "CLOSED" and preserved
    print(
        json.dumps(
            {
                "scenario": "New authenticated request after final close",
                "status": "PASS" if passed else "FAIL",
                "final_state": outcome,
                "owner_state": owner_state,
                "sealed_anchor_and_winners_unchanged": preserved,
            },
            indent=2,
        )
    )
    if not passed:
        raise RuntimeError("Late request did not preserve the sealed result")


def check():
    for url in (BASE + "/health", "http://127.0.0.1:18080"):
        httpx.get(url, timeout=10).raise_for_status()
    with client_for("admin") as client:
        client.get("/v1/admin/metrics").raise_for_status()
        client.get("/v1/admin/backups").raise_for_status()
    print("PASS: API, dashboard, authenticated admin metrics and backup records. No cloud calls.")


def bacula():
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env",
            "-f",
            "infra/compose.bacula.yaml",
            "exec",
            "-T",
            "bacula",
            "bconsole",
        ],
        input="list jobs\nquit\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    print(result.stdout)


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for action in (
        "check",
        "prepare",
        "race",
        "recover",
        "evidence",
        "bacula",
        "bidding",
        "verify-bidding",
        "closed-test",
        "late",
    ):
        actions.add_argument("--" + action, action="store_true")
    args = parser.parse_args()
    if os.getenv("ENVIRONMENT", "development") not in ("development", "test"):
        parser.error("Demo actions are restricted to local development/test")
    action = next(name for name, selected in vars(args).items() if selected)
    {
        "check": check,
        "prepare": prepare,
        "race": race,
        "recover": recover,
        "evidence": evidence,
        "bacula": bacula,
        "bidding": bidding,
        "verify_bidding": verify_bidding,
        "closed_test": closed_test,
        "late": late,
    }[action]()
