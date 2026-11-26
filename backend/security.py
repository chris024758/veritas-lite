"""Server-side authentication and request limits shared by all API routes."""
import argparse
import hashlib
import hmac
import os
import re
import secrets
import time
from getpass import getpass
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

import db

DEMO_USERNAME = "demo123"
ENVIRONMENT = os.getenv("VERITAS_ENV", "development")
if ENVIRONMENT not in {"development", "production"}:
    raise RuntimeError("VERITAS_ENV must be development or production")
PRODUCTION = ENVIRONMENT == "production"
DEMO_ENABLED = os.getenv("VERITAS_ENABLE_DEMO", "0" if PRODUCTION else "1") == "1"
COOKIE = "__Host-veritas_session" if PRODUCTION else "veritas_session"
SESSION_SECONDS = 8 * 60 * 60
USERNAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_JSON_BYTES = 64 * 1024
MAX_AUDIO_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
LOGIN_LIMIT = 8
API_LIMIT = 180
TOOL_LIMIT = 20
_password_slots = BoundedSemaphore(2)
_dummy_hash = "00" * 16 + ":" + "00" * 64


def allowed_origins() -> list[str]:
    defaults = "" if PRODUCTION else "http://localhost:5173,http://127.0.0.1:5173"
    configured = os.getenv("VERITAS_ALLOWED_ORIGINS", defaults)
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        port = parsed.port
        if (parsed.scheme not in ({"https"} if PRODUCTION else {"http", "https"})
                or not parsed.hostname or parsed.username or parsed.password or "@" in parsed.netloc
                or port == 0 or "*" in origin or origin != f"{parsed.scheme}://{parsed.netloc}"):
            raise RuntimeError("VERITAS_ALLOWED_ORIGINS must contain exact browser origins")
    if PRODUCTION and not origins:
        raise RuntimeError("Set VERITAS_ALLOWED_ORIGINS for production")
    return origins


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256 * 1024**2)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}:{_scrypt(password, salt).hex()}"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _account_for(token: str) -> str | None:
    if not re.fullmatch(r"[\w-]{43}", token, flags=re.ASCII):
        return None
    with db.connect() as conn:
        row = conn.execute("SELECT username FROM auth_sessions WHERE token_hash = ? AND expires_at > ?",
                           (_token_hash(token), int(time.time()))).fetchone()
    return row["username"] if row else None


def _rate_limit(scope: str, client: str, limit: int) -> int | None:
    """Count requests atomically across workers using the same SQLite database."""
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        window, elapsed = divmod(int(time.time()), 60)
        conn.execute("DELETE FROM rate_limits WHERE window < ?", (window,))
        updated = conn.execute(
            """INSERT INTO rate_limits VALUES (?, ?, ?, 1)
               ON CONFLICT(scope, client) DO UPDATE SET requests = rate_limits.requests + 1
               WHERE rate_limits.requests < ?""", (scope, client, window, limit),
        )
    return None if updated.rowcount else 60 - elapsed


class RequestSecurity:
    def __init__(self, app, origins: list[str]):
        self.app = app
        self.origins = origins

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        method = request.method
        path = scope["path"]
        root = scope.get("root_path", "")
        if root and path.startswith(f"{root}/"):
            path = path[len(root):]

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                if PRODUCTION and scope["scheme"] == "https":
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        async def reject(status, detail, headers=None):
            await JSONResponse({"detail": detail}, status_code=status, headers=headers)(scope, receive, send_with_headers)

        if method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if (origin is not None and origin not in self.origins) or request.headers.get("sec-fetch-site") == "cross-site":
                await reject(403, "Request origin is not allowed")
                return
        if PRODUCTION and scope["scheme"] != "https":
            await reject(400, "HTTPS is required")
            return

        logging_in = method == "POST" and path == "/auth/login"
        client = request.client.host if request.client else "unknown"
        if logging_in:
            retry = await run_in_threadpool(_rate_limit, "login", client, LOGIN_LIMIT)
            if retry is None:
                retry = await run_in_threadpool(_rate_limit, "login-global", "all", 60)
        else:
            retry = await run_in_threadpool(_rate_limit, "api", client, API_LIMIT)
        if retry is not None:
            await reject(429, "Too many requests", {"Retry-After": str(retry)})
            return

        if not logging_in:
            account = await run_in_threadpool(_account_for, request.cookies.get(COOKIE, ""))
            if not account or (account == DEMO_USERNAME and not DEMO_ENABLED):
                await reject(401, "Sign in required")
                return
            request.state.account = account
            if (path == "/static" or path.startswith("/static/")) and account != DEMO_USERNAME:
                await reject(404, "File not found")
                return
            if method == "POST" and (path.startswith("/tools/") or path.endswith(
                    ("/statements", "/audio", "/transcribe", "/extract", "/report"))):
                retry = await run_in_threadpool(_rate_limit, "tools", account, TOOL_LIMIT)
                if retry is not None:
                    await reject(429, "Too many requests", {"Retry-After": str(retry)})
                    return

        limit = MAX_JSON_BYTES
        if request.headers.get("content-type", "").split(";", 1)[0].lower() == "multipart/form-data":
            limit += MAX_AUDIO_BYTES if path.endswith(("/audio", "/transcribe")) else MAX_IMAGE_BYTES
        content_length = request.headers.get("content-length")
        if content_length is not None:
            if not re.fullmatch(r"[0-9]{1,20}", content_length):
                await reject(400, "Invalid Content-Length")
                return
            if int(content_length) > limit:
                await reject(413, "Request body is too large")
                return

        size = 0

        async def receive_limited():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                raise HTTPException(413, "Request body is too large")
            return message

        await self.app(scope, receive_limited, send_with_headers)


auth = APIRouter(prefix="/auth")


class Credentials(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=1, max_length=256)


@auth.post("/login")
def login(body: Credentials, request: Request, response: Response):
    if not _password_slots.acquire(blocking=False):
        raise HTTPException(429, "Too many sign-in attempts", headers={"Retry-After": "1"})
    try:
        with db.connect() as conn:
            row = conn.execute("SELECT password_hash FROM accounts WHERE username = ?", (body.username,)).fetchone()
        salt, expected = (row["password_hash"] if row else _dummy_hash).split(":", 1)
        matches = hmac.compare_digest(_scrypt(body.password, bytes.fromhex(salt)), bytes.fromhex(expected))
    finally:
        _password_slots.release()
    if not matches or not row or (body.username == DEMO_USERNAME and not DEMO_ENABLED):
        raise HTTPException(401, "Invalid username or password")

    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with db.connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ? OR token_hash = ?",
                     (now, _token_hash(request.cookies.get(COOKIE, ""))))
        conn.execute("INSERT INTO auth_sessions VALUES (?, ?, ?)", (_token_hash(token), body.username, now + SESSION_SECONDS))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=PRODUCTION, samesite="strict")
    return {"username": body.username}


@auth.get("/session")
def current_session(request: Request):
    return {"username": request.state.account}


@auth.post("/logout", status_code=204)
def logout(request: Request):
    with db.connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_token_hash(request.cookies[COOKIE]),))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, httponly=True, secure=PRODUCTION, samesite="strict")
    return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a local account and assign existing, unowned cases to it.")
    parser.add_argument("username")
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    if args.username == DEMO_USERNAME or not re.fullmatch(USERNAME_PATTERN, args.username):
        parser.error("Choose a valid username other than the reserved demo username")
    password = getpass("Password: ")
    if not 15 <= len(password) <= 256 or password != getpass("Confirm password: "):
        parser.error("Passwords must match and contain 15 to 256 characters")
    password_hash = hash_password(password)
    db.init_db()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM accounts WHERE username = ?", (args.username,)).fetchone():
            parser.error("Account already exists")
        conn.execute("INSERT INTO accounts VALUES (?, ?)", (args.username, password_hash))
        for case_id in dict.fromkeys(args.case):
            assigned = conn.execute("UPDATE cases SET owner = ? WHERE id = ? AND owner IS NULL", (args.username, case_id))
            if not assigned.rowcount:
                parser.error(f"Case {case_id!r} is missing or already owned")
