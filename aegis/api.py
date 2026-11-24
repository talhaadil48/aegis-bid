import asyncio
import os
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.responses import JSONResponse

from aegis import config
from aegis.auth import check_password, current_user, identity, roles, subject, token, users_many
from aegis.coalescing import grouped
from aegis.db import connection
from aegis.engine import Conflict, lock_intake
from aegis.engine_batch import admit_many
from aegis.security import SecurityHeaders

app = FastAPI(title="AegisBid Omega", version="1.0.0")
app.add_middleware(SecurityHeaders)
attempts = defaultdict(deque)
connections = defaultdict(int)
next_prune = 0.0


def limit(key, maximum, seconds=60):
    global next_prune
    now = time.monotonic()
    bucket = attempts[key]
    while bucket and bucket[0] < now - seconds:
        bucket.popleft()
    if len(bucket) >= maximum:
        raise HTTPException(429, "Rate limit reached", headers={"Retry-After": str(seconds)})
    bucket.append(now)
    if len(attempts) > 10000 and now >= next_prune:
        next_prune = now + 1
        for old in list(attempts):
            if not attempts[old] or attempts[old][-1] < now - seconds:
                del attempts[old]


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


@app.post("/v1/auth/login")
def login(body: Login, response: Response, request: Request):
    limit(("login", request.client.host), 10)
    with connection() as c:
        user = c.execute("SELECT * FROM users WHERE username=%s", (body.username,)).fetchone()
    if not user or not check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    response.set_cookie(
        "aegis_session",
        token(user),
        httponly=True,
        samesite="strict",
        secure=config.ENVIRONMENT == "production",
        max_age=14400,
    )
    return {k: user[k] for k in ("id", "username", "role")}


@app.post("/v1/auth/logout")
def logout(response: Response):
    response.delete_cookie("aegis_session")
    return {"ok": True}


@app.get("/v1/auth/me")
def me(user=Depends(current_user)):
    return user


def snapshot(aid):
    with connection() as c:
        a = c.execute("SELECT * FROM auctions WHERE id=%s", (aid,)).fetchone()
        if not a:
            raise HTTPException(404, "Auction not found")
        high = c.execute(
            "SELECT coalesce(max(current_amount_cents),0) high, (SELECT coalesce(max(intake_seq),0) FROM bid_requests WHERE auction_id=%s) intake_seq FROM bidder_offers WHERE auction_id=%s",
            (aid, aid),
        ).fetchone()
        a["intake_seq"] = max(a["intake_seq"], high["intake_seq"])
        high = high["high"]
        a.update(
            high_cents=high,
            minimum_next_cents=max(a["min_price_cents"], high + a["increment_cents"] if high else 0),
            server_time=datetime.now(UTC),
        )
        return a


@app.get("/v1/auctions")
def auctions(user=Depends(current_user)):
    with connection() as c:
        return c.execute(
            "SELECT a.*,greatest(a.intake_seq,coalesce(r.intake_seq,0)) AS intake_seq FROM auctions a LEFT JOIN LATERAL(SELECT max(intake_seq) intake_seq FROM bid_requests WHERE auction_id=a.id) r ON true ORDER BY closes_at DESC LIMIT 100"
        ).fetchall()


@app.get("/v1/auctions/{aid}")
def auction(aid: UUID, user=Depends(current_user)):
    return snapshot(aid)


class Bid(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    amount_cents: int = Field(strict=True, gt=0, le=10**12)


class ServiceBid(Bid):
    session_cookie: str = Field(min_length=1, max_length=4096)


class AdmissionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auction_id: UUID
    requests: list[ServiceBid] = Field(min_length=1, max_length=512)


@app.post("/internal/v1/admissions", include_in_schema=False)
def internal_admission(body: AdmissionBatch):
    results = [None] * len(body.requests)
    verified = []
    for index, item in enumerate(body.requests):
        try:
            verified.append((index, subject(item.session_cookie)))
        except HTTPException as error:
            results[index] = {"http_status": error.status_code, "detail": error.detail}
    users = users_many(None, [uid for _, uid in verified]) if verified else []
    accepted = []
    for (index, _), user in zip(verified, users, strict=True):
        try:
            if isinstance(user, HTTPException):
                raise user
            if user["role"] != "bidder":
                raise HTTPException(403, "Role does not permit this action")
            limit(("bid", str(user["id"])), 120)
            item = body.requests[index]
            accepted.append((index, (user["id"], item.request_id, item.amount_cents)))
        except HTTPException as error:
            results[index] = {"http_status": error.status_code, "detail": error.detail}
    outcomes = admit_many(body.auction_id, [entry for _, entry in accepted]) if accepted else []
    for (index, _), outcome in zip(accepted, outcomes, strict=True):
        if isinstance(outcome, LookupError):
            results[index] = {"http_status": 404, "detail": str(outcome)}
        elif isinstance(outcome, Conflict):
            results[index] = {"http_status": 409, "detail": str(outcome)}
        elif isinstance(outcome, OverflowError):
            results[index] = {"http_status": 429, "detail": str(outcome)}
        else:
            results[index] = {
                "http_status": 202 if outcome["state"] == "QUEUED" else 200,
                "request_id": str(outcome["request_id"]),
                "state": outcome["state"],
                "message": "Durable result; query request for final reason",
            }
    return JSONResponse({"results": results})


@app.post("/v1/auctions/{aid}/bids", status_code=202)
async def bid(aid: UUID, body: Bid, user=Depends(roles("bidder"))):
    limit(("bid", str(user["id"])), 120)
    try:
        r = await grouped(
            "admission", aid, (user["id"], body.request_id, body.amount_cents), admit_many, collect_delay=0.100
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except Conflict as e:
        raise HTTPException(409, str(e)) from None
    except OverflowError as e:
        raise HTTPException(429, str(e)) from None
    return JSONResponse(
        status_code=202 if r["state"] == "QUEUED" else 200,
        content={
            "request_id": str(r["request_id"]),
            "state": r["state"],
            "message": "Durably queued; query for final decision"
            if r["state"] == "QUEUED"
            else "Final result; query for recorded reason",
        },
    )


@app.get("/v1/bid-requests/{rid}")
def request_status(rid: UUID, user=Depends(current_user)):
    with connection() as c:
        r = c.execute("SELECT * FROM bid_requests WHERE request_id=%s", (rid,)).fetchone()
        if not r or (r["bidder_id"] != user["id"] and user["role"] != "admin"):
            raise HTTPException(404, "Request not found")
        r["decision"] = c.execute("SELECT * FROM bid_decisions WHERE request_id=%s", (rid,)).fetchone()
        if r["decision"] is None:
            r["decision"] = c.execute(
                "SELECT request_id,status,reason,finalized_at, NULL::bigint AS decision_seq "
                "FROM admission_outcomes WHERE request_id=%s",
                (rid,),
            ).fetchone()
        return r


@app.get("/v1/me/bids")
def history(user=Depends(current_user)):
    with connection() as c:
        return c.execute(
            "SELECT r.*,coalesce(d.reason,o.reason) reason,d.decision_seq FROM bid_requests r "
            "LEFT JOIN bid_decisions d USING(request_id) LEFT JOIN admission_outcomes o USING(request_id) "
            "WHERE r.bidder_id=%s ORDER BY admitted_at DESC LIMIT 100",
            (user["id"],),
        ).fetchall()


@app.get("/v1/auctions/{aid}/winners")
def winners(aid: UUID, user=Depends(current_user)):
    if snapshot(aid)["status"] != "CLOSED":
        return {"state": "PENDING", "winners": []}
    with connection() as c:
        rows = c.execute(
            "SELECT rank,final_amount_cents,bidder_id FROM winners WHERE auction_id=%s ORDER BY rank", (aid,)
        ).fetchall()
    return {
        "state": "FINAL",
        "winners": [
            {"rank": r["rank"], "amount_cents": r["final_amount_cents"], "is_you": r["bidder_id"] == user["id"]}
            for r in rows
        ],
    }


class AuctionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    stock: int = Field(strict=True, gt=0, le=100000)
    min_price_cents: int = Field(strict=True, gt=0, le=10**12)
    increment_cents: int = Field(strict=True, gt=0, le=10**12)
    opens_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def timestamps(self):
        if not self.opens_at.tzinfo or not self.closes_at.tzinfo or self.closes_at <= self.opens_at:
            raise ValueError("Use ordered timezone-aware timestamps")
        return self


@app.post("/v1/admin/auctions", status_code=201)
@app.post("/v1/seller/auctions", status_code=201)
def create_auction(body: AuctionCreate, user=Depends(roles("seller", "admin"))):
    aid = uuid4()
    with connection() as c:
        c.execute(
            "INSERT INTO auctions(id,seller_id,title,stock,min_price_cents,increment_cents,opens_at,closes_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                aid,
                user["id"],
                body.title,
                body.stock,
                body.min_price_cents,
                body.increment_cents,
                body.opens_at,
                body.closes_at,
            ),
        )
    return snapshot(aid)


@app.post("/v1/admin/auctions/{aid}/close")
def end_auction(aid: UUID, user=Depends(roles("seller", "admin"))):
    with connection() as c:
        lock_intake(c, aid)
        a = c.execute("SELECT * FROM auctions WHERE id=%s FOR UPDATE", (aid,)).fetchone()
        if not a:
            raise HTTPException(404, "Auction not found")
        if user["role"] == "seller" and a["seller_id"] != user["id"]:
            raise HTTPException(403, "This auction belongs to another seller")
        if a["opens_at"] >= datetime.now(UTC):
            raise HTTPException(409, "Auction has not opened")
        c.execute("UPDATE auctions SET closes_at=least(closes_at,clock_timestamp()) WHERE id=%s", (aid,))
    return {"state": "CLOSING", "message": "Draining admitted bids before allocation"}


@app.get("/v1/admin/metrics")
def metrics(user=Depends(roles("admin"))):
    with connection() as c:
        stats = c.execute(
            "SELECT count(*) total,count(*) FILTER(WHERE status='ACCEPTED') accepted,count(*) FILTER(WHERE status='REJECTED') rejected,count(*) FILTER(WHERE status='CLOSED') closed FROM bid_decisions"
        ).fetchone()
        stats.update(
            c.execute(
                "SELECT percentile_cont(ARRAY[0.5,0.95,0.99]) WITHIN GROUP(ORDER BY extract(epoch FROM d.committed_at-r.admitted_at)) latency_seconds FROM bid_decisions d JOIN bid_requests r USING(request_id)"
            ).fetchone()
        )
        stats["queue_depth"] = c.execute("SELECT count(*) n FROM bid_requests WHERE state='QUEUED'").fetchone()["n"]
        stats["bids_per_second_last_minute"] = float(
            c.execute(
                "SELECT count(*)/60.0 n FROM bid_decisions WHERE committed_at>now()-interval '60 seconds'"
            ).fetchone()["n"]
        )
        stats["leases"] = c.execute("SELECT * FROM worker_leases ORDER BY lease_expires_at DESC LIMIT 100").fetchall()
        stats["outbox_pending"] = c.execute("SELECT count(*) n FROM outbox WHERE published_at IS NULL").fetchone()["n"]
    stats["open_connections_this_process"] = sum(connections.values())
    return stats


@app.get("/v1/admin/backups")
def backups(user=Depends(roles("admin"))):
    with connection() as c:
        return {
            "jobs": c.execute("SELECT * FROM backup_jobs ORDER BY started_at DESC LIMIT 20").fetchall(),
            "recovery_runs": c.execute("SELECT * FROM recovery_runs ORDER BY created_at DESC LIMIT 20").fetchall(),
        }


@app.websocket("/v1/live/auctions/{aid}")
async def live(ws: WebSocket, aid: UUID):
    try:
        user = await asyncio.to_thread(identity, ws.cookies.get("aegis_session"))
        if ws.headers.get("origin") and ws.headers["origin"] != os.getenv(
            "PUBLIC_ORIGIN", f"{ws.url.scheme.replace('ws', 'http')}://{ws.url.netloc}"
        ):
            raise HTTPException(403, "Origin denied")
        limit(("socket", str(user["id"])), 30)
        if connections[str(aid)] >= 2000:
            raise HTTPException(429, "Auction connection limit reached")
        await asyncio.to_thread(snapshot, aid)
    except HTTPException:
        await ws.close(code=1008)
        return
    await ws.accept()
    connections[str(aid)] += 1
    try:
        # Coalesced authoritative snapshots bound memory and heal missed fanout/version gaps.
        while True:
            data = await asyncio.to_thread(snapshot, aid)
            await asyncio.wait_for(ws.send_json(jsonable_encoder({"type": "auction.snapshot", **data})), timeout=3)
            await asyncio.sleep(1)
    except (WebSocketDisconnect, TimeoutError, RuntimeError):
        pass
    finally:
        connections[str(aid)] -= 1


@app.get("/health")
def health():
    with connection() as c:
        c.execute("SELECT 1")
    return {"database": "ok"}


@app.get("/livez")
def livez():
    return {"process": "ok"}


# Register operation routes after the application and dependencies exist.
import importlib

importlib.import_module("aegis.operations")
