import argparse
import base64
import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main(destination):
    session = os.environ["SESSION_SECRET"]
    if len(session) < 32:
        raise ValueError("Strong SESSION_SECRET required")
    password, route_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    routes = {f"ROUTE_{i}": f"nats-route://routes:{route_password}@nats-{i}.nats.aegis.svc:6222" for i in range(3)}
    data = [
        (
            "aegis-runtime",
            {
                "session-secret": session,
                "nats-url": f"tls://aegis:{password}@nats.aegis.svc:4222",
                "admission-key": os.getenv("ADMISSION_SERVICE_KEY") or secrets.token_urlsafe(48),
            },
        ),
        (
            "aegis-nats-auth",
            {
                "NATS_USERNAME": "aegis",
                "NATS_PASSWORD": password,
                "ROUTE_USER": "routes",
                "ROUTE_PASSWORD": route_password,
                **routes,
            },
        ),
        ("aegis-audit-key", {"audit-private.pem": private}),
    ]
    result = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": name, "namespace": "aegis"},
                "type": "Opaque",
                "data": {k: base64.b64encode(v.encode()).decode() for k, v in values.items()},
            }
            for name, values in data
        ],
    }
    path = Path(destination)
    with path.open("x") as stream:
        json.dump(result, stream)
    path.chmod(0o600)
    public = path.with_suffix(".public.pem")
    with public.open("xb") as stream:
        stream.write(
            key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        )
    print("Wrote private bootstrap secrets; preserve audit public key independently. Never commit this file.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    main(parser.parse_args().destination)
