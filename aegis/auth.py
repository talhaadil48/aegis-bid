import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from aegis import config
from aegis.coalescing import grouped
from aegis.db import connection


class NewAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=12, max_length=128)


def create_account(account: NewAccount, role: str, *, first_admin=False):
    password_hash = hash_password(account.password)
    with connection() as c:
        if first_admin:
            # Prevent concurrent setup and account provisioning from racing the check.
            c.execute("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE")
            if c.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone():
                raise HTTPException(409, "An administrator already exists")
        return c.execute(
            """
            INSERT INTO users (id, username, password_hash, role)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (username) DO NOTHING
            RETURNING id, username, role
            """,
            (uuid4(), account.username, password_hash, role),
        ).fetchone()


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return base64.b64encode(salt + digest).decode()


def check_password(password, encoded):
    raw = base64.b64decode(encoded)
    digest = hashlib.scrypt(password.encode(), salt=raw[:16], n=16384, r=8, p=1)
    return hmac.compare_digest(raw[16:], digest)


def token(user):
    config.require_secret()
    return jwt.encode(
        {"sub": str(user["id"]), "exp": datetime.now(UTC) + timedelta(hours=4), "iss": "aegisbid"},
        config.SECRET,
        algorithm="HS256",
    )


def subject(raw):
    config.require_secret()
    try:
        payload = jwt.decode(
            raw or "",
            config.SECRET,
            algorithms=["HS256"],
            issuer="aegisbid",
            options={"require": ["exp", "sub", "iss"]},
        )
        return UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, "Sign in required") from None


def users_many(_key, ids):
    with connection() as c:
        rows = c.execute("SELECT id,username,role FROM users WHERE id=ANY(%s)", (ids,)).fetchall()
    users = {r["id"]: r for r in rows}
    return [users.get(uid) or HTTPException(401, "Sign in required") for uid in ids]


def identity(raw):
    result = users_many(None, [subject(raw)])[0]
    if isinstance(result, Exception):
        raise result
    return result


async def current_user(request: Request):
    uid = subject(request.cookies.get("aegis_session"))
    try:
        return await grouped("identity", "all", uid, users_many)
    except OverflowError as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "1"}) from None


def roles(*allowed):
    async def dependency(user=Depends(current_user)):
        if user["role"] not in allowed:
            raise HTTPException(403, "Role does not permit this action")
        return user

    return dependency
