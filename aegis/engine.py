from datetime import timedelta

from psycopg.types.json import Jsonb

from aegis.db import connection
from aegis.evidence import pseudonym
from aegis.rules import ZERO_HASH, event_hash


class Conflict(ValueError):
    pass


class Fenced(RuntimeError):
    pass


def lock_intake(c, auction_id):
    """Admission and final-close share this lock; decision batches do not."""
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("aegis-intake:" + str(auction_id).lower(),))


def admit(auction_id, bidder_id, request_id, amount):
    from aegis.engine_batch import admit_many

    result = admit_many(auction_id, [(bidder_id, request_id, amount)])[0]
    if isinstance(result, Exception):
        raise result
    return result


def finalize_stranded():
    """Repair legacy late intake without changing a closed auction's audit anchor."""
    with connection() as c:
        rows = c.execute(
            "SELECT r.request_id FROM bid_requests r JOIN auctions a ON a.id=r.auction_id "
            "WHERE a.status='CLOSED' AND r.state='QUEUED' "
            "ORDER BY r.auction_id,r.intake_seq LIMIT 1000 FOR UPDATE OF r SKIP LOCKED"
        ).fetchall()
        ids = [r["request_id"] for r in rows]
        if ids:
            c.execute(
                "INSERT INTO admission_outcomes(request_id,status,reason) "
                "SELECT request_id,'CLOSED','Auction already finalized' FROM bid_requests "
                "WHERE request_id=ANY(%s) ON CONFLICT DO NOTHING",
                (ids,),
            )
            c.execute("UPDATE bid_requests SET state='CLOSED' WHERE request_id=ANY(%s)", (ids,))
        return len(ids)


def acquire(c, auction_id, holder):
    now = c.execute("SELECT clock_timestamp() t").fetchone()["t"]
    lease = c.execute("SELECT * FROM worker_leases WHERE auction_id=%s FOR UPDATE", (auction_id,)).fetchone()
    if lease and lease["holder_id"] != holder and lease["lease_expires_at"] > now:
        raise Fenced("Another worker owns the lease")
    epoch = (lease["epoch"] + (lease["holder_id"] != holder or lease["lease_expires_at"] <= now)) if lease else 1
    c.execute(
        "INSERT INTO worker_leases VALUES(%s,%s,%s,%s) ON CONFLICT(auction_id) DO UPDATE SET holder_id=excluded.holder_id,epoch=excluded.epoch,lease_expires_at=excluded.lease_expires_at",
        (auction_id, holder, epoch, now + timedelta(seconds=5)),
    )
    return epoch


def append_event(c, a, payload):
    prev = c.execute(
        "SELECT event_hash FROM auction_events WHERE auction_id=%s ORDER BY event_seq DESC LIMIT 1", (a["id"],)
    ).fetchone()
    previous = prev["event_hash"] if prev else ZERO_HASH
    digest = event_hash(previous, payload)
    c.execute(
        "INSERT INTO auction_events(auction_id,event_seq,payload,prev_hash,event_hash) VALUES(%s,%s,%s,%s,%s)",
        (a["id"], a["version"], Jsonb(payload), previous, digest),
    )
    c.execute(
        "INSERT INTO outbox(auction_id,event_type,body) VALUES(%s,%s,%s)",
        (
            a["id"],
            payload["type"],
            Jsonb({"auction_id": str(a["id"]), "version": a["version"], "type": payload["type"]}),
        ),
    )


def process(auction_id, holder, expected_epoch=None):
    from aegis.engine_batch import process_many

    rows = process_many(auction_id, holder, limit=1, expected_epoch=expected_epoch)
    return rows[0] if rows else None


def close(auction_id, holder):
    with connection() as c:
        lock_intake(c, auction_id)
        a = c.execute("SELECT * FROM auctions WHERE id=%s FOR UPDATE", (auction_id,)).fetchone()
        if not a or a["status"] == "CLOSED":
            return False
        acquire(c, auction_id, holder)
        if c.execute("SELECT clock_timestamp() >= %s due", (a["closes_at"],)).fetchone()["due"] is False:
            return False
        if c.execute(
            "SELECT 1 FROM bid_requests WHERE auction_id=%s AND state='QUEUED' LIMIT 1", (auction_id,)
        ).fetchone():
            return False
        offers = c.execute(
            "SELECT * FROM bidder_offers WHERE auction_id=%s ORDER BY current_amount_cents DESC,decision_seq ASC LIMIT %s",
            (auction_id, a["stock"]),
        ).fetchall()
        for rank, offer in enumerate(offers, 1):
            c.execute(
                "INSERT INTO winners VALUES(%s,%s,%s,%s)",
                (auction_id, offer["bidder_id"], rank, offer["current_amount_cents"]),
            )
        a["version"] += 1
        c.execute(
            "UPDATE auctions SET status='CLOSED',version=%s,intake_seq=greatest(intake_seq,coalesce((SELECT max(intake_seq) FROM bid_requests WHERE auction_id=%s),0)) WHERE id=%s",
            (a["version"], auction_id, auction_id),
        )
        append_event(
            c,
            a,
            {
                "type": "auction.closed",
                "decision_seq": a["version"],
                "winners": [
                    {"bidder": pseudonym(o["bidder_id"]), "amount_cents": o["current_amount_cents"]} for o in offers
                ],
            },
        )
        return True
