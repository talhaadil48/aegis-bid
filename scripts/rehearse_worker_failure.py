import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    compose = ["docker", "compose", "--env-file", ".env", "-f", "infra/compose.yaml"]
    password = os.environ["DEMO_PASSWORD"]
    with httpx.Client(base_url="http://127.0.0.1:58000", timeout=30) as client:
        client.post("/v1/auth/login", json={"username": "admin", "password": password}).raise_for_status()
        now = datetime.now(UTC)
        response = client.post(
            "/v1/admin/auctions",
            json={
                "title": "Worker crash rehearsal",
                "stock": 3,
                "min_price_cents": 10000,
                "increment_cents": 500,
                "opens_at": (now - timedelta(seconds=1)).isoformat(),
                "closes_at": (now + timedelta(minutes=10)).isoformat(),
            },
        )
        response.raise_for_status()
        aid = response.json()["id"]
        client.post("/v1/auth/login", json={"username": "bidder2", "password": password}).raise_for_status()
        subprocess.run([*compose, "kill", "-s", "SIGKILL", "worker"], check=True)
        rid = str(uuid4())
        body = {"request_id": rid, "amount_cents": 10000}
        for _ in range(20):
            result = client.post("/v1/auctions/" + aid + "/bids", json=body)
            result.raise_for_status()
        start = time.perf_counter()
        subprocess.run([*compose, "up", "-d", "worker"], check=True)
        state = "QUEUED"
        while time.perf_counter() - start < 45:
            result = client.get("/v1/bid-requests/" + rid)
            result.raise_for_status()
            data = result.json()
            state = data["state"]
            if state != "QUEUED":
                break
            time.sleep(0.2)
        history = client.get("/v1/me/bids").json()
        matches = [r for r in history if r["request_id"] == rid]
        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "scenario": "SIGKILL worker, 20 identical retries, explicit Compose worker restart",
            "request_id": rid,
            "auction_id": aid,
            "final_state": state,
            "matching_requests": len(matches),
            "decision_seq": data.get("decision", {}).get("decision_seq") if data.get("decision") else None,
            "recovery_s": time.perf_counter() - start,
            "status": "PASS" if state == "ACCEPTED" and len(matches) == 1 else "FAIL",
            "scope": "Local process failure and restart; database unique constraint prevents duplicate decisions; not database primary failover",
        }
        path = Path("docs/evidence/worker-failure.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    main()
