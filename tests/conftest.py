import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from aegis.db import connection, migrate


@pytest.fixture
def auction():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Set RUN_INTEGRATION=1 against a disposable PostgreSQL database")
    migrate()
    with connection() as c:
        seller, bidder, aid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        for uid, role in [(seller, "seller"), (bidder, "bidder")]:
            c.execute("INSERT INTO users VALUES(%s,%s,%s,%s)", (uid, str(uid), "unused", role))
        now = datetime.now(UTC)
        c.execute(
            "INSERT INTO auctions(id,seller_id,title,stock,min_price_cents,increment_cents,opens_at,closes_at) VALUES(%s,%s,%s,3,100,10,%s,%s)",
            (aid, seller, "Test", now - timedelta(minutes=1), now + timedelta(minutes=5)),
        )
    return aid, bidder
