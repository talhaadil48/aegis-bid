"""HTTP workload: reports actual completion latency; never labels it socket capacity."""

import argparse
import asyncio
import csv
import json
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx


async def main(args):
    semaphore = asyncio.Semaphore(args.concurrency)
    rows = []
    async with httpx.AsyncClient(base_url=args.url, timeout=30) as client:
        response = await client.post("/v1/auth/login", json={"username": args.username, "password": args.password})
        response.raise_for_status()

        async def bid(index):
            async with semaphore:
                rid = str(uuid4())
                start = time.perf_counter()
                state = "ERROR"
                response = await client.post(
                    f"/v1/auctions/{args.auction}/bids",
                    json={"request_id": rid, "amount_cents": args.amount + index * args.increment},
                )
                ingress = time.perf_counter() - start
                if response.status_code == 202:
                    state = "QUEUED"
                    while time.perf_counter() - start < args.timeout:
                        result = await client.get("/v1/bid-requests/" + rid)
                        result.raise_for_status()
                        state = result.json()["state"]
                        if state != "QUEUED":
                            break
                        await asyncio.sleep(0.05)
                rows.append(
                    {
                        "request_id": rid,
                        "http_status": response.status_code,
                        "state": state,
                        "ingress_s": ingress,
                        "decision_s": time.perf_counter() - start,
                    }
                )

        start = time.perf_counter()
        await asyncio.gather(*(bid(i) for i in range(args.bids)))
        elapsed = time.perf_counter() - start
    latencies = sorted(r["decision_s"] for r in rows if r["state"] in ("ACCEPTED", "REJECTED", "CLOSED"))

    def quantile(q):
        return latencies[min(len(latencies) - 1, int(q * (len(latencies) - 1)))] if latencies else None

    report = {
        "run_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": (await asyncio.to_thread(subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True)).strip(),
        "machine": platform.platform(),
        "bids": args.bids,
        "concurrency": args.concurrency,
        "elapsed_s": elapsed,
        "completed_per_second": len(latencies) / elapsed,
        "p50_s": quantile(0.5),
        "p95_s": quantile(0.95),
        "p99_s": quantile(0.99),
        "error_rate": sum(r["state"] in ("ERROR", "QUEUED") for r in rows) / len(rows),
        "websocket_connections": "NOT_MEASURED",
        "scope": "Single authenticated user; per-user rate limits intentionally apply; HTTP end-to-end decision latency",
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(report, indent=2))
    with path.with_suffix(".csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    import os

    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:58000")
    p.add_argument("--auction", required=True)
    p.add_argument("--username", default="bidder1")
    p.add_argument("--bids", type=int, default=30)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--amount", type=int, default=10000)
    p.add_argument("--increment", type=int, default=500)
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--output", default="docs/evidence/load")
    args = p.parse_args()
    if args.bids < 1 or args.concurrency < 1:
        p.error("Positive workload required")
    args.password = os.environ["DEMO_PASSWORD"]
    asyncio.run(main(args))
