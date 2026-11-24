"""Security headers and origin checks without per-request middleware task queues."""

import os

from starlette.requests import Request
from starlette.responses import Response


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message["headers"]
                    if k.lower() not in (b"cache-control", b"x-content-type-options")
                ]
                headers.extend([(b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-store")])
                message = {**message, "headers": headers}
            await send(message)

        if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            origin = next((v.decode("latin1") for k, v in scope["headers"] if k.lower() == b"origin"), None)
            if origin and origin != os.getenv("PUBLIC_ORIGIN", str(Request(scope).base_url).rstrip("/")):
                await Response("Cross-origin request denied", status_code=403)(scope, receive, secure_send)
                return
        await self.app(scope, receive, secure_send)
