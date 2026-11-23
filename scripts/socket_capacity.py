"""Local Docker shards; the same Go generator can run on independent load hosts."""

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx


def aggregate(reports, required, minimum_overlap=30):
    if not reports:
        return {"status": "FAIL", "reason": "No shard reports"}
    runs = {r["run_id"] for r in reports}
    shards = {r["shard"] for r in reports}
    start = max(datetime.fromisoformat(r["hold_started_at"]) for r in reports)
    end = min(datetime.fromisoformat(r["hold_ended_at"]) for r in reports)
    overlap = max(0, (end - start).total_seconds())
    held = sum(r["held_end"] for r in reports)
    valid = len(runs) == 1 and len(shards) == len(reports) and held >= required and overlap >= minimum_overlap
    valid = valid and all(
        r["requested"] == r["held_start"] == r["held_end"] and r["handshake_errors"] == 0 for r in reports
    )
    return {
        "status": "PASS" if valid else "FAIL",
        "run_id": reports[0]["run_id"],
        "requested": sum(r["requested"] for r in reports),
        "simultaneously_held": held,
        "overlap_seconds": overlap,
        "required": required,
        "shards": len(reports),
        "handshake_errors": sum(r["handshake_errors"] for r in reports),
        "scope": "Local Docker socket capacity; shared demo identity; not independent hosts, unique bidders or bid throughput",
    }


def run(args):
    with httpx.Client(base_url=args.api, timeout=30) as client:
        response = client.post("/v1/auth/login", json={"username": "bidder1", "password": os.environ["DEMO_PASSWORD"]})
        response.raise_for_status()
        cookie = client.cookies.get("aegis_session")
        auctions = client.get("/v1/auctions").json()
        if not auctions:
            raise ValueError("Create an auction first")
        aid = args.auction or auctions[0]["id"]
    run_id = uuid4().hex
    directory = Path("docs/evidence") / ("sockets-" + run_id)
    directory.mkdir(parents=True)
    directory.chmod(0o777)
    counts = [args.connections // args.shards + (i < args.connections % args.shards) for i in range(args.shards)]
    containers = []
    env = {**os.environ, "WS_COOKIE": cookie, "RUN_ID": run_id}
    samples = []
    try:
        for index, count in enumerate(counts):
            name = f"aegis-load-{run_id[:8]}-{index}"
            containers.append(name)
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    args.network,
                    "--ulimit",
                    "nofile=100000:100000",
                    "-e",
                    "WS_COOKIE",
                    "-e",
                    "RUN_ID",
                    "-e",
                    f"SHARD_ID={index}",
                    "-v",
                    f"{directory.resolve()}:/results",
                    "--entrypoint",
                    "/usr/local/bin/load",
                    args.image,
                    "-url",
                    f"ws://gateway:8081/v1/live/auctions/{aid}",
                    "-connections",
                    str(count),
                    "-ramp",
                    str(args.ramp),
                    "-hold",
                    f"{args.hold}s",
                    "-output",
                    f"/results/shard-{index}.json",
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        deadline = time.monotonic() + args.hold + max(180, args.connections / 50)
        while time.monotonic() < deadline:
            states = [
                subprocess.check_output(
                    ["docker", "inspect", "--format", "{{.State.Running}}", name], text=True
                ).strip()
                for name in containers
            ]
            if all(state == "false" for state in states):
                break
            try:
                metrics = httpx.get("http://127.0.0.1:18081/metrics", timeout=5).text
                samples.append({"at": datetime.now(UTC).isoformat(), "metrics": metrics})
            except httpx.HTTPError:
                samples.append({"at": datetime.now(UTC).isoformat(), "metrics": "unavailable"})
            time.sleep(3)
        reports = [json.loads(path.read_text()) for path in sorted(directory.glob("shard-*.json"))]
        report = aggregate(reports, args.connections, min(30, args.hold * 0.5))
        if len(reports) != args.shards:
            report.update(status="FAIL", reason="Missing shard reports")
        report.update(
            commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            sampled_at=datetime.now(UTC).isoformat(),
            gateway_samples=samples,
            machine=subprocess.check_output(
                ["docker", "info", "--format", "{{.NCPU}} CPUs {{.MemTotal}} bytes"], text=True
            ).strip(),
        )
        (directory / "summary.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k != "gateway_samples"}, indent=2))
        return report["status"] == "PASS"
    finally:
        for name in containers:
            subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--connections", type=int, default=100)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--ramp", type=int, default=50)
    parser.add_argument("--hold", type=int, default=60)
    parser.add_argument("--auction")
    parser.add_argument("--api", default="http://127.0.0.1:58000")
    parser.add_argument("--network", default="infra_default")
    parser.add_argument("--image", default="infra-gateway")
    args = parser.parse_args()
    if args.connections < 1 or args.shards < 1 or args.shards > args.connections or args.hold < 2:
        parser.error("Positive counts, at most one shard per connection, hold >= 2s required")
    raise SystemExit(0 if run(args) else 1)
