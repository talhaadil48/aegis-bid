import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from fastapi.encoders import jsonable_encoder

from aegis.db import connection
from aegis.rules import ZERO_HASH, canonical


def pseudonym(uid):
    return hashlib.sha256(str(uid).encode()).hexdigest()


def export_auction(aid, *, seller_id=None):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        a = c.execute(
            """
            SELECT id,stock,min_price_cents,increment_cents,opens_at,closes_at,status,version
            FROM auctions WHERE id=%s AND (%s::uuid IS NULL OR seller_id=%s)
            """,
            (aid, seller_id, seller_id),
        ).fetchone()
        if not a:
            raise LookupError("Auction not found")
        events = c.execute(
            "SELECT event_seq,payload,prev_hash,event_hash FROM auction_events WHERE auction_id=%s ORDER BY event_seq",
            (aid,),
        ).fetchall()
        winners = c.execute(
            "SELECT bidder_id,rank,final_amount_cents FROM winners WHERE auction_id=%s ORDER BY rank", (aid,)
        ).fetchall()
    document = jsonable_encoder(
        {
            "schema_version": 1,
            "auction": a,
            "events": events,
            "winners": [
                {"bidder": pseudonym(w["bidder_id"]), "amount_cents": w["final_amount_cents"], "rank": w["rank"]}
                for w in winners
            ],
            "anchor": events[-1]["event_hash"] if events else ZERO_HASH,
        }
    )
    keypath = os.getenv("AUDIT_SIGNING_KEY")
    if keypath:
        key = serialization.load_pem_private_key(Path(keypath).read_bytes(), password=None)
        document["signature"] = base64.b64encode(key.sign(canonical(document))).decode()
    else:
        document["signature"] = None
    return document
