import asyncio
import os
import uuid

import pytest

from aegis.db import connection
from aegis.engine import admit
from aegis.pipeline import connect, reconcile, relay_once


def test_real_jetstream_relay(auction):
    if os.getenv("RUN_NATS") != "1":
        pytest.skip("Set RUN_NATS=1 with a disposable JetStream server")
    aid, bidder = auction
    rid = uuid.uuid4()
    admit(aid, bidder, rid, 100)

    async def scenario():
        nc, js = await connect()
        try:
            await relay_once(js)
            info = await js.stream_info("COMMANDS")
            assert info.state.messages > 0
            reconcile("integration-worker")
            await relay_once(js)
        finally:
            await nc.close()

    asyncio.run(scenario())
    with connection() as c:
        assert (
            c.execute("SELECT state,published_at FROM bid_requests WHERE request_id=%s", (rid,)).fetchone()["state"]
            == "ACCEPTED"
        )
        assert (
            c.execute("SELECT published_at FROM outbox WHERE auction_id=%s", (aid,)).fetchone()["published_at"]
            is not None
        )
