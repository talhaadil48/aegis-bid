from datetime import timedelta

from psycopg.types.json import Jsonb

from aegis.db import connection
from aegis.rules import ZERO_HASH, evaluate, event_hash


class Conflict(ValueError):
    pass


class Fenced(RuntimeError):
    pass


def admit(auction_id, bidder_id, request_id, amount):
    with connection() as c:
        a = c.execute("SELECT * FROM auctions WHERE id=%s FOR UPDATE", (auction_id,)).fetchone()
        if not a:
            raise LookupError("Auction not found")
        old = c.execute("SELECT * FROM bid_requests WHERE request_id=%s", (request_id,)).fetchone()
        if old:
            if (str(old["auction_id"]), str(old["bidder_id"]), old["amount_cents"]) != (
                str(auction_id),
                str(bidder_id),
                amount,
            ):
                raise Conflict("Request ID already used for another payload")
            return old
        pending = c.execute(
            "SELECT count(*) n FROM bid_requests WHERE auction_id=%s AND state='QUEUED'", (auction_id,)
        ).fetchone()["n"]
        if pending >= 10000:
            raise OverflowError("Auction queue capacity reached")
        seq = c.execute(
            "UPDATE auctions SET intake_seq=intake_seq+1 WHERE id=%s RETURNING intake_seq", (auction_id,)
        ).fetchone()["intake_seq"]
        return c.execute(
            "INSERT INTO bid_requests(request_id,auction_id,bidder_id,amount_cents,intake_seq) VALUES(%s,%s,%s,%s,%s) RETURNING *",
            (request_id, auction_id, bidder_id, amount, seq),
        ).fetchone()


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
    with connection() as c:
        a = c.execute("SELECT * FROM auctions WHERE id=%s FOR UPDATE", (auction_id,)).fetchone()
        if not a:
            return None
        epoch = acquire(c, auction_id, holder)
        if expected_epoch is not None and epoch != expected_epoch:
            raise Fenced("Stale fencing epoch")
        r = c.execute(
            "SELECT * FROM bid_requests WHERE auction_id=%s AND state='QUEUED' ORDER BY intake_seq LIMIT 1 FOR UPDATE",
            (auction_id,),
        ).fetchone()
        if not r:
            return None
        high = c.execute(
            "SELECT coalesce(max(current_amount_cents),0) high FROM bidder_offers WHERE auction_id=%s", (auction_id,)
        ).fetchone()["high"]
        status, reason = evaluate(a, r, high)
        a["version"] += 1
        c.execute("UPDATE auctions SET version=%s WHERE id=%s", (a["version"], auction_id))
        decision = c.execute(
            "INSERT INTO bid_decisions(request_id,auction_id,bidder_id,status,reason,effective_amount_cents,decision_seq,epoch) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (r["request_id"], auction_id, r["bidder_id"], status, reason, r["amount_cents"], a["version"], epoch),
        ).fetchone()
        if status == "ACCEPTED":
            c.execute(
                "INSERT INTO bidder_offers VALUES(%s,%s,%s,%s) ON CONFLICT(auction_id,bidder_id) DO UPDATE SET current_amount_cents=excluded.current_amount_cents,decision_seq=excluded.decision_seq",
                (auction_id, r["bidder_id"], r["amount_cents"], a["version"]),
            )
        c.execute("UPDATE bid_requests SET state=%s WHERE request_id=%s", (status, r["request_id"]))
        append_event(
            c,
            a,
            {
                "type": "bid.decision",
                "request_id": str(r["request_id"]),
                "bidder": str(r["bidder_id"]),
                "amount_cents": r["amount_cents"],
                "admitted_at": r["admitted_at"].isoformat(),
                "status": status,
                "reason": reason,
                "decision_seq": a["version"],
                "intake_seq": r["intake_seq"],
            },
        )
        return decision


def close(auction_id, holder):
    with connection() as c:
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
        c.execute("UPDATE auctions SET status='CLOSED',version=%s WHERE id=%s", (a["version"], auction_id))
        append_event(
            c,
            a,
            {
                "type": "auction.closed",
                "decision_seq": a["version"],
                "winners": [{"bidder": str(o["bidder_id"]), "amount_cents": o["current_amount_cents"]} for o in offers],
            },
        )
        return True
