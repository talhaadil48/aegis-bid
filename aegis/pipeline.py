import asyncio
import json
import logging
import os
import socket

import nats
from nats.js.api import AckPolicy, ConsumerConfig, StreamConfig

from aegis.config import NATS_URL
from aegis.db import connection
from aegis.engine import Fenced, close, process

log = logging.getLogger("aegis.pipeline")


async def connect():
    nc = await nats.connect(NATS_URL, connect_timeout=2, max_reconnect_attempts=3)
    js = nc.jetstream()
    try:
        await js.stream_info("COMMANDS")
    except nats.js.errors.NotFoundError:
        await js.add_stream(
            config=StreamConfig(
                name="COMMANDS",
                subjects=["auction.*.commands"],
                storage="file",
                num_replicas=int(os.getenv("NATS_REPLICAS", "1")),
                max_bytes=256 * 1024 * 1024,
                discard="new",
            )
        )
    return nc, js


def pending():
    with connection() as c:
        return c.execute(
            "SELECT * FROM bid_requests WHERE published_at IS NULL ORDER BY admitted_at,intake_seq LIMIT 100"
        ).fetchall()


async def relay_once(js):
    for row in await asyncio.to_thread(pending):
        payload = {"schema_version": 1, "request_id": str(row["request_id"]), "auction_id": str(row["auction_id"])}
        await js.publish(
            f"auction.{row['auction_id']}.commands",
            json.dumps(payload).encode(),
            headers={"Nats-Msg-Id": str(row["request_id"])},
        )
        with connection() as c:
            c.execute(
                "UPDATE bid_requests SET published_at=clock_timestamp() WHERE request_id=%s", (row["request_id"],)
            )
    with connection() as c:
        rows = c.execute("SELECT * FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT 100").fetchall()
    for row in rows:
        await js._nc.publish(f"live.{row['auction_id']}", json.dumps(row["body"]).encode())
        await js._nc.flush()
        with connection() as c:
            c.execute("UPDATE outbox SET published_at=clock_timestamp() WHERE id=%s", (row["id"],))


def reconcile(holder):
    with connection() as c:
        if c.execute("SELECT 1 FROM incidents WHERE scenario='pause-queue-consumer' AND state='ACTIVE'").fetchone():
            return
        ids = c.execute("SELECT id FROM auctions WHERE status='OPEN' ORDER BY closes_at LIMIT 100").fetchall()
    for row in ids:
        try:
            for _ in range(100):
                if process(row["id"], holder) is None:
                    break
            close(row["id"], holder)
        except Fenced:
            continue


async def run(mode):
    logging.basicConfig(level=logging.INFO)
    holder = f"{socket.gethostname()}-{os.getpid()}"
    nc, js = await connect()
    sub = None
    if mode == "worker":
        sub = await js.pull_subscribe(
            "auction.*.commands",
            durable="auction-workers",
            config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT, ack_wait=30, max_deliver=20, max_ack_pending=1000),
        )
    try:
        while True:
            try:
                if mode == "relay":
                    await relay_once(js)
                else:
                    # SQL journal reconciliation also recovers commands never published or restored without NATS.
                    await asyncio.to_thread(reconcile, holder)
                    try:
                        messages = await sub.fetch(100, timeout=0.5)
                    except nats.errors.TimeoutError:
                        messages = []
                    for message in messages:
                        payload = json.loads(message.data)
                        with connection() as c:
                            row = c.execute(
                                "SELECT state FROM bid_requests WHERE request_id=%s", (payload["request_id"],)
                            ).fetchone()
                        if row and row["state"] != "QUEUED":
                            await message.ack()
                        else:
                            await message.nak(delay=1)
                await asyncio.sleep(0.1)
            except Exception:
                log.exception("Pipeline iteration failed; durable work retained")
                await asyncio.sleep(1)
    finally:
        await nc.close()


if __name__ == "__main__":
    import sys

    asyncio.run(run(sys.argv[1]))
