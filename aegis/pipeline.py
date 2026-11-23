import asyncio
import json
import logging
import os
import socket
import ssl
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import nats
from nats.js.api import AckPolicy, ConsumerConfig, StreamConfig

from aegis.config import NATS_URL
from aegis.db import connection
from aegis.engine import Fenced, close, finalize_stranded
from aegis.engine_batch import process_many

log = logging.getLogger("aegis.pipeline")


async def connect():
    ca_file = os.getenv("NATS_CA_FILE")
    if os.getenv("ENVIRONMENT") == "production" and not ca_file:
        raise RuntimeError("Production NATS requires a verified TLS CA")
    tls = ssl.create_default_context(cafile=ca_file) if ca_file else None
    nc = await nats.connect(
        NATS_URL, connect_timeout=2, max_reconnect_attempts=3, tls=tls, tls_hostname=os.getenv("NATS_TLS_SERVER_NAME")
    )
    js = nc.jetstream()
    try:
        info = await js.stream_info("COMMANDS")
        if info.config.num_replicas != int(os.getenv("NATS_REPLICAS", "1")):
            await nc.close()
            raise RuntimeError("Existing stream replication differs from required durability; migrate explicitly")
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
            "SELECT * FROM bid_requests WHERE published_at IS NULL ORDER BY admitted_at,intake_seq LIMIT 1000"
        ).fetchall()


async def relay_once(js):
    rows = await asyncio.to_thread(pending)
    for start in range(0, len(rows), 100):
        batch = rows[start : start + 100]
        await asyncio.gather(
            *(
                js.publish(
                    f"auction.{r['auction_id']}.commands",
                    json.dumps(
                        {"schema_version": 1, "request_id": str(r["request_id"]), "auction_id": str(r["auction_id"])}
                    ).encode(),
                    headers={"Nats-Msg-Id": str(r["request_id"])},
                )
                for r in batch
            )
        )
        with connection() as c:
            c.execute(
                "UPDATE bid_requests SET published_at=clock_timestamp() WHERE request_id=ANY(%s)",
                ([r["request_id"] for r in batch],),
            )
    with connection() as c:
        rows = c.execute("SELECT * FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT 1000").fetchall()
    for row in rows:
        await js._nc.publish(f"live.{row['auction_id']}", json.dumps(row["body"]).encode())
    if rows:
        await js._nc.flush()
        with connection() as c:
            c.execute(
                "UPDATE outbox SET published_at=clock_timestamp() WHERE id=ANY(%s)", ([row["id"] for row in rows],)
            )


def reconcile(holder):
    finalize_stranded()
    processed = 0
    with connection() as c:
        if c.execute("SELECT 1 FROM incidents WHERE scenario='pause-queue-consumer' AND state='ACTIVE'").fetchone():
            return 0
        ids = c.execute("SELECT id FROM auctions WHERE status='OPEN' ORDER BY closes_at LIMIT 100").fetchall()
    for row in ids:
        try:
            for _ in range(8):
                batch = process_many(row["id"], holder)
                processed += len(batch)
                if len(batch) < 512:
                    break
            close(row["id"], holder)
        except Fenced:
            continue
    return processed


async def run(mode):
    logging.basicConfig(level=logging.INFO)
    holder = f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:12]}"
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
                    processed = await asyncio.to_thread(reconcile, holder)
                    try:
                        messages = await sub.fetch(100, timeout=0.05 if processed else 0.5)
                    except nats.errors.TimeoutError:
                        messages = []
                    payloads = [(message, json.loads(message.data)["request_id"]) for message in messages]
                    with connection() as c:
                        resolved = (
                            {
                                str(r["request_id"])
                                for r in c.execute(
                                    "SELECT request_id FROM bid_requests WHERE request_id=ANY(%s::uuid[]) AND state<>'QUEUED'",
                                    ([rid for _, rid in payloads],),
                                ).fetchall()
                            }
                            if payloads
                            else set()
                        )
                    for message, rid in payloads:
                        if rid in resolved:
                            await message.ack()
                        else:
                            await message.nak(delay=1)
                await asyncio.sleep(0.005 if mode == "worker" and processed else 0.1)
                Path(
                    os.getenv("PIPELINE_HEALTH_FILE", str(Path(tempfile.gettempdir()) / "aegis-pipeline-health"))
                ).write_text(str(time.time()))
            except Exception:
                log.exception("Pipeline iteration failed; durable work retained")
                await asyncio.sleep(1)
    finally:
        await nc.close()


if __name__ == "__main__":
    import sys

    asyncio.run(run(sys.argv[1]))
