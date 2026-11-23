"""Stop one disposable kind node; verify synchronous ledger failover and stale worker fencing."""

import argparse
import base64
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from aegis import db
from aegis.engine import Fenced, admit, close, process
from aegis.evidence import export_auction
from aegis.verifier import verify


def main(kubectl, kubeconfig):
    command = [kubectl, "--kubeconfig", kubeconfig, "--context", "kind-aegis-ha-lab"]

    def kube(*args):
        result = subprocess.run([*command, *args], capture_output=True, text=True, check=True, timeout=60)
        return result.stdout

    def cluster():
        return json.loads(kube("-n", "aegis", "get", "cluster", "aegis-pg", "-o", "json"))

    def wait(predicate, timeout=600):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            current = cluster()
            if predicate(current):
                return current
            time.sleep(2)
        raise TimeoutError("PostgreSQL HA state did not reach the required condition")

    wait(lambda c: c.get("status", {}).get("readyInstances") == 3)
    ca = json.loads(kube("-n", "aegis", "get", "secret", "aegis-pg-ca", "-o", "json"))
    ca_path = Path(".tools/ha-postgres-ca.crt").resolve()
    ca_path.write_bytes(base64.b64decode(ca["data"]["ca.crt"]))
    app = json.loads(kube("-n", "aegis", "get", "secret", "aegis-pg-app", "-o", "json"))
    fields = conninfo_to_dict(base64.b64decode(app["data"]["uri"]).decode())
    fields.update(
        host="127.0.0.1",
        port="55435",
        sslmode="verify-ca",
        sslrootcert=str(ca_path),
        sslnegotiation="direct",
        gssencmode="disable",
    )
    url = make_conninfo(**fields)
    forward = None
    forward_log = Path(".tools/ha-port-forward.log").open("w")  # noqa: SIM115 - closed in the outer finally

    def connect_forward():
        nonlocal forward
        if forward:
            db.close_pools()
            forward.terminate()
            forward.wait(timeout=10)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        forward = subprocess.Popen(
            [*command, "-n", "aegis", "port-forward", "service/aegis-pg-rw", "55435:5432"],
            stdout=subprocess.DEVNULL,
            stderr=forward_log,
            creationflags=flags,
        )
        until = time.monotonic() + 30
        while time.monotonic() < until:
            try:
                with db.connection(url) as probe:
                    probe.execute("SELECT 1")
                    return
            except psycopg.OperationalError:
                time.sleep(1)
        raise TimeoutError("Read-write service did not become reachable")

    before = cluster()
    old_primary = before["status"]["currentPrimary"]
    pod = json.loads(kube("-n", "aegis", "get", "pod", old_primary, "-o", "json"))
    node = pod["spec"]["nodeName"]
    if not re.fullmatch(r"aegis-ha-lab-worker[0-9]*", node):
        raise ValueError("Refusing a fault outside the disposable kind worker nodes")
    original = db.DATABASE_URL
    stopped = False
    try:
        connect_forward()
        db.DATABASE_URL = url
        db.migrate()
        aid, seller = uuid4(), uuid4()
        now = datetime.now(UTC)
        with db.connection() as c:
            c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (seller, str(seller), "unused", "seller"))
            c.execute(
                "INSERT INTO auctions(id,seller_id,title,stock,min_price_cents,increment_cents,opens_at,closes_at) VALUES(%s,%s,%s,3,100,10,%s,%s)",
                (
                    aid,
                    seller,
                    "Synchronous HA ledger rehearsal",
                    now - timedelta(minutes=1),
                    now + timedelta(minutes=10),
                ),
            )
        requests = []
        for index in range(3):
            bidder, rid = uuid4(), uuid4()
            with db.connection() as c:
                c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (bidder, str(bidder), "unused", "bidder"))
            amount = 100 + index * 10
            admit(aid, bidder, rid, amount)
            process(aid, "ha-before")
            requests.append((bidder, rid, amount))
        with db.connection() as c:
            c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
            synchronous = c.execute("SHOW synchronous_standby_names").fetchone()["synchronous_standby_names"]
        close(aid, "ha-before")
        expected = export_auction(aid)
        started = time.monotonic()
        subprocess.run(["docker", "stop", "--time", "5", node], check=True, capture_output=True)
        stopped = True
        running = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.State.Running}}", node], text=True
        ).strip()
        if running != "false":
            raise RuntimeError("Old node is not fenced; refusing to claim safe failover")
        current = wait(
            lambda c: (
                c.get("status", {}).get("currentPrimary") not in (None, "", old_primary)
                and c.get("status", {}).get("readyInstances", 0) >= 2
            ),
            timeout=300,
        )
        connect_forward()
        actual = export_auction(aid)
        for bidder, rid, amount in requests:
            for _ in range(5):
                assert admit(aid, bidder, rid, amount)["state"] == "ACCEPTED"
        process(aid, "ha-after")
        fenced = False
        try:
            process(aid, "ha-before", expected_epoch=1)
        except Fenced:
            fenced = True
        with db.connection() as c:
            c.execute("INSERT INTO incidents(scenario,state) VALUES('ha-post-failover-write','RESOLVED')")
            decisions = c.execute("SELECT count(*) n FROM bid_decisions WHERE auction_id=%s", (aid,)).fetchone()["n"]
        verification = verify(actual)
        valid = actual == expected and not verification["errors"] and fenced and decisions == 3
        report = {
            "status": "PASS" if valid else "FAIL",
            "timestamp": datetime.now(UTC).isoformat(),
            "old_primary": old_primary,
            "new_primary": current["status"]["currentPrimary"],
            "stopped_node": node,
            "old_node_running": False,
            "synchronous_standby_names": synchronous,
            "failover_quorum": current["spec"]["postgresql"]["synchronous"].get("failoverQuorum"),
            "leader_epoch_fencing_passed": fenced,
            "committed_decisions_preserved": decisions,
            "ledger_anchor_matches": actual["anchor"] == expected["anchor"],
            "recovery_s": time.monotonic() - started,
            "verifier_errors": verification["errors"],
            "scope": "Real kind worker-container loss and synchronous PostgreSQL promotion on one host; lab zone labels are simulated failure domains, not physical availability zones",
        }
        Path("docs/evidence/ha-local.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        raise SystemExit(not valid)
    finally:
        db.DATABASE_URL = original
        db.close_pools()
        if forward:
            forward.terminate()
            forward.wait(timeout=10)
        forward_log.close()
        if stopped:
            subprocess.run(["docker", "start", node], check=True, capture_output=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubectl", default=".tools/kubectl.exe" if os.name == "nt" else "kubectl")
    parser.add_argument("--kubeconfig", default=".tools/ha-kubeconfig")
    args = parser.parse_args()
    main(args.kubectl, args.kubeconfig)
