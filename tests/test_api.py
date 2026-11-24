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


def test_security_headers_on_success_and_origin_refusal():
    client = TestClient(app)
    response = client.get("/livez")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    refused = client.post("/v1/auth/logout", headers={"Origin": "https://evil.test"})
    assert refused.status_code == 403
    assert refused.headers["Cache-Control"] == "no-store"


def test_registration_creates_a_bidder_and_starts_a_session(auction):
    client = TestClient(app)
    username = "buyer-" + uuid4().hex[:16]
    credentials = {"username": username, "password": "registration-test-password"}
    path = "/v1/auth/register"
    invalid = client.post(path, json={**credentials, "role": "admin"})
    assert invalid.status_code == 422
    assert credentials["password"] not in invalid.text
    assert client.get("/v1/auth/me").status_code == 401

    created = client.post(path, json=credentials)
    assert created.status_code == 201
    account = created.json()
    assert set(account) == {"id", "username", "role"}
    assert account["username"] == username
    assert account["role"] == "bidder"
    assert "HttpOnly" in created.headers["set-cookie"]
    assert client.get("/v1/auth/me").json() == account
    assert client.get("/v1/auctions").status_code == 200
    assert client.get("/v1/admin/metrics").status_code == 403

    assert client.post("/v1/auth/logout").status_code == 200
    assert client.get("/v1/auth/me").status_code == 401
    assert client.post(path, json={**credentials, "password": "different-long-password"}).status_code == 409
    assert client.get("/v1/auth/me").status_code == 401
    assert client.post("/v1/auth/login", json=credentials).json() == account


def test_public_seller_registration(auction):
    client = TestClient(app)
    credentials = {"username": "seller-" + uuid4().hex[:16], "password": "registration-test-password"}
    assert client.post("/v1/auth/register", json={**credentials, "role": "auditor"}).status_code == 422
    registered = client.post("/v1/auth/register", json={**credentials, "role": "seller"})
    assert registered.status_code == 201
    assert client.get("/v1/auth/me").json()["role"] == "seller"
    assert client.post("/v1/admin/users", json={**credentials, "role": "admin"}).status_code == 403


def test_first_admin_setup_and_account_provisioning(auction, monkeypatch):
    client = TestClient(app)
    setup_key = "first-admin-test-key-with-at-least-32-characters"
    credentials = {"username": "admin-" + uuid4().hex[:16], "password": "registration-test-password"}
    assert client.post("/v1/admin/users", json={**credentials, "role": "admin"}).status_code == 401
    monkeypatch.delenv("ADMIN_SETUP_KEY", raising=False)
    assert client.get("/v1/auth/setup").json() == {"available": False}
    monkeypatch.setenv("ADMIN_SETUP_KEY", setup_key)
    assert client.get("/v1/auth/setup").json() == {"available": True}
    assert client.post("/v1/auth/setup", json={**credentials, "setup_key": "wrong"}).status_code == 403
    created = client.post("/v1/auth/setup", json={**credentials, "setup_key": setup_key})
    assert created.status_code == 201
    assert created.json()["role"] == "admin"
    assert client.get("/v1/auth/setup").json() == {"available": False}
    duplicate = client.post("/v1/auth/setup", json={**credentials, "setup_key": setup_key})
    assert duplicate.status_code == 409
    auditor = {"username": "auditor-" + uuid4().hex[:16], "password": "registration-test-password"}
    managed = client.post("/v1/admin/users", json={**auditor, "role": "auditor"})
    assert managed.status_code == 201
    assert "set-cookie" not in managed.headers
    assert client.get("/v1/auth/me").json() == created.json()
    assert TestClient(app).post("/v1/auth/login", json=auditor).json() == managed.json()


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
