"""Bounded group commits; every request retains its own ordered durable decision."""

import os
from uuid import UUID

from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from aegis.db import connection
from aegis.engine import Conflict, Fenced, acquire
from aegis.evidence import pseudonym
from aegis.rules import ZERO_HASH, evaluate, event_hash


def insert_rows(c, table, fields, rows, suffix=""):
    """Internal, typed array inserts; identifiers and types come only from code."""
    columns = sql.SQL(",").join(sql.Identifier(name) for name, _ in fields)
    casts = sql.SQL(",").join(sql.SQL("%s::{}[]").format(sql.SQL(kind)) for _, kind in fields)
    query = sql.SQL("INSERT INTO {} ({}) SELECT * FROM unnest({}) {}").format(
        sql.Identifier(table), columns, casts, sql.SQL(suffix)
    )
    arrays = [[row[index] for row in rows] for index in range(len(fields))]
    return c.execute(query, arrays)


def admit_many(auction_id, entries):
    """Every result follows one atomic SQL admission; authorization remains in the API."""
    if not entries:
        return []
    if len(entries) > 1024:
        raise ValueError("Admission batch exceeds 1024")
    errors = {
        "NO_AUCTION": (LookupError, "Auction not found"),
        "CAPACITY": (OverflowError, "Auction queue capacity reached"),
        "CONFLICT": (Conflict, "Request ID already used for another payload"),
    }
    with connection() as c:
        rows = c.execute(
            "SELECT * FROM aegis_admit_batch(%s,%s::uuid[],%s::uuid[],%s::bigint[],%s)",
            (
                UUID(str(auction_id)),
                [UUID(str(rid)) for _, rid, _ in entries],
                [UUID(str(uid)) for uid, _, _ in entries],
                [amount for _, _, amount in entries],
                int(os.getenv("MAX_PENDING_BIDS", "60000")),
            ),
        ).fetchall()
        result = []
        for row in rows:
            error = row.pop("error_code")
            result.append(errors[error][0](errors[error][1]) if error else row)
        return result


def decision_prefix(c, auction_id, holder, limit, expected_epoch):
    key = "aegis-intake:" + str(auction_id).lower()
    c.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))
    try:
        a = c.execute("SELECT * FROM auctions WHERE id=%s FOR NO KEY UPDATE SKIP LOCKED", (auction_id,)).fetchone()
        if not a:
            return None
        epoch = acquire(c, auction_id, holder)
        if expected_epoch is not None and epoch != expected_epoch:
            raise Fenced("Stale fencing epoch")
        rows = (
            c.execute(
                "SELECT * FROM bid_requests WHERE auction_id=%s AND state='QUEUED' ORDER BY intake_seq LIMIT %s FOR UPDATE",
                (auction_id, limit),
            ).fetchall()
            if a["status"] != "CLOSED"
            else []
        )
        return a, epoch, rows
    finally:
        if not c.closed:
            if c.info.transaction_status == TransactionStatus.INERROR:
                c.rollback()
            c.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))


def process_many(auction_id, holder, limit=512, expected_epoch=None):
    if not 1 <= limit <= 1024:
        raise ValueError("Decision batch must be between 1 and 1024")
    with connection() as c:
        prefix = decision_prefix(c, auction_id, holder, limit, expected_epoch)
        if prefix is None:
            return []
        a, epoch, requests = prefix
        if not requests:
            return []
        high = c.execute(
            "SELECT coalesce(max(current_amount_cents),0) high FROM bidder_offers WHERE auction_id=%s", (auction_id,)
        ).fetchone()["high"]
        anchor = c.execute(
            "SELECT event_hash FROM auction_events WHERE auction_id=%s ORDER BY event_seq DESC LIMIT 1", (auction_id,)
        ).fetchone()
        previous = anchor["event_hash"] if anchor else ZERO_HASH
        decisions, events, notifications = [], [], []
        offers = {}
        for r in requests:
            status, reason = evaluate(a, r, high)
            a["version"] += 1
            seq = a["version"]
            decisions.append((r["request_id"], a["id"], r["bidder_id"], status, reason, r["amount_cents"], seq, epoch))
            if status == "ACCEPTED":
                high = r["amount_cents"]
                offers[r["bidder_id"]] = (a["id"], r["bidder_id"], high, seq)
            payload = {
                "type": "bid.decision",
                "request_id": str(r["request_id"]),
                "bidder": pseudonym(r["bidder_id"]),
                "amount_cents": r["amount_cents"],
                "admitted_at": r["admitted_at"].isoformat(),
                "status": status,
                "reason": reason,
                "decision_seq": seq,
                "intake_seq": r["intake_seq"],
            }
            digest = event_hash(previous, payload)
            events.append((a["id"], seq, Jsonb(payload), previous, digest))
            previous = digest
        # All decisions become visible together; one notification names that
        # committed version while the full per-bid event chain remains intact.
        notifications.append(
            (
                a["id"],
                "bid.decision",
                Jsonb({"auction_id": str(a["id"]), "version": a["version"], "type": "bid.decision"}),
            )
        )
        fields = [
            ("request_id", "uuid"),
            ("auction_id", "uuid"),
            ("bidder_id", "uuid"),
            ("status", "text"),
            ("reason", "text"),
            ("effective_amount_cents", "bigint"),
            ("decision_seq", "bigint"),
            ("epoch", "bigint"),
        ]
        result = insert_rows(c, "bid_decisions", fields, decisions, "RETURNING *").fetchall()
        if offers:
            insert_rows(
                c,
                "bidder_offers",
                [
                    ("auction_id", "uuid"),
                    ("bidder_id", "uuid"),
                    ("current_amount_cents", "bigint"),
                    ("decision_seq", "bigint"),
                ],
                list(offers.values()),
                "ON CONFLICT(auction_id,bidder_id) DO UPDATE SET current_amount_cents=excluded.current_amount_cents,decision_seq=excluded.decision_seq",
            )
        c.execute(
            "UPDATE bid_requests r SET state=v.state FROM unnest(%s::uuid[],%s::text[]) v(id,state) WHERE r.request_id=v.id",
            ([d[0] for d in decisions], [d[3] for d in decisions]),
        )
        insert_rows(
            c,
            "auction_events",
            [
                ("auction_id", "uuid"),
                ("event_seq", "bigint"),
                ("payload", "jsonb"),
                ("prev_hash", "text"),
                ("event_hash", "text"),
            ],
            events,
        )
        insert_rows(c, "outbox", [("auction_id", "uuid"), ("event_type", "text"), ("body", "jsonb")], notifications)
        c.execute(
            "UPDATE auctions SET version=%s,processed_intake_seq=%s WHERE id=%s",
            (a["version"], requests[-1]["intake_seq"], a["id"]),
        )
        return result
