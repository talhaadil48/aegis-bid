import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from aegis.coalescing import grouped
from aegis.db import connection
from aegis.engine import Conflict, Fenced, close
from aegis.engine_batch import admit_many, process_many
from aegis.evidence import export_auction
from aegis.verifier import verify


def test_group_commit_order_prices_duplicates_and_signed_replay(auction):
    aid, bidder = auction
    ids = [uuid4() for _ in range(5)]
    entries = [(bidder, rid, amount) for rid, amount in zip(ids, [100, 100, 130, 120, 140], strict=True)]
    rows = admit_many(aid, entries + [entries[0], (bidder, ids[0], 101)])
    assert [r["intake_seq"] for r in rows[:5]] == [1, 2, 3, 4, 5]
    assert rows[5]["request_id"] == ids[0]
    assert isinstance(rows[6], Conflict)
    decisions = process_many(aid, "worker", limit=3)
    assert [r["status"] for r in decisions] == ["ACCEPTED", "REJECTED", "ACCEPTED"]
    with pytest.raises(Fenced):
        process_many(aid, "other")
    assert [r["status"] for r in process_many(aid, "worker")] == ["REJECTED", "ACCEPTED"]
    assert process_many(aid, "worker") == []
    with connection() as c:
        c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
    assert close(aid, "worker")
    assert verify(export_auction(aid))["errors"] == []


def test_capacity_is_per_new_uuid_and_late_admission_is_final(auction, monkeypatch):
    aid, bidder = auction
    monkeypatch.setenv("MAX_PENDING_BIDS", "2")
    first, second, third = [(bidder, uuid4(), 100 + i * 10) for i in range(3)]
    rows = admit_many(aid, [first, first, second, third])
    assert rows[0] == rows[1]
    assert rows[2]["intake_seq"] == 2
    assert isinstance(rows[3], OverflowError)
    with connection() as c:
        c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
    assert admit_many(aid, [third])[0]["state"] == "CLOSED"


def test_uuid_conflict_across_auctions_is_not_a_database_error(auction):
    aid, bidder = auction
    other = uuid4()
    with connection() as c:
        c.execute(
            "INSERT INTO auctions(id,seller_id,title,stock,min_price_cents,increment_cents,opens_at,closes_at) SELECT %s,seller_id,'Other',stock,min_price_cents,increment_cents,opens_at,closes_at FROM auctions WHERE id=%s",
            (other, aid),
        )
    rid = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda target: admit_many(target, [(bidder, rid, 100)])[0], [aid, other]))
    assert sum(isinstance(r, Conflict) for r in results) == 1
    assert sum(isinstance(r, dict) for r in results) == 1


def test_batch_failure_rolls_back_every_decision_and_hash(auction):
    aid, bidder = auction
    admit_many(aid, [(bidder, uuid4(), 100), (bidder, uuid4(), 120)])
    with connection() as c:
        c.execute(
            "CREATE OR REPLACE FUNCTION fail_batch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.auction_id = '"
            + str(aid)
            + "'::uuid AND NEW.event_seq=2 THEN RAISE EXCEPTION 'injected batch failure'; END IF; RETURN NEW; END $$"
        )
        c.execute(
            "CREATE TRIGGER injected_batch_failure BEFORE INSERT ON auction_events FOR EACH ROW EXECUTE FUNCTION fail_batch()"
        )
    try:
        with pytest.raises(Exception, match="injected batch failure"):
            process_many(aid, "worker")
        with connection() as c:
            assert c.execute("SELECT count(*) n FROM bid_decisions WHERE auction_id=%s", (aid,)).fetchone()["n"] == 0
            assert c.execute("SELECT version FROM auctions WHERE id=%s", (aid,)).fetchone()["version"] == 0
            assert (
                c.execute(
                    "SELECT count(*) n FROM bid_requests WHERE auction_id=%s AND state='QUEUED'", (aid,)
                ).fetchone()["n"]
                == 2
            )
    finally:
        with connection() as c:
            c.execute("DROP TRIGGER injected_batch_failure ON auction_events")
            c.execute("DROP FUNCTION fail_batch()")
    assert len(process_many(aid, "worker")) == 2
    assert verify(export_auction(aid))["errors"] == []


def test_cancelled_http_waiter_does_not_cancel_group():
    async def scenario():
        seen = []

        def execute(_key, rows):
            seen.extend(rows)
            return [r * 2 for r in rows]

        first = asyncio.create_task(grouped("test", "cancel", 1, execute))
        second = asyncio.create_task(grouped("test", "cancel", 2, execute))
        await asyncio.sleep(0.001)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second == 4
        assert seen == [1, 2]

    asyncio.run(scenario())
