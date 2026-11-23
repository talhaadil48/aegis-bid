from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from aegis.db import connection
from aegis.engine import Conflict, admit, close, finalize_stranded, process
from aegis.evidence import export_auction
from aegis.verifier import verify
from tests.test_api import client_for


def finish(aid):
    with connection() as c:
        c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
    assert close(aid, "test-worker")


def test_late_retries_have_final_history_and_preserve_closed_ledger(auction):
    aid, bidder = auction
    original = uuid4()
    admit(aid, bidder, original, 100)
    process(aid, "test-worker")
    finish(aid)
    before = export_auction(aid)
    rid = uuid4()
    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(lambda _: admit(aid, bidder, rid, 200)["state"], range(16)))
    assert states == ["CLOSED"] * 16
    assert admit(aid, bidder, original, 100)["state"] == "ACCEPTED"
    with pytest.raises(Conflict):
        admit(aid, bidder, rid, 201)
    client = client_for(bidder)
    response = client.post(f"/v1/auctions/{aid}/bids", json={"request_id": str(rid), "amount_cents": 200})
    assert response.status_code == 200
    assert response.json()["state"] == "CLOSED"
    result = client.get(f"/v1/bid-requests/{rid}").json()
    assert result["decision"]["status"] == "CLOSED"
    assert result["decision"]["reason"] == "Auction deadline passed"
    assert next(r for r in client.get("/v1/me/bids").json() if r["request_id"] == str(rid))["reason"]
    after = export_auction(aid)
    assert after == before
    assert verify(after)["errors"] == []
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM admission_outcomes WHERE request_id=%s", (rid,)).fetchone()["n"] == 1


def test_deadline_passed_before_worker_closes_is_terminal(auction):
    aid, bidder = auction
    with connection() as c:
        c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
    assert admit(aid, bidder, uuid4(), 100)["state"] == "CLOSED"
    assert process(aid, "test-worker") is None
    assert close(aid, "test-worker")


def test_reconcile_repairs_legacy_queued_requests_without_mutating_winners(auction):
    aid, bidder = auction
    finish(aid)
    before = export_auction(aid)
    rid = uuid4()
    with connection() as c:
        c.execute("UPDATE auctions SET intake_seq=intake_seq+1 WHERE id=%s", (aid,))
        c.execute(
            "INSERT INTO bid_requests(request_id,auction_id,bidder_id,amount_cents,intake_seq) VALUES(%s,%s,%s,100,1)",
            (rid, aid, bidder),
        )
    assert finalize_stranded() == 1
    assert finalize_stranded() == 0
    with connection() as c:
        assert c.execute("SELECT state FROM bid_requests WHERE request_id=%s", (rid,)).fetchone()["state"] == "CLOSED"
    assert export_auction(aid) == before
