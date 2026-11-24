"""Bounded group commits; every request retains its own ordered durable decision."""

import os
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from aegis.db import connection
from aegis.engine import Conflict, Fenced, acquire, lock_intake
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
    """entries=(bidder UUID, request UUID, cents); return rows or per-item errors."""
    if not entries:
        return []
    if len(entries) > 1024:
        raise ValueError("Admission batch exceeds 1024")
    aid = UUID(str(auction_id))
    entries = [(UUID(str(uid)), UUID(str(rid)), amount) for uid, rid, amount in entries]
    with connection() as c:
        # Global UUID conflicts are serialized even when different auctions race.
        c.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(rid::text,0)) "
            "FROM (SELECT DISTINCT unnest(%s::uuid[]) rid ORDER BY rid) ordered",
            ([r for _, r, _ in entries],),
        )
        lock_intake(c, aid)
        a = c.execute("SELECT * FROM auctions WHERE id=%s", (aid,)).fetchone()
        if not a:
            return [LookupError("Auction not found") for _ in entries]
        now = c.execute("SELECT clock_timestamp() t").fetchone()["t"]
        expired = a["status"] == "CLOSED" or now >= a["closes_at"]
        previous = c.execute(
            "SELECT * FROM bid_requests WHERE request_id=ANY(%s)", ([r for _, r, _ in entries],)
        ).fetchall()
        known = {r["request_id"]: r for r in previous}
        capacity = int(os.getenv("MAX_PENDING_BIDS", "60000"))
        pending = (
            0
            if expired
            else c.execute(
                "SELECT count(*) n FROM bid_requests WHERE auction_id=%s AND state='QUEUED'", (aid,)
            ).fetchone()["n"]
        )
        fresh = {}
        results = []
        for uid, rid, amount in entries:
            old = known.get(rid) or fresh.get(rid)
            if old:
                if (old["auction_id"], old["bidder_id"], old["amount_cents"]) != (aid, uid, amount):
                    results.append(Conflict("Request ID already used for another payload"))
                else:
                    results.append(rid)
            elif not expired and pending + len(fresh) >= capacity:
                results.append(OverflowError("Auction queue capacity reached"))
            else:
                fresh[rid] = {"auction_id": aid, "bidder_id": uid, "amount_cents": amount}
                results.append(rid)
        if fresh:
            last = c.execute(
                "SELECT intake_seq FROM bid_requests WHERE auction_id=%s ORDER BY intake_seq DESC LIMIT 1", (aid,)
            ).fetchone()
            first = max(a["intake_seq"], last["intake_seq"] if last else 0) + 1
            rows = [
                (rid, aid, r["bidder_id"], r["amount_cents"], first + i, now, "CLOSED" if expired else "QUEUED")
                for i, (rid, r) in enumerate(fresh.items())
            ]
            fields = [
                ("request_id", "uuid"),
                ("auction_id", "uuid"),
                ("bidder_id", "uuid"),
                ("amount_cents", "bigint"),
                ("intake_seq", "bigint"),
                ("admitted_at", "timestamptz"),
                ("state", "text"),
            ]
            known.update(
                {r["request_id"]: r for r in insert_rows(c, "bid_requests", fields, rows, "RETURNING *").fetchall()}
            )
            if expired:
                c.execute(
                    "INSERT INTO admission_outcomes(request_id,status,reason) SELECT request_id,'CLOSED','Auction deadline passed' FROM bid_requests WHERE request_id=ANY(%s)",
                    (list(fresh),),
                )
        return [r if isinstance(r, Exception) else known[r] for r in results]


def process_many(auction_id, holder, limit=512, expected_epoch=None):
    if not 1 <= limit <= 1024:
        raise ValueError("Decision batch must be between 1 and 1024")
    with connection() as c:
        # Retain one decision authority while allowing FK-safe journal inserts.
        a = c.execute("SELECT * FROM auctions WHERE id=%s FOR NO KEY UPDATE", (auction_id,)).fetchone()
        if not a:
            return []
        epoch = acquire(c, auction_id, holder)
        if expected_epoch is not None and epoch != expected_epoch:
            raise Fenced("Stale fencing epoch")
        if a["status"] == "CLOSED":
            return []
        requests = c.execute(
            "SELECT * FROM bid_requests WHERE auction_id=%s AND state='QUEUED' ORDER BY intake_seq LIMIT %s FOR UPDATE",
            (auction_id, limit),
        ).fetchall()
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
            notifications.append(
                (a["id"], "bid.decision", Jsonb({"auction_id": str(a["id"]), "version": seq, "type": "bid.decision"}))
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
        c.execute("UPDATE auctions SET version=%s WHERE id=%s", (a["version"], a["id"]))
        return result
