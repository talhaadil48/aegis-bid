from uuid import uuid4

from aegis.db import connection
from tests.test_api import client_for


def test_chaos_is_gated(auction, monkeypatch):
    aid, _bidder = auction
    uid = uuid4()
    with connection() as c:
        c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (uid, str(uid), "unused", "admin"))
    client = client_for(uid)
    assert client.post("/v1/admin/chaos/scenarios", json={"scenario": "kill-worker"}).status_code == 403
    monkeypatch.setenv("ENABLE_CHAOS", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    assert client.post("/v1/admin/chaos/scenarios", json={"scenario": "arbitrary-shell"}).status_code == 422
    assert client.post("/v1/admin/chaos/scenarios", json={"scenario": "pause-queue-consumer"}).status_code == 202
    assert client.post("/v1/admin/chaos/scenarios", json={"scenario": "resume-queue-consumer"}).status_code == 202
    assert client.get("/v1/audit/auctions/" + str(aid)).status_code == 200
    assert client.get("/metrics").status_code == 200
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.post("/v1/admin/chaos/scenarios", json={"scenario": "kill-worker"}).status_code == 403
