import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request

from aegis import config
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


def identity(raw):
    config.require_secret()
    try:
        payload = jwt.decode(
            raw or "",
            config.SECRET,
            algorithms=["HS256"],
            issuer="aegisbid",
            options={"require": ["exp", "sub", "iss"]},
        )
        with connection() as c:
            user = c.execute("SELECT id,username,role FROM users WHERE id=%s", (payload["sub"],)).fetchone()
        if not user:
            raise ValueError("Unknown identity")
        return user
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(401, "Sign in required") from None


def current_user(request: Request):
    return identity(request.cookies.get("aegis_session"))


def roles(*allowed):
    def dependency(user=Depends(current_user)):
        if user["role"] not in allowed:
            raise HTTPException(403, "Role does not permit this action")
        return user

    return dependency
