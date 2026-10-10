"""Server-side sessions (cookie `ac_session`) and CSRF protection.

The cookie holds a random 32-byte value; the database only stores its HMAC (keyed with
ASTRACORE_SESSION_SECRET), so a copy of the database can't be used to sign in. Sessions slide:
30 days after the last visit. A session exists before sign-in too (it binds the SSO `state`), and
is replaced by a fresh one at sign-in.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from http.cookies import SimpleCookie
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request

from astracore import config, db

COOKIE = "ac_session"
MAX_AGE = 30 * 86400
TOUCH_EVERY = 300          # seconds between last_seen/expiry updates
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _secret() -> bytes:
    s = config.session_secret()
    if not s:
        if config.PRODUCTION:
            raise RuntimeError("ASTRACORE_SESSION_SECRET is missing in .env.production")
        s = secrets.token_hex(32)
        config.save_env({"ASTRACORE_SESSION_SECRET": s})
        config._ENV["ASTRACORE_SESSION_SECRET"] = s
    return s.encode()


def hash_id(raw: str) -> str:
    return hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()


def _ip_hint(scope: dict, headers: Dict[str, str]) -> str:
    """Coarse location hint for the sessions list: first two parts of the IP only."""
    ip = headers.get("cf-connecting-ip") or headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not ip and scope.get("client"):
        ip = scope["client"][0]
    if ":" in ip:
        return ":".join(ip.split(":")[:2]) + ":…"
    parts = ip.split(".")
    return ".".join(parts[:2]) + ".x.x" if len(parts) == 4 else ""


def _load(raw: Optional[str]) -> Optional[dict]:
    if not raw or len(raw) > 128:
        return None
    h = hash_id(raw)
    with db.session() as c:
        r = c.execute("SELECT * FROM sessions WHERE id_hash=?", (h,)).fetchone()
    if not r:
        return None
    s = dict(r)
    if s["expires_at"] < time.time():
        with db.session() as c:
            c.execute("DELETE FROM sessions WHERE id_hash=?", (h,))
        return None
    s["data"] = json.loads(s.pop("data_json") or "{}")
    return s


def _create(profile_id: Optional[int], scope: dict, headers: Dict[str, str]) -> (str, dict):
    raw = secrets.token_urlsafe(32)
    now = time.time()
    s = {"id_hash": hash_id(raw), "profile_id": profile_id, "csrf": secrets.token_urlsafe(32),
         "created_at": now, "last_seen_at": now, "expires_at": now + MAX_AGE,
         "user_agent": headers.get("user-agent", "")[:200], "ip_hint": _ip_hint(scope, headers), "data": {}}
    with db.session() as c:
        c.execute("INSERT INTO sessions(id_hash, profile_id, csrf, created_at, last_seen_at, expires_at, user_agent, "
                  "ip_hint, data_json) VALUES(?,?,?,?,?,?,?,?, '{}')",
                  (s["id_hash"], profile_id, s["csrf"], now, now, now + MAX_AGE, s["user_agent"], s["ip_hint"]))
    return raw, s


def _cookie_header(value: str, max_age: int) -> bytes:
    parts = [f"{COOKIE}={value}", "Path=/", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
    if config.SECURE_COOKIES:
        parts.append("Secure")
    return "; ".join(parts).encode()


def user_for(sess: Optional[dict]) -> Optional[dict]:
    if not sess or not sess.get("profile_id"):
        return None
    p = db.get_profile(sess["profile_id"])
    if not p:
        return None
    p["is_admin"] = db.is_admin(p["id"])
    return p


class SessionMiddleware:
    """Loads the session + signed-in profile into request.state and writes the cookie when it changes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith(("/static/", "/healthz")):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        jar = SimpleCookie()
        try:
            jar.load(headers.get("cookie", ""))
        except Exception:  # noqa: BLE001 - malformed cookie header: treat as none
            pass
        raw = jar[COOKIE].value if COOKIE in jar else None
        sess = _load(raw)
        state = scope.setdefault("state", {})
        state["session"] = sess
        state["user"] = user_for(sess)
        state["_scope"] = scope
        state["_headers"] = headers
        state["_set_cookie"] = None
        if sess and time.time() - sess["last_seen_at"] > TOUCH_EVERY:
            now = time.time()
            with db.session() as c:
                c.execute("UPDATE sessions SET last_seen_at=?, expires_at=? WHERE id_hash=?",
                          (now, now + MAX_AGE, sess["id_hash"]))
            state["_set_cookie"] = (raw, MAX_AGE)   # slide the browser cookie too
        if raw and not sess:
            state["_set_cookie"] = ("", 0)          # stale cookie: clear it

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and state.get("_set_cookie") is not None:
                value, age = state["_set_cookie"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"set-cookie", _cookie_header(value, age))]
            await send(message)

        await self.app(scope, receive, send_wrapper)


# --------------------------------------------------------------------------- helpers for routes
def ensure(request: Request) -> dict:
    """The current session, creating a signed-out one if there is none (e.g. before an SSO login)."""
    sess = request.state.session
    if sess:
        return sess
    raw, sess = _create(None, request.state._scope, request.state._headers)
    request.state.session = sess
    request.state._set_cookie = (raw, MAX_AGE)
    return sess


def sign_in(request: Request, profile_id: int) -> dict:
    """Start a fresh session for the profile (the old cookie value stops working: no session fixation)."""
    old = request.state.session
    if old:
        with db.session() as c:
            c.execute("DELETE FROM sessions WHERE id_hash=?", (old["id_hash"],))
    raw, sess = _create(profile_id, request.state._scope, request.state._headers)
    request.state.session = sess
    request.state.user = user_for(sess)
    request.state._set_cookie = (raw, MAX_AGE)
    db.update_profile(profile_id, last_login_at=time.time())
    return sess


def sign_out(request: Request) -> None:
    sess = request.state.session
    if sess:
        with db.session() as c:
            c.execute("DELETE FROM sessions WHERE id_hash=?", (sess["id_hash"],))
    request.state.session = None
    request.state.user = None
    request.state._set_cookie = ("", 0)


def sign_out_everywhere(profile_id: int) -> int:
    with db.session() as c:
        return c.execute("DELETE FROM sessions WHERE profile_id=?", (profile_id,)).rowcount


def list_sessions(profile_id: int) -> List[dict]:
    with db.session() as c:
        return [dict(r) for r in c.execute(
            "SELECT id_hash, created_at, last_seen_at, user_agent, ip_hint FROM sessions WHERE profile_id=? "
            "ORDER BY last_seen_at DESC", (profile_id,))]


def end_session(profile_id: int, id_hash: str) -> bool:
    with db.session() as c:
        return c.execute("DELETE FROM sessions WHERE id_hash=? AND profile_id=?", (id_hash, profile_id)).rowcount > 0


def set_data(request: Request, **kw: Any) -> None:
    sess = ensure(request)
    sess["data"].update(kw)
    sess["data"] = {k: v for k, v in sess["data"].items() if v is not None}
    with db.session() as c:
        c.execute("UPDATE sessions SET data_json=? WHERE id_hash=?", (json.dumps(sess["data"]), sess["id_hash"]))


def purge_expired() -> None:
    now = time.time()
    with db.session() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute("DELETE FROM sso_states WHERE created_at < ?", (now - 600,))


# --------------------------------------------------------------------------- CSRF
async def csrf_protect(request: Request) -> None:
    """App-wide dependency: every POST (form or fetch) must carry the session's CSRF token."""
    if request.method in SAFE_METHODS:
        return
    if request.method == "POST" and request.url.path == "/api/community/github/webhook":
        # This machine-to-machine endpoint validates GitHub's signed raw body instead.
        return
    sess = request.state.session
    sent = request.headers.get("x-csrf-token")
    if not sent:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            sent = (await request.form()).get("csrf_token")
    if not sess or not sent or not hmac.compare_digest(str(sent), sess["csrf"]):
        raise HTTPException(status_code=403, detail="Your session expired or the form is stale. Reload the page and try again.")


def require_user(request: Request) -> dict:
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return user
