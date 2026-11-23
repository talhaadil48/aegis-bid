import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request

from aegis import config
from aegis.coalescing import grouped
from aegis.db import connection


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
