import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://aegis:aegis-local@127.0.0.1:55432/aegisbid")
NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:54222")
SECRET = os.getenv("SESSION_SECRET", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


def require_secret():
    if len(SECRET) < 32:
        raise RuntimeError("Set SESSION_SECRET to at least 32 random characters")
