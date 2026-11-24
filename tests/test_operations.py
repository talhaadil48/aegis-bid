from uuid import uuid4

from fastapi.testclient import TestClient

from aegis.api import app
from aegis.db import connection
from aegis.engine import process
from tests.test_api import client_for


def test_seller_studio_lists_owned_auctions_and_protects_activity(auction):
    aid, bidder_id = auction
    other_id = uuid4()
    with connection() as c:
        owner = c.execute("SELECT seller_id FROM auctions WHERE id=%s", (aid,)).fetchone()["seller_id"]
        c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (other_id, str(other_id), "unused", "seller"))
    seller = client_for(owner)
    other = client_for(other_id)
    bidder = client_for(bidder_id)

    listing = "/v1/seller/auctions"
    activity = f"{listing}/{aid}/activity"
    audit = f"/v1/audit/auctions/{aid}"
    assert [row["id"] for row in seller.get(listing).json()] == [str(aid)]
    assert other.get(listing).json() == []
    assert other.get(f"/v1/auctions/{aid}").status_code == 200
    assert other.get(activity).status_code == other.get(audit).status_code == 404
    assert bidder.get(activity).status_code == bidder.get(audit).status_code == 403
    assert TestClient(app).get(activity).status_code == 401

    requests = [str(uuid4()) for _ in range(7)]
    for rid in requests:
        response = bidder.post(f"/v1/auctions/{aid}/bids", json={"request_id": rid, "amount_cents": 100})
        assert response.status_code == 202
    for _ in requests:
        process(aid, "seller-studio-test-worker")
    detail = seller.get(activity).json()
    assert detail["counts"] == {"bidders": 1, "total": 7, "accepted": 1, "rejected": 6, "queued": 0, "closed": 0}
    assert [row["request_id"] for row in detail["recent"]] == requests[:1:-1]
    assert all(row["state"] == "REJECTED" and row["reason"] for row in detail["recent"])
    assert all("bidder_id" not in row and "username" not in row for row in detail["recent"])
    evidence = seller.get(audit).json()
    assert evidence["auction"]["id"] == str(aid)
    assert len(evidence["events"]) == 7
    assert str(bidder_id) not in str(evidence)


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
