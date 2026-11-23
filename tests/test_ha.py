import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aegis.api import app
from aegis.db import connection
from aegis.pipeline import connect
from scripts.render_ha import render

IMAGE = "registry.example/aegis@sha256:" + "a" * 64


def test_production_ha_boundaries():
    objects = render(IMAGE, IMAGE, IMAGE, "https://auction.example")["items"]
    deployments = [o for o in objects if o["kind"] == "Deployment"]
    assert {o["metadata"]["name"] for o in deployments} == {"api", "worker", "relay", "gateway", "web"}
    for deployment in deployments:
        pod = deployment["spec"]["template"]["spec"]
        assert pod["topologySpreadConstraints"][0]["minDomains"] == 2
        assert not pod["automountServiceAccountToken"]
        for container in pod["containers"]:
            assert not container["securityContext"]["allowPrivilegeEscalation"]
            assert "AWS_SECRET_ACCESS_KEY" not in str(container)
            assert "BACKUP_ENCRYPTION_KEY" not in str(container)
    ingress = next(o for o in objects if o["kind"] == "Ingress")
    assert ingress["spec"]["tls"][0]["hosts"] == ["auction.example"]
    assert any(o["kind"] == "NetworkPolicy" and o["metadata"]["name"] == "default-deny" for o in objects)
    for bad in ["http://auction.example", "https://auction.example/path"]:
        with pytest.raises(ValueError):
            render(IMAGE, IMAGE, IMAGE, bad)
    with pytest.raises(ValueError):
        render("aegis:latest", IMAGE, IMAGE, "https://auction.example")


def test_public_origin_behind_tls_proxy(monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://auction.example")
    client = TestClient(app)
    assert client.get("/livez").status_code == 200
    assert client.post("/v1/auth/logout", json={}, headers={"Origin": "https://auction.example"}).status_code == 200
    assert client.post("/v1/auth/logout", json={}, headers={"Origin": "http://testserver"}).status_code == 403


def test_production_nats_refuses_unverified_transport(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("NATS_CA_FILE", raising=False)
    with pytest.raises(RuntimeError, match="verified TLS"):
        asyncio.run(connect())


def test_pooled_transaction_rollback(auction):
    marker = str(uuid4())
    with pytest.raises(ValueError, match="rollback"), connection() as c:
        c.execute("INSERT INTO incidents(scenario,state) VALUES(%s,%s)", (marker, "TEST"))
        raise ValueError("rollback")
    with connection() as c:
        assert c.execute("SELECT 1 FROM incidents WHERE scenario=%s", (marker,)).fetchone() is None
