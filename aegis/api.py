import asyncio
import os
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.responses import JSONResponse

from aegis import config
from aegis.auth import NewAccount, check_password, create_account, current_user, identity, roles, token
from aegis.coalescing import grouped
from aegis.db import connection
from aegis.engine import Conflict
from aegis.engine_batch import admit_many

app = FastAPI(title="AegisBid Omega", version="1.0.0")
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


@app.middleware("http")
async def security(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin != os.getenv("PUBLIC_ORIGIN", str(request.base_url).rstrip("/")):
            return Response("Cross-origin request denied", status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


@app.exception_handler(RequestValidationError)
async def validate_request(request: Request, exc: RequestValidationError):
    if request.url.path in ("/v1/auth/register", "/v1/auth/login"):
        return JSONResponse({"detail": "Check the username and password fields."}, status_code=422)
    return await request_validation_exception_handler(request, exc)


def start_session(response: Response, user):
    response.set_cookie(
        "aegis_session",
        token(user),
        httponly=True,
        samesite="strict",
        secure=config.ENVIRONMENT == "production",
        max_age=14400,
    )
    return {k: user[k] for k in ("id", "username", "role")}


@app.post("/v1/auth/login")
def login(body: Login, response: Response, request: Request):
    limit(("login", request.client.host), 10)
    with connection() as c:
        user = c.execute("SELECT * FROM users WHERE username=%s", (body.username,)).fetchone()
    if not user or not check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    return start_session(response, user)


@app.post("/v1/auth/register", status_code=201)
def register(body: NewAccount, response: Response, request: Request):
    limit(("register", request.client.host), 5)
    config.require_secret()
    if body.username.lower() in {"admin", "seller", "auditor"}:
        raise HTTPException(409, "Username is unavailable")
    user = create_account(body, role="bidder")
    if user is None:
        raise HTTPException(409, "Username is unavailable")
    return start_session(response, user)


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
            "SELECT coalesce(max(current_amount_cents),0) high FROM bidder_offers WHERE auction_id=%s", (aid,)
        ).fetchone()["high"]
        a.update(
            high_cents=high,
            minimum_next_cents=max(a["min_price_cents"], high + a["increment_cents"] if high else 0),
            server_time=datetime.now(UTC),
        )
        return a


@app.get("/v1/auctions")
def auctions(user=Depends(current_user)):
    with connection() as c:
        return c.execute("SELECT * FROM auctions ORDER BY closes_at DESC LIMIT 100").fetchall()


@app.get("/v1/auctions/{aid}")
def auction(aid: UUID, user=Depends(current_user)):
    return snapshot(aid)


class Bid(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    amount_cents: int = Field(strict=True, gt=0, le=10**12)


@app.post("/v1/auctions/{aid}/bids", status_code=202)
async def bid(aid: UUID, body: Bid, response: Response, user=Depends(roles("bidder"))):
    limit(("bid", str(user["id"])), 120)
    try:
        r = await grouped("admission", aid, (user["id"], body.request_id, body.amount_cents), admit_many)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except Conflict as e:
        raise HTTPException(409, str(e)) from None
    except OverflowError as e:
        raise HTTPException(429, str(e)) from None
    response.status_code = 202 if r["state"] == "QUEUED" else 200
    return {
        "request_id": r["request_id"],
        "state": r["state"],
        "message": "Durably queued; query for final decision"
        if r["state"] == "QUEUED"
        else "Final result; query for recorded reason",
    }


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
