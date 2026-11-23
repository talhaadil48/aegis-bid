import asyncio
import os
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import httpx

from scripts.run_load import main as load


def main():
    with httpx.Client(base_url="http://127.0.0.1:58000", timeout=30) as c:
        r = c.post("/v1/auth/login", json={"username": "admin", "password": os.environ["DEMO_PASSWORD"]})
        r.raise_for_status()
        now = datetime.now(UTC)
        r = c.post(
            "/v1/admin/auctions",
            json={
                "title": "Measured demo auction",
                "stock": 3,
                "min_price_cents": 10000,
                "increment_cents": 500,
                "opens_at": (now - timedelta(seconds=1)).isoformat(),
                "closes_at": (now + timedelta(hours=2)).isoformat(),
            },
        )
        r.raise_for_status()
        aid = r.json()["id"]
        with httpx.Client(timeout=30) as web:
            response = web.get("http://127.0.0.1:18080")
            response.raise_for_status()
            assert "AegisBid" in response.text or "AEGISBID" in response.text
        print("API authentication, auction creation and dashboard HTTP smoke passed.")
    args = Namespace(
        url="http://127.0.0.1:58000",
        auction=aid,
        username="bidder1",
        password=os.environ["DEMO_PASSWORD"],
        bids=30,
        concurrency=10,
        amount=10000,
        increment=500,
        timeout=30,
        output="docs/evidence/load-local",
    )
    asyncio.run(load(args))


if __name__ == "__main__":
    main()
