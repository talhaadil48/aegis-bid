from uuid import uuid4

from fastapi.testclient import TestClient

from aegis.api import app
from aegis.auth import token
from aegis.db import connection
from aegis.engine_batch import process_many


def test_private_batch_keeps_per_user_auth_and_uuid_conflicts(auction, monkeypatch):
    aid, bidder = auction
    key = "service-key-with-at-least-thirty-two-characters"
    monkeypatch.setenv("ADMISSION_SERVICE_KEY", key)
    client = TestClient(app)
    assert client.post("/internal/v1/admissions", content=b"not json").status_code == 403
    with connection() as c:
        seller = c.execute("SELECT seller_id FROM auctions WHERE id=%s", (aid,)).fetchone()["seller_id"]
    rid = str(uuid4())
    good = {"request_id": rid, "amount_cents": 100, "session_cookie": token({"id": bidder})}
    requests = [
        good,
        {**good, "session_cookie": "forged"},
        {**good, "session_cookie": token({"id": seller})},
        {**good, "amount_cents": 110},
    ]
    result = client.post(
        "/internal/v1/admissions", json={"auction_id": str(aid), "requests": requests}, headers={"X-Admission-Key": key}
    )
    assert result.status_code == 200
    assert [r["http_status"] for r in result.json()["results"]] == [202, 401, 403, 409]
    assert process_many(aid, "worker")[0]["status"] == "ACCEPTED"
    result = client.post(
        "/internal/v1/admissions", json={"auction_id": str(aid), "requests": [good]}, headers={"X-Admission-Key": key}
    )
    assert result.json()["results"][0]["http_status"] == 200
    spoof = {**good, "bidder_id": str(seller)}
    assert (
        client.post(
            "/internal/v1/admissions",
            json={"auction_id": str(aid), "requests": [spoof]},
            headers={"X-Admission-Key": key},
        ).status_code
        == 422
    )
