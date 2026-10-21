"""Short-lived, process-local request limits, checked before sign-in or planner work starts.

* Login starts (they create a session and an OAuth state): per network address.
* Planner computations: per signed-in profile, on top of the solve gate (which already allows one
  solve per profile at a time). Ordinary wizard, prefetch and slider use stays far below the limit.

A rejected request gets HTTP 429 with Retry-After and doesn't count. Callbacks, assets, health checks
and normal pages are never limited. Counters live in memory, so a restart resets them.
"""
from __future__ import annotations

import ipaddress
import math
import time
from collections import OrderedDict, deque
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from astracore import config
from .web import render

WINDOW = 60           # seconds
LOGIN_LIMIT = 20      # login starts per network address per window
PLANNER_LIMIT = 120   # planner computations per profile per window
MAX_KEYS = 4096       # buckets kept; the least recently used goes first
LOGIN_PATHS = ("/auth/login", "/auth/community")
COMPUTE_PATHS = {"/pi/api/preview", "/pi/api/apply", "/pi/api/suggest", "/pi/api/whatif",
                 "/pi/api/alternatives", "/pi/api/sensitivity"}


class RequestLimiter:
    """Sliding-window counters with bounded storage: at most MAX_KEYS buckets of at most `limit` times."""

    def __init__(self, max_keys: int = MAX_KEYS):
        self.max_keys = max_keys
        self.buckets: "OrderedDict[tuple, deque]" = OrderedDict()

    def clear(self) -> None:
        self.buckets.clear()

    def check(self, key: tuple, limit: int, now: Optional[float] = None) -> int:
        """Seconds to wait, or 0 when the request may go ahead (it is then counted)."""
        now = time.monotonic() if now is None else now
        cutoff = now - WINDOW
        events = self.buckets.get(key)
        if events is None:
            events = self.buckets[key] = deque()
            while len(self.buckets) > self.max_keys:
                self.buckets.popitem(last=False)
        self.buckets.move_to_end(key)
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            return max(1, math.ceil(events[0] + WINDOW - now))
        events.append(now)
        return 0


LIMITER = RequestLimiter()


def _network(address: str) -> str:
    """One bucket per IPv4 address and per IPv6 /64 (what one connection usually gets)."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def client_network(scope: dict) -> str:
    """The client's network address. Forwarded addresses are only trusted in production, where the app
    listens on loopback and the Cloudflare tunnel is the only way in: Cloudflare overwrites any
    CF-Connecting-IP a client sends. Locally, every header is ignored."""
    peer = (scope.get("client") or ("unknown", 0))[0]
    if config.PRODUCTION:
        values = [v.decode("latin-1").strip() for k, v in scope.get("headers", []) if k == b"cf-connecting-ip"]
        if len(values) == 1:
            try:
                return _network(str(ipaddress.ip_address(values[0])))
            except ValueError:
                pass
    return _network(peer)


def _limit_for(scope: dict):
    path, method = scope["path"], scope["method"]
    if method == "GET" and (path in LOGIN_PATHS or path.startswith("/auth/upgrade/")):
        return ("login", client_network(scope)), LOGIN_LIMIT
    user = scope.get("state", {}).get("user")
    if method == "POST" and path in COMPUTE_PATHS and user:
        return ("planner", user["id"]), PLANNER_LIMIT
    return None, 0


class RequestLimitMiddleware:
    """Sits inside SessionMiddleware, so planner limits apply to the profile, not to one browser."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        key, limit = _limit_for(scope)
        wait = LIMITER.check(key, limit) if key else 0
        if not wait:
            return await self.app(scope, receive, send)
        unit = "second" if wait == 1 else "seconds"
        if key[0] == "login":
            message = f"Too many sign-in attempts from your network. Wait {wait} {unit}, then try again."
        else:
            message = f"Too many planning requests in a short time. Wait {wait} {unit}, then try again."
        if scope["path"].startswith("/pi/api/"):
            response = JSONResponse({"error": message, "retry_after": wait}, status_code=429)
        else:
            response = render(Request(scope), "error.html", page_title="Please wait", code=429,
                              message=message, status_code=429)
        response.headers["Retry-After"] = str(wait)
        response.headers["Cache-Control"] = "no-store"
        await response(scope, receive, send)
