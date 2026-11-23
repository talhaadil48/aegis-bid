import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import nats
from nats.js.api import StreamConfig

COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    ".env",
    "-p",
    "aegis-cluster",
    "-f",
    "infra/compose.yaml",
    "-f",
    "infra/compose.cluster.yaml",
]


async def main():
    os.environ["NATS_PORT"] = "54322"
    nc = await nats.connect("nats://127.0.0.1:54322")
    js = nc.jetstream(timeout=3)
    await js.add_stream(config=StreamConfig(name="PROBE", subjects=["probe"], num_replicas=3, storage="file"))
    first = await js.publish("probe", b"healthy")
    await asyncio.to_thread(subprocess.run, [*COMPOSE, "stop", "nats3"], check=True)
    await asyncio.sleep(3)
    second = await js.publish("probe", b"one-node-down")
    await asyncio.to_thread(subprocess.run, [*COMPOSE, "stop", "nats2"], check=True)
    await asyncio.sleep(3)
    false_ack = False
    try:
        await js.publish("probe", b"no-quorum")
        false_ack = True
    except (nats.errors.TimeoutError, nats.js.errors.APIError):
        pass
    finally:
        await asyncio.to_thread(subprocess.run, [*COMPOSE, "start", "nats2", "nats3"], check=True)
        await nc.close()
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "replicas": 3,
        "healthy_publish_seq": first.seq,
        "single_node_loss_publish_seq": second.seq,
        "quorum_loss_false_ack": false_ack,
        "status": "FAIL" if false_ack else "PASS",
        "scope": "Three containers on one host; durable stream quorum only; SQL intake remains independent",
    }
    Path("docs/evidence/jetstream-cluster.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    raise SystemExit(false_ack)


if __name__ == "__main__":
    asyncio.run(main())
