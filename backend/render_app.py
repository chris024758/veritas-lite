"""Same-origin, password-protected entry point for the resettable Render demo."""
import asyncio
import base64
import binascii
import hashlib
import hmac
import os
import time
from collections import deque
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.staticfiles import StaticFiles

MAX_IMAGE_REQUEST_BYTES = 11 * 1024 * 1024  # 10 MiB image plus multipart fields
MAX_WRITE_BYTES = 32 * 1024
MAX_WRITES_PER_MINUTE = 12
MAX_BAD_PASSWORDS_PER_MINUTE = 20
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def allow_attempt(attempts, limit):
    now = time.monotonic()
    while attempts and attempts[0] <= now - 60:
        attempts.popleft()
    if len(attempts) >= limit:
        return False
    attempts.append(now)
    return True


def too_many(detail):
    return JSONResponse({"detail": detail}, 429, headers={"Retry-After": "60"})


class DemoAccess:
    def __init__(self, app, password, origin=None):
        self.app = app
        self.credential = hashlib.sha256(f"demo:{password}".encode()).digest()
        self.origin = origin
        self.bad_passwords = deque()
        self.writes = deque()
        self.writing = False

    def authenticated(self, authorization):
        scheme, _, encoded = authorization.partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            credentials = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return False
        return hmac.compare_digest(hashlib.sha256(credentials).digest(), self.credential)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_uncached(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Cache-Control"] = "no-store"
                response_headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        method, path = scope["method"], scope["path"]
        if path == "/healthz" and method == "GET":
            return await JSONResponse({"status": "ok"})(scope, receive, send_uncached)

        headers = Headers(scope=scope)
        authorization = headers.get("authorization", "")
        if not self.authenticated(authorization):
            if authorization and not allow_attempt(self.bad_passwords, MAX_BAD_PASSWORDS_PER_MINUTE):
                response = too_many("Too many failed sign-in attempts.")
            else:
                response = JSONResponse({"detail": "Sign in to the demo."}, 401, headers={
                    "WWW-Authenticate": 'Basic realm="Veritas Lite", charset="UTF-8"',
                })
            return await response(scope, receive, send_uncached)

        if method in READ_METHODS:
            return await self.app(scope, receive, send_uncached)

        origin = self.origin or f'{scope["scheme"]}://{headers.get("host", "")}'
        if headers.get("origin", origin) != origin or headers.get("sec-fetch-site") == "cross-site":
            return await JSONResponse({"detail": "Cross-origin write denied."}, 403)(scope, receive, send_uncached)
        if path.startswith("/sessions/") and path.rstrip("/").endswith(("/audio", "/transcribe")):
            return await JSONResponse({"detail": "Use typed interviews in the hosted demo."}, 403)(scope, receive, send_uncached)
        if self.writing:
            response = JSONResponse({"detail": "Another operation is running. Try again when it finishes."}, 429,
                                    headers={"Retry-After": "1"})
            return await response(scope, receive, send_uncached)
        if not allow_attempt(self.writes, MAX_WRITES_PER_MINUTE):
            return await too_many("Demo write limit reached. Try again in a minute.")(scope, receive, send_uncached)

        self.writing = True
        try:
            image_upload = path == "/tools/extract-image" or path.endswith("/attachments")
            limit = MAX_IMAGE_REQUEST_BYTES if image_upload else MAX_WRITE_BYTES
            return await self.run_write(scope, receive, send_uncached, limit)
        finally:
            self.writing = False

    async def run_write(self, scope, receive, send, limit):
        # Count actual bytes, including requests without Content-Length, before multipart parsing.
        body = bytearray()
        try:
            async with asyncio.timeout(15):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        return await JSONResponse({"detail": "Request body is too large."}, 413)(scope, receive, send)
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await JSONResponse({"detail": "Request upload timed out."}, 408)(scope, receive, send)

        async def replay_body():
            nonlocal body
            if body is None:
                return await receive()
            message = {"type": "http.request", "body": bytes(body), "more_body": False}
            body = None
            return message

        return await self.app(scope, replay_body, send)


def create_app():
    password = os.getenv("VERITAS_DEMO_PASSWORD", "")
    if len(password) < 24:
        raise RuntimeError("Set VERITAS_DEMO_PASSWORD to a random password of at least 24 characters.")

    from main import app as api
    from seed import seed

    frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    api.mount("/assets", StaticFiles(directory=frontend / "assets"), name="frontend-assets")

    @api.get("/", include_in_schema=False)
    def index():
        return FileResponse(frontend / "index.html")

    seed()
    return DemoAccess(api, password, os.getenv("RENDER_EXTERNAL_URL"))
