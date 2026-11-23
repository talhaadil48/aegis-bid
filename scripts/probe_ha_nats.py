"""Verify actual authenticated TLS and replicated JetStream in the disposable HA lab."""

import argparse
import asyncio
import base64
import json
import os
import ssl
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import nats
from nats.js.api import StreamConfig


def main(kubectl, kubeconfig):
    args = [kubectl, "--kubeconfig", kubeconfig, "--context", "kind-aegis-ha-lab", "-n", "aegis"]

    def secret(name):
        data = json.loads(subprocess.check_output([*args, "get", "secret", name, "-o", "json"], text=True))["data"]
        return {k: base64.b64decode(v).decode() for k, v in data.items()}

    uri = urlsplit(secret("aegis-runtime")["nats-url"])
    ca = Path(".tools/ha-nats-ca.crt")
    ca.write_text(secret("aegis-nats-tls")["ca.crt"])
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    forward = subprocess.Popen(
        [*args, "port-forward", "service/nats", "18082:4222"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    try:
        time.sleep(2)

        async def probe():
            client = await nats.connect(
                "tls://127.0.0.1:18082",
                user=uri.username,
                password=uri.password,
                tls=ssl.create_default_context(cafile=str(ca)),
                tls_hostname="nats.aegis.svc",
                max_reconnect_attempts=2,
            )
            try:
                stream = "TLS_PROBE_" + uuid4().hex[:8]
                js = client.jetstream()
                await js.add_stream(config=StreamConfig(name=stream, subjects=[stream], storage="file", num_replicas=3))
                ack = await js.publish(stream, b"authenticated-replicated-proof")
                info = await js.stream_info(stream)
                report = {
                    "status": "PASS" if ack.seq == 1 and info.config.num_replicas == 3 else "FAIL",
                    "tls_certificate_verified": True,
                    "credentials_authenticated": True,
                    "stream_replicas": info.config.num_replicas,
                    "committed_stream_sequence": ack.seq,
                    "scope": "Actual private Kubernetes NATS TLS and replicated persistence; three lab nodes on one host",
                }
                Path("docs/evidence/ha-nats-tls.json").write_text(json.dumps(report, indent=2))
                print(json.dumps(report, indent=2))
                return report["status"] == "PASS"
            finally:
                await client.close()

        valid = asyncio.run(probe())
        raise SystemExit(not valid)
    finally:
        forward.terminate()
        forward.wait(timeout=10)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--kubectl", default=".tools/kubectl.exe" if os.name == "nt" else ".tools/kubectl")
    p.add_argument("--kubeconfig", default=".tools/ha-kubeconfig")
    args = p.parse_args()
    main(args.kubectl, args.kubeconfig)
