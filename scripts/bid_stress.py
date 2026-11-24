"""Isolated distinct-user close-window bidding and real worker-crash proof; no cloud calls."""

import argparse
import csv
import gzip
import hashlib
import json
import os
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegis import config, db
from aegis.auth import hash_password, token
from aegis.db import connection, migrate
from aegis.engine import Fenced
from aegis.engine_batch import process_many
from aegis.evidence import export_auction
from aegis.verifier import verify

ROOT = Path(__file__).resolve().parents[1]


def command(args, env=None, quiet=True):
    return subprocess.run(args, cwd=ROOT, env=env, check=True, capture_output=quiet, text=True).stdout


def write_json(path, value, private=False):
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    if private:
        path.chmod(0o600)


def quantiles(values):
    ordered = sorted(values)
    return {
        f"p{int(q * 100)}": ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1)))] if ordered else None
        for q in [0.5, 0.95, 0.99]
    }


def sample(aid):
    with connection() as c:
        return c.execute(
            "SELECT clock_timestamp() at,a.status,a.version,"
            "(SELECT count(*) FROM bid_requests WHERE auction_id=a.id) admitted,"
            "(SELECT count(*) FROM bid_requests WHERE auction_id=a.id AND state='QUEUED') queued,"
            "(SELECT count(*) FROM bid_decisions WHERE auction_id=a.id AND status='ACCEPTED') accepted,"
            "(SELECT count(*) FROM bid_decisions WHERE auction_id=a.id AND status='REJECTED') rejected,"
            "(SELECT count(*) FROM admission_outcomes o JOIN bid_requests r USING(request_id) WHERE r.auction_id=a.id) late,"
            "(SELECT count(*) FROM command_queue q JOIN bid_requests r USING(request_id) WHERE r.auction_id=a.id AND q.published_at IS NULL) unpublished "
            "FROM auctions a WHERE id=%s",
            (aid,),
        ).fetchone()


def seed(count, run_id):
    profiles = [
        {"id": uuid4(), "request_id": uuid4(), "amount_cents": 10000 + i * 10, "index": i} for i in range(count)
    ]
    owner, aid = uuid4(), uuid4()
    password_hash = hash_password(secrets.token_urlsafe(32))
    with connection() as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        with c.cursor().copy("COPY users(id,username,password_hash,role) FROM STDIN") as copy:
            copy.write_row((owner, f"stress-owner-{run_id}", password_hash, "admin"))
            for p in profiles:
                copy.write_row((p["id"], f"stress-{run_id}-{p['index']}", password_hash, "bidder"))
        now = datetime.now(UTC)
        c.execute(
            "INSERT INTO auctions(id,seller_id,title,stock,min_price_cents,increment_cents,opens_at,closes_at) VALUES(%s,%s,%s,20,10000,10,%s,%s)",
            (aid, owner, f"Distinct bidder stress {run_id}", now - timedelta(minutes=1), now + timedelta(minutes=20)),
        )
    for p in profiles:
        p["token"] = token({"id": p["id"]})
    return aid, owner, profiles


def crash(compose, env, aid):
    with connection() as c:
        before = c.execute(
            "SELECT event_seq,event_hash FROM auction_events WHERE auction_id=%s ORDER BY event_seq DESC LIMIT 1",
            (aid,),
        ).fetchone()
        lease = c.execute("SELECT holder_id,epoch FROM worker_leases WHERE auction_id=%s", (aid,)).fetchone()
        busy = c.execute(
            "SELECT count(*) n FROM pg_stat_activity WHERE application_name='aegis-stress-worker' AND state='active'"
        ).fetchone()["n"]
    cid = command([*compose, "ps", "-q", "worker"], env).strip()
    record = {
        "requested_at": datetime.now(UTC).isoformat(),
        "checkpoint": before,
        "lease_before": lease,
        "active_db_sessions_before": busy,
        "before": sample(aid),
    }
    command(["docker", "kill", "--signal", "KILL", cid])
    record["stopped"] = json.loads(command(["docker", "inspect", "--format", "{{json .State}}", cid]))
    time.sleep(0.5)
    command([*compose, "start", "worker"], env)
    record["restart_requested_at"] = datetime.now(UTC).isoformat()
    record["running_after_start"] = (
        command(["docker", "inspect", "--format", "{{.State.Running}}", cid]).strip() == "true"
    )
    return record


def validate(aid, profiles, start, end, fault, api_url, owner):
    expected = {str(p["request_id"]): p for p in profiles}
    with connection() as c:
        rows = c.execute(
            "SELECT r.*,d.status decision_status,d.effective_amount_cents,d.committed_at,d.decision_seq,o.status admission_status FROM bid_requests r LEFT JOIN bid_decisions d USING(request_id) LEFT JOIN admission_outcomes o USING(request_id) WHERE r.auction_id=%s ORDER BY r.intake_seq",
            (aid,),
        ).fetchall()
        lease = c.execute("SELECT holder_id,epoch FROM worker_leases WHERE auction_id=%s", (aid,)).fetchone()
        durability = {
            name: c.execute("SELECT current_setting(%s) value", (name,)).fetchone()["value"]
            for name in ("fsync", "synchronous_commit", "full_page_writes")
        }
        server = c.execute("SELECT version() v").fetchone()["v"]
    wrong, late = 0, 0
    states = {}
    at_deadline = {"ACCEPTED": 0, "REJECTED": 0, "QUEUED": 0, "CLOSED": 0}
    latencies = []
    for row in rows:
        p = expected.get(str(row["request_id"]))
        valid_payload = p and str(row["bidder_id"]) == str(p["id"]) and row["amount_cents"] == p["amount_cents"]
        valid_result = (
            row["state"] == row["decision_status"] and row["effective_amount_cents"] == row["amount_cents"]
        ) or (row["state"] == row["admission_status"] == "CLOSED")
        if not valid_payload or not valid_result:
            wrong += 1
        states[row["state"]] = states.get(row["state"], 0) + 1
        if not start <= row["admitted_at"] < end:
            late += 1
        if row["committed_at"]:
            latencies.append((row["committed_at"] - row["admitted_at"]).total_seconds())
        if row["admitted_at"] < end:
            at_deadline[row["decision_status"] if row["committed_at"] and row["committed_at"] < end else "QUEUED"] += 1
    checkpoint_preserved = True
    if fault and fault["checkpoint"]:
        with connection() as c:
            found = c.execute(
                "SELECT event_hash FROM auction_events WHERE auction_id=%s AND event_seq=%s",
                (aid, fault["checkpoint"]["event_seq"]),
            ).fetchone()
        checkpoint_preserved = bool(found and found["event_hash"] == fault["checkpoint"]["event_hash"])
    stale_worker_fenced = not fault
    if fault and fault["lease_before"]:
        try:
            process_many(aid, fault["lease_before"]["holder_id"], expected_epoch=fault["lease_before"]["epoch"])
        except Fenced:
            stale_worker_fenced = True
    sample_profiles = profiles[:: max(1, len(profiles) // 64)][:64]
    owner_history_checks = 0
    retry_checks = 0
    with httpx.Client(base_url=api_url, timeout=30) as client:
        for p in sample_profiles:
            headers = {"Cookie": "aegis_session=" + p["token"]}
            response = client.get("/v1/bid-requests/" + str(p["request_id"]), headers=headers)
            if response.status_code != 200:
                continue
            status = response.json()
            history = client.get("/v1/me/bids", headers=headers)
            history.raise_for_status()
            matches = [r for r in history.json() if r["request_id"] == str(p["request_id"])]
            owner_history_checks += int(
                len(matches) == 1
                and matches[0]["state"] == status["state"]
                and status["state"] != "QUEUED"
                and matches[0]["amount_cents"] == p["amount_cents"]
            )
            response = client.post(
                f"/v1/auctions/{aid}/bids",
                json={"request_id": str(p["request_id"]), "amount_cents": p["amount_cents"]},
                headers=headers,
            )
            retry_checks += int(response.status_code == 200 and response.json()["state"] == status["state"])
    return {
        "requested_bidders": len(profiles),
        "durable_requests": len(rows),
        "distinct_bidder_ids": len({r["bidder_id"] for r in rows}),
        "missing_request_ids": len(set(expected) - {str(r["request_id"]) for r in rows}),
        "payload_or_history_mismatches": wrong,
        "outside_server_admission_window": late,
        "final_states": states,
        "states_at_deadline": at_deadline,
        "decision_latency_s": quantiles(latencies),
        "last_decision_after_deadline_s": max(
            [0] + [(r["committed_at"] - end).total_seconds() for r in rows if r["committed_at"]]
        ),
        "full_sql_histories_checked": len(rows),
        "owner_http_history_checks": owner_history_checks,
        "owner_http_history_expected": len(sample_profiles),
        "idempotent_http_retries": retry_checks,
        "pre_crash_checkpoint_preserved": checkpoint_preserved,
        "stale_worker_fenced": stale_worker_fenced,
        "lease_after": lease,
        "durability_settings": durability,
        "postgres_version": server,
        "auction_status": sample(aid)["status"],
    }


def run(args):
    run_id = uuid4().hex
    project = "aegis-stress-" + run_id[:10]
    private = ROOT / ".cache" / "bid-stress" / run_id
    output = ROOT / "docs" / "evidence" / ("bids-" + run_id)
    private.mkdir(parents=True)
    private.chmod(0o700)
    output.mkdir(parents=True)
    output.chmod(0o777)
    database = "aegis_stress_" + run_id[:10]
    password, session_key = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    env = {
        **os.environ,
        "STRESS_DATABASE": database,
        "STRESS_DB_PASSWORD": password,
        "STRESS_SESSION_SECRET": session_key,
        "STRESS_API_WORKERS": str(args.workers),
        "STRESS_ADMISSION_KEY": secrets.token_urlsafe(48),
    }
    compose = ["docker", "compose", "-p", project, "-f", "infra/compose.stress.yaml"]
    write_json(
        private / "compose-environment.json", {k: v for k, v in env.items() if k.startswith("STRESS_")}, private=True
    )
    old_url, old_secret = db.DATABASE_URL, config.SECRET
    old_signing_key = os.environ.get("AUDIT_SIGNING_KEY")
    containers = []
    samples = []
    stop_resources = Event()

    def resource_monitor():
        with (output / "resources.jsonl").open("w", encoding="utf-8") as stream:
            while not stop_resources.is_set():
                raw = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                    text=True,
                    capture_output=True,
                    check=False,
                ).stdout
                values = [json.loads(line) for line in raw.splitlines() if line.strip()]
                stream.write(
                    json.dumps(
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "containers": [v for v in values if v["Name"].startswith(project + "-")],
                        }
                    )
                    + "\n"
                )
                stream.flush()
                stop_resources.wait(1)

    resource_thread = None
    fault = None
    report = {"run_id": run_id, "status": "FAIL", "requested_bidders": args.bidders}
    try:
        if not args.skip_build:
            command(["docker", "build", "-t", "aegis-stress-app:local", "-f", "infra/Dockerfile", "."])
            command(["docker", "build", "-t", "aegis-stress-tools:local", "-f", "infra/Realtime.Dockerfile", "."])
        print(f"Starting isolated project {project}; {args.bidders} distinct bidders", flush=True)
        command([*compose, "up", "-d"], env)
        resource_thread = Thread(target=resource_monitor, daemon=True)
        resource_thread.start()
        db.close_pools()
        db.DATABASE_URL = f"postgresql://aegis:{password}@127.0.0.1:55440/{database}"
        config.SECRET = session_key
        migrate()
        aid, owner, profiles = seed(args.bidders, run_id)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                httpx.get("http://127.0.0.1:15810/health", timeout=2).raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise TimeoutError("Isolated API did not become ready")
        shards = min(args.shards, args.bidders)
        for shard in range(shards):
            shard_profiles = profiles[shard::shards]
            path = private / f"shard-{shard}.json"
            write_json(
                path,
                {
                    "run_id": run_id,
                    "shard": shard,
                    "api_url": "http://admission:8081" if args.ingress == "gateway" else "http://api:8000",
                    "ws_url": f"ws://gateway:8081/v1/live/auctions/{aid}",
                    "auction_id": aid,
                    "total": args.bidders,
                    "live_sockets": not args.no_sockets,
                    "users": shard_profiles,
                },
                private=True,
            )
            name = project + f"-load-{shard}"
            containers.append(name)
            command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    project + "_default",
                    "--user",
                    "0:0",
                    "-e",
                    "GOMAXPROCS=2",
                    "--read-only",
                    "--ulimit",
                    "nofile=100000:100000",
                    "-v",
                    f"{private}:/control:ro",
                    "-v",
                    f"{output}:/results",
                    "--entrypoint",
                    "/usr/local/bin/stress",
                    "aegis-stress-tools:local",
                    "-config",
                    f"/control/shard-{shard}.json",
                    "-ramp",
                    str(args.ramp),
                ]
            )
        ramp_deadline = time.monotonic() + args.ramp_timeout
        while time.monotonic() < ramp_deadline:
            ready_files = list(output.glob("ready-*.json"))
            if len(ready_files) == shards:
                ready = [json.loads(p.read_text()) for p in ready_files]
                if not args.no_sockets and sum(r["active"] for r in ready) != args.bidders:
                    raise RuntimeError("Not all distinct-bidder sockets connected; see ready reports")
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("Distinct socket ramp did not complete")
        with connection() as c:
            now = c.execute("SELECT clock_timestamp() t").fetchone()["t"]
            start, end = now + timedelta(seconds=4), now + timedelta(seconds=14)
            c.execute(
                "UPDATE auctions SET opens_at=%s,closes_at=%s WHERE id=%s", (start - timedelta(seconds=10), end, aid)
            )
        write_json(
            private / "start.json",
            {"start": start.isoformat(), "close": end.isoformat(), "spread_seconds": args.spread},
        )
        print(
            f"All {args.bidders} authenticated {'sessions' if args.no_sockets else 'sockets'} ready. Final ten-second window starts {start.isoformat()}; fault={args.fault}",
            flush=True,
        )
        until = time.monotonic() + args.drain_timeout + 14
        crashed = False
        next_progress = 0
        while time.monotonic() < until:
            row = sample(aid)
            samples.append(row)
            now = datetime.now(UTC)
            if args.fault == "worker" and not crashed and now >= start + timedelta(seconds=4):
                fault = crash(compose, env, aid)
                crashed = True
                write_json(output / "worker-crash.json", fault)
                print("Real worker SIGKILL confirmed; restarted with a new holder identity", flush=True)
            if time.monotonic() >= next_progress:
                print(
                    f"SQL admitted={row['admitted']} accepted={row['accepted']} rejected={row['rejected']} queued={row['queued']} late={row['late']} status={row['status']}",
                    flush=True,
                )
                next_progress = time.monotonic() + 5
            if len(list(output.glob("ingress-*.json"))) == shards and row["status"] == "CLOSED" and row["queued"] == 0:
                break
            time.sleep(1)
        else:
            raise TimeoutError("Bidding did not reach final results within the drain timeout")
        print(
            "Checking every SQL request, sampled private histories, retries and independent signed replay", flush=True
        )
        key = Ed25519PrivateKey.generate()
        key_path = private / "audit-private.pem"
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        key_path.chmod(0o600)
        public = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        (output / "audit-public-key.txt").write_bytes(public)
        os.environ["AUDIT_SIGNING_KEY"] = str(key_path)
        audit = export_auction(aid)
        replay = verify(audit, public)
        tampered = {**audit, "winners": []}
        tamper_result = verify(tampered, public)
        with gzip.open(output / "signed-auction.json.gz", "wt", encoding="utf-8") as f:
            json.dump(audit, f, separators=(",", ":"))
        truth = validate(aid, profiles, start, end, fault, "http://127.0.0.1:15810", owner)
        with connection() as c:
            query_costs = c.execute(
                "SELECT left(query,300) query,calls,total_exec_time,mean_exec_time,rows FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 25"
            ).fetchall()
        write_json(output / "query-costs.json", query_costs)
        # New late requests must finalize without adding events after the signed close.
        p = profiles[0]
        with httpx.Client(base_url="http://127.0.0.1:15810", timeout=30) as client:
            response = client.post(
                f"/v1/auctions/{aid}/bids",
                json={"request_id": str(uuid4()), "amount_cents": 10000},
                headers={"Cookie": "aegis_session=" + p["token"]},
            )
            response.raise_for_status()
            late_status = response.json()["state"]
        truth["post_close_new_request_terminal"] = late_status == "CLOSED"
        truth["sealed_anchor_unchanged_after_late_request"] = export_auction(aid)["anchor"] == audit["anchor"]
        (private / "stop").write_text("stop")
        until = time.monotonic() + 30
        while len(list(output.glob("shard-*.json"))) < shards and time.monotonic() < until:
            time.sleep(0.2)
        shard_reports = [json.loads(p.read_text()) for p in sorted(output.glob("shard-*.json"))]
        rows = []
        for path in sorted(output.glob("requests-*.csv")):
            with path.open(newline="", encoding="utf-8") as f:
                rows.extend(csv.DictReader(f))
        request_errors = sum(r["request_errors"] for r in shard_reports)
        population_ok = args.no_sockets or (
            len(shard_reports) == shards
            and sum(r["active_at_window_start"] for r in shard_reports) == args.bidders
            and sum(r["active_at_end"] for r in shard_reports) == args.bidders
        )
        workload_ok = (
            truth["durable_requests"] == truth["distinct_bidder_ids"] == args.bidders
            and truth["outside_server_admission_window"] == 0
            and sum(r["writes_in_window"] for r in shard_reports) == args.bidders
            and request_errors == 0
        )
        correctness_ok = (
            truth["payload_or_history_mismatches"]
            == truth["missing_request_ids"]
            == truth["final_states"].get("QUEUED", 0)
            == 0
            and replay["status"] == "PASS"
            and tamper_result["status"] == "FAIL"
            and truth["owner_http_history_checks"]
            == truth["idempotent_http_retries"]
            == truth["owner_http_history_expected"]
            and truth["sealed_anchor_unchanged_after_late_request"]
            and truth["post_close_new_request_terminal"]
        )
        fault_ok = not fault or (
            not fault["stopped"]["Running"]
            and fault["stopped"]["ExitCode"] == 137
            and fault["running_after_start"]
            and truth["pre_crash_checkpoint_preserved"]
            and truth["stale_worker_fenced"]
            and fault["lease_before"]
            and truth["lease_after"]["epoch"] > fault["lease_before"]["epoch"]
            and fault["before"]["admitted"] > 0
            and start <= datetime.fromisoformat(fault["requested_at"]) < end
        )
        report = {
            "run_id": run_id,
            "status": "PASS" if population_ok and workload_ok and correctness_ok and fault_ok else "FAIL",
            "commit": command(["git", "rev-parse", "HEAD"]).strip(),
            "source_files_changed": bool(
                command(["git", "status", "--porcelain", "--", "aegis", "scripts", "infra", "services"]).strip()
            ),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "timestamp": datetime.now(UTC).isoformat(),
            "scenario": args.fault,
            "profile": "http_only" if args.no_sockets else "live_and_http",
            "bid_ingress": args.ingress,
            "separate_admission_and_realtime_services": True,
            "auction_id": str(aid),
            "window_start": start.isoformat(),
            "window_close": end.isoformat(),
            "window_s": 10,
            "offered_spread_s": args.spread,
            "api_workers": args.workers,
            "shards": shards,
            "max_generator_http_connections": shards * 1024,
            "transport_warmup_health_requests": shards * 256,
            "population_gate": population_ok,
            "close_window_gate": workload_ok,
            "correctness_gate": correctness_ok,
            "failure_gate": bool(fault_ok),
            "request_errors": request_errors,
            "distinct_authenticated_sockets_at_start": sum(r["active_at_window_start"] for r in shard_reports),
            "distinct_authenticated_sockets_at_end": sum(r["active_at_end"] for r in shard_reports),
            "client_write_count_in_window": sum(r["writes_in_window"] for r in shard_reports),
            "http_ingress_latency_s": quantiles([float(r["ingress_s"]) for r in rows]),
            "audit": replay,
            "tampered_winners_verification": tamper_result["status"],
            "winner_count": len(audit["winners"]),
            "winning_amount_total_cents": sum(w["amount_cents"] for w in audit["winners"]),
            "sql": truth,
            "machine": command(["docker", "info", "--format", "{{.NCPU}} CPUs {{.MemTotal}} bytes"]).strip(),
            "app_image_id": command(["docker", "inspect", project + "-api-1", "--format", "{{.Image}}"]).strip(),
            "tools_image_id": command(["docker", "inspect", project + "-gateway-1", "--format", "{{.Image}}"]).strip(),
            "scope": "One local Docker host; distinct seeded users and pre-issued real HS256 sessions; HTTP connections pooled across virtual users. Profile explicitly identifies whether live sockets were held. 50k bidding claim requires 50,000 users and every gate passing. No password-login throughput, independent load hosts or real cloud zones claimed.",
        }
        write_json(output / "summary.json", report)
        write_json(output / "sql-timeline.json", samples)
        print(json.dumps(report, indent=2, default=str), flush=True)
        return report["status"] == "PASS"
    except (RuntimeError, TimeoutError, subprocess.CalledProcessError, httpx.HTTPError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            (private / "command-error.log").write_text((error.stdout or "") + (error.stderr or ""), encoding="utf-8")
        report["error"] = type(error).__name__ + ": " + str(error)
        write_json(output / "summary.json", report)
        write_json(output / "sql-timeline.json", samples)
        print(json.dumps(report, indent=2), flush=True)
        return False
    finally:
        stop_resources.set()
        if resource_thread:
            resource_thread.join(timeout=5)
        (private / "stop").write_text("stop")
        for name in containers:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        # Private logs can contain operational details; never copy them to evidence.
        try:
            (private / "services.log").write_text(
                command([*compose, "logs", "--no-color", "--tail", "200"], env), encoding="utf-8"
            )
        except subprocess.CalledProcessError:
            pass
        if not args.keep:
            command([*compose, "down", "--volumes"], env)
        for path in output.glob("requests-*.csv"):
            with path.open("rb") as source, gzip.open(path.with_suffix(".csv.gz"), "wb") as target:
                target.write(source.read())
            path.unlink()
        db.close_pools()
        db.DATABASE_URL, config.SECRET = old_url, old_secret
        if old_signing_key is None:
            os.environ.pop("AUDIT_SIGNING_KEY", None)
        else:
            os.environ["AUDIT_SIGNING_KEY"] = old_signing_key


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bidders", type=int, default=500)
    parser.add_argument("--shards", type=int, default=5)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--ramp", type=int, default=50)
    parser.add_argument("--ramp-timeout", type=float, default=240)
    parser.add_argument("--drain-timeout", type=float, default=120)
    parser.add_argument("--spread", type=float, default=9)
    parser.add_argument("--fault", choices=["none", "worker"], default="none")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--no-sockets", action="store_true", help="Separate HTTP bidding calibration; does not claim held sockets"
    )
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--ingress", choices=["direct", "gateway"], default="gateway")
    args = parser.parse_args()
    if (
        not 1 <= args.bidders <= 50000
        or not 1 <= args.shards <= 10
        or not 1 <= args.workers <= 12
        or not 0 < args.spread < 10
    ):
        parser.error("Require 1..50000 bidders, 1..10 shards, 1..12 workers and a spread below 10 seconds")
    raise SystemExit(0 if run(args) else 1)
