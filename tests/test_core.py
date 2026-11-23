from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from aegis.db import connection
from aegis.engine import Conflict, Fenced, admit, close, process
from aegis.rules import ZERO_HASH, evaluate, event_hash


def test_cutoff_and_rules():
    now = datetime.now(UTC)
    a = {
        "status": "OPEN",
        "opens_at": now - timedelta(seconds=10),
        "closes_at": now,
        "min_price_cents": 100,
        "increment_cents": 10,
    }
    r = {"admitted_at": now, "amount_cents": 100}
    assert evaluate(a, r, 0)[0] == "CLOSED"
    r["admitted_at"] -= timedelta(seconds=1)
    assert evaluate(a, r, 0)[0] == "ACCEPTED"
    assert evaluate(a, r, 100)[0] == "REJECTED"


def test_hash_tamper():
    assert event_hash(ZERO_HASH, {"x": 1}) != event_hash(ZERO_HASH, {"x": 2})


def test_duplicate_race(auction):
    aid, bidder = auction
    rid = uuid4()
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda _: admit(aid, bidder, rid, 100), range(20)))
    with pytest.raises(Conflict):
        admit(aid, bidder, rid, 110)
    assert process(aid, "worker")["status"] == "ACCEPTED"
    assert process(aid, "worker") is None
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM bid_decisions WHERE auction_id=%s", (aid,)).fetchone()["n"] == 1
        assert c.execute("SELECT count(*) n FROM outbox WHERE auction_id=%s", (aid,)).fetchone()["n"] == 1


def test_same_price_race(auction):
    aid, bidder = auction
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda _: admit(aid, bidder, uuid4(), 100), range(30)))
    for _ in range(30):
        process(aid, "worker")
    with connection() as c:
        rows = c.execute(
            "SELECT status,count(*) n FROM bid_decisions WHERE auction_id=%s GROUP BY status", (aid,)
        ).fetchall()
        assert {r["status"]: r["n"] for r in rows} == {"ACCEPTED": 1, "REJECTED": 29}


def test_fencing_and_close(auction):
    aid, bidder = auction
    admit(aid, bidder, uuid4(), 100)
    process(aid, "old")
    with pytest.raises(Fenced):
        process(aid, "new")
    with connection() as c:
        c.execute("UPDATE worker_leases SET lease_expires_at=now()-interval '1 second' WHERE auction_id=%s", (aid,))
    assert process(aid, "new") is None
    with pytest.raises(Fenced):
        process(aid, "old", expected_epoch=1)
    with connection() as c:
        c.execute("UPDATE auctions SET closes_at=now()-interval '1 second' WHERE id=%s", (aid,))
    assert close(aid, "new")
    assert close(aid, "new") is False


def test_distinct_winners_and_pending_cutoff(auction):
    aid, _bidder = auction
    for index in range(4):
        uid = uuid4()
        with connection() as c:
            c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (uid, str(uid), "unused", "bidder"))
        admit(aid, uid, uuid4(), 100 + index * 10)
    with connection() as c:
        c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
    assert close(aid, "worker") is False
    for _ in range(4):
        assert process(aid, "worker")["status"] == "ACCEPTED"
    assert close(aid, "worker")
    with connection() as c:
        rows = c.execute("SELECT * FROM winners WHERE auction_id=%s ORDER BY rank", (aid,)).fetchall()
        assert len(rows) == 3
        assert [r["final_amount_cents"] for r in rows] == [130, 120, 110]
