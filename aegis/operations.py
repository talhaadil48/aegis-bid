import os
from uuid import UUID

from fastapi import Depends, HTTPException, Response
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from pydantic import BaseModel

from aegis.api import app, connections, metrics
from aegis.auth import current_user, roles
from aegis.db import connection
from aegis.evidence import export_auction


@app.get("/v1/audit/auctions/{aid}")
def audit(aid: UUID, user=Depends(roles("admin", "auditor", "seller"))):
    try:
        return export_auction(aid, seller_id=user["id"] if user["role"] == "seller" else None)
    except LookupError:
        raise HTTPException(404, "Auction not found") from None


@app.get("/v1/seller/auctions")
def seller_auctions(user=Depends(roles("seller"))):
    with connection() as c:
        return c.execute(
            """
            SELECT id, seller_id, title, stock, opens_at, closes_at, status
            FROM auctions WHERE seller_id=%s ORDER BY closes_at DESC, id LIMIT 100
            """,
            (user["id"],),
        ).fetchall()


@app.get("/v1/seller/auctions/{aid}/activity")
def seller_activity(aid: UUID, user=Depends(roles("seller"))):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        owned = c.execute("SELECT 1 FROM auctions WHERE id=%s AND seller_id=%s", (aid, user["id"])).fetchone()
        if not owned:
            raise HTTPException(404, "Auction not found")
        counts = c.execute(
            """
            SELECT count(DISTINCT bidder_id) AS bidders, count(*) AS total,
                   count(*) FILTER (WHERE state='ACCEPTED') AS accepted,
                   count(*) FILTER (WHERE state='REJECTED') AS rejected,
                   count(*) FILTER (WHERE state='QUEUED') AS queued,
                   count(*) FILTER (WHERE state='CLOSED') AS closed
            FROM bid_requests WHERE auction_id=%s
            """,
            (aid,),
        ).fetchone()
        recent = c.execute(
            """
            SELECT r.request_id, r.intake_seq, r.amount_cents, r.state, r.admitted_at,
                   d.committed_at, coalesce(d.reason,o.reason) AS reason
            FROM (
                SELECT request_id, intake_seq, amount_cents, state, admitted_at
                FROM bid_requests WHERE auction_id=%s ORDER BY intake_seq DESC LIMIT 5
            ) r
            LEFT JOIN bid_decisions d USING (request_id)
            LEFT JOIN admission_outcomes o USING (request_id)
            ORDER BY r.intake_seq DESC
            """,
            (aid,),
        ).fetchall()
    return {"counts": counts, "recent": recent}


@app.get("/v1/bid-requests/{rid}/receipt")
def receipt(rid: UUID, user=Depends(current_user)):
    with connection() as c:
        r = c.execute("SELECT * FROM bid_requests WHERE request_id=%s AND bidder_id=%s", (rid, user["id"])).fetchone()
        if not r:
            raise HTTPException(404, "Request not found")
        event = c.execute(
            "SELECT event_seq,event_hash FROM auction_events WHERE auction_id=%s AND payload->>'request_id'=%s",
            (r["auction_id"], str(rid)),
        ).fetchone()
        return {
            "request_id": rid,
            "auction_id": r["auction_id"],
            "state": r["state"],
            "event": event,
            "verification": "Compare event hash against independently verified signed auction manifest",
        }


class Scenario(BaseModel):
    scenario: str


@app.post("/v1/admin/chaos/scenarios", status_code=202)
def chaos(body: Scenario, user=Depends(roles("admin"))):
    if os.getenv("ENABLE_CHAOS") != "true" or os.getenv("ENVIRONMENT", "development") not in ("development", "test"):
        raise HTTPException(403, "Chaos is disabled outside explicitly enabled disposable environments")
    allowed = {"pause-queue-consumer", "resume-queue-consumer", "kill-worker", "restart-gateway", "disconnect-client"}
    if body.scenario not in allowed:
        raise HTTPException(422, "Scenario not supported: " + ", ".join(sorted(allowed)))
    with connection() as c:
        if body.scenario == "pause-queue-consumer":
            c.execute("INSERT INTO incidents(scenario,state) VALUES(%s,'ACTIVE')", (body.scenario,))
        elif body.scenario == "resume-queue-consumer":
            c.execute("UPDATE incidents SET state='RESOLVED' WHERE scenario='pause-queue-consumer' AND state='ACTIVE'")
            c.execute("INSERT INTO incidents(scenario,state) VALUES(%s,'RESOLVED')", (body.scenario,))
        else:
            c.execute("INSERT INTO incidents(scenario,state) VALUES(%s,'PENDING')", (body.scenario,))
    return {
        "scenario": body.scenario,
        "state": "ACTIVE" if body.scenario == "pause-queue-consumer" else "REQUESTED",
        "note": "Process faults require the local allowlisted controller",
    }


@app.get("/v1/admin/incidents")
def incidents(user=Depends(roles("admin"))):
    with connection() as c:
        return c.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT 100").fetchall()


@app.get("/metrics")
def prometheus():
    registry = CollectorRegistry()
    data = metrics(user={"role": "admin"})
    for name, value in [
        ("gateway_connected_clients", sum(connections.values())),
        ("bid_commands_total", data["total"] + data["queue_depth"]),
        ("auction_queue_depth", data["queue_depth"]),
        ("outbox_pending", data["outbox_pending"]),
    ]:
        Gauge(name, "Measured local AegisBid value", registry=registry).set(value)
    decisions = Gauge("bid_decisions_total", "Committed decisions", ["status"], registry=registry)
    for status in ["accepted", "rejected", "closed"]:
        decisions.labels(status.upper()).set(data[status])
    latency = Gauge("bid_decision_latency_seconds", "Admission to commit quantiles", ["quantile"], registry=registry)
    if data["latency_seconds"]:
        for q, value in zip(["0.5", "0.95", "0.99"], data["latency_seconds"], strict=True):
            latency.labels(q).set(value)
    return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")
