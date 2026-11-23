import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aegis.auth import hash_password
from aegis.db import connection, migrate


def main():
    password = os.environ["DEMO_PASSWORD"]
    if len(password) < 10:
        raise ValueError("DEMO_PASSWORD must have at least 10 characters")
    migrate()
    with connection() as c:
        for name, role in [
            ("admin", "admin"),
            ("seller", "seller"),
            ("auditor", "auditor"),
            ("bidder1", "bidder"),
            ("bidder2", "bidder"),
        ]:
            c.execute(
                "INSERT INTO users VALUES(%s,%s,%s,%s) ON CONFLICT(username) DO NOTHING",
                (uuid4(), name, hash_password(password), role),
            )
        seller = c.execute("SELECT id FROM users WHERE username='seller'").fetchone()["id"]
        if not c.execute("SELECT 1 FROM auctions LIMIT 1").fetchone():
            now = datetime.now(UTC)
            c.execute(
                "INSERT INTO auctions(id,seller_id,title,stock,min_price_cents,increment_cents,opens_at,closes_at) VALUES(%s,%s,%s,3,10000,500,%s,%s)",
                (
                    uuid4(),
                    seller,
                    "Founders Edition · Mechanical Keyboard",
                    now - timedelta(minutes=1),
                    now + timedelta(hours=2),
                ),
            )
    print("Seeded demo accounts: admin, seller, auditor, bidder1, bidder2. Password supplied by DEMO_PASSWORD.")


if __name__ == "__main__":
    main()
