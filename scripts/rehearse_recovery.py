"""Create a new source database and restore copy for a reproducible local recovery drill."""

import os
import subprocess
import sys
from datetime import UTC
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from aegis.config import DATABASE_URL


def main():
    name = "aegis_drill_" + uuid4().hex
    with psycopg.connect(DATABASE_URL, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    fields = conninfo_to_dict(DATABASE_URL)
    fields["dbname"] = name
    env = {**os.environ, "DATABASE_URL": make_conninfo(**fields)}
    result = subprocess.run([sys.executable, "-m", "scripts.rehearse_recovery", "--source"], env=env, check=False)
    raise SystemExit(result.returncode)


def source():
    import json
    from datetime import datetime, timedelta

    from aegis.db import connection, migrate
    from aegis.engine import admit, close, process
    from scripts.backup_export import export
    from scripts.restore_sandbox import restore

    migrate()
    aid, seller = uuid4(), uuid4()
    with connection() as c:
        c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (seller, str(seller), "unused", "seller"))
        now = datetime.now(UTC)
        c.execute(
            "INSERT INTO auctions(id,seller_id,title,stock,min_price_cents,increment_cents,opens_at,closes_at) VALUES(%s,%s,%s,3,100,10,%s,%s)",
            (aid, seller, "Recovery rehearsal", now - timedelta(minutes=1), now + timedelta(minutes=5)),
        )
    for index in range(4):
        bidder = uuid4()
        with connection() as c:
            c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (bidder, str(bidder), "unused", "bidder"))
        for retry in range(5):
            rid = uuid4()
            admit(aid, bidder, rid, 100 + (index * 5 + retry) * 10)
            admit(aid, bidder, rid, 100 + (index * 5 + retry) * 10)
            process(aid, "rehearsal-worker")
    with connection() as c:
        c.execute("UPDATE auctions SET closes_at=clock_timestamp() WHERE id=%s", (aid,))
    close(aid, "rehearsal-worker")
    directory = Path("backup-staging") / ("drill-" + uuid4().hex[:12])
    manifest = export(directory)
    report = restore(directory, "docs/evidence/recovery-local")
    print(
        json.dumps(
            {
                "source_database": conninfo_to_dict(DATABASE_URL)["dbname"],
                "export_directory": str(directory),
                "snapshot_id": manifest["snapshot_id"],
                "report": report,
            },
            indent=2,
        )
    )
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    if "--source" in sys.argv:
        source()
    else:
        main()
