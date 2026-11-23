from uuid import uuid4

from fastapi.testclient import TestClient

from aegis import config
from aegis.api import app
from aegis.auth import check_password, hash_password, token
from aegis.db import connection
from aegis.engine import process


def client_for(uid):
    config.SECRET = "test-secret-with-at-least-thirty-two-characters"
    client = TestClient(app)
    client.cookies.set("aegis_session", token({"id": uid}))
    return client


def test_password():
    encoded = hash_password("correct-password")
    assert check_password("correct-password", encoded)
    assert not check_password("wrong", encoded)


def test_bid_authorization_and_lifecycle(auction):
    aid, bidder = auction
    anon = TestClient(app)
    assert anon.get("/v1/auctions").status_code == 401
    client = client_for(bidder)
    assert client.get("/v1/admin/metrics").status_code == 403
    rid = str(uuid4())
    path = f"/v1/auctions/{aid}/bids"
    assert (
        client.post(path, json={"request_id": rid, "amount_cents": 100, "bidder_id": str(uuid4())}).status_code == 422
    )
    assert client.post(path, json={"request_id": rid, "amount_cents": 100.5}).status_code == 422
    assert client.post(path, json={"request_id": rid, "amount_cents": 100}).json()["state"] == "QUEUED"
    process(aid, "test-worker")
    assert client.get("/v1/bid-requests/" + rid).json()["decision"]["status"] == "ACCEPTED"
    assert client.post(path, json={"request_id": rid, "amount_cents": 101}).status_code == 409
    assert (
        client.post(
            path, json={"request_id": str(uuid4()), "amount_cents": 110}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    with connection() as c:
        other = uuid4()
        c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (other, str(other), "unused", "bidder"))
    assert client_for(other).get("/v1/bid-requests/" + rid).status_code == 404
    with client.websocket_connect(f"/v1/live/auctions/{aid}") as ws:
        data = ws.receive_json()
        assert data["version"] == 1
        assert "bidder_id" not in data
