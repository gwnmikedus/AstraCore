"""Static asset versioning and cache headers.

Every static URL the app hands out carries a content hash: /static/img/logo.svg?v=3f9a1c2b7d. A changed file gets a
new URL, so browsers, phones and Cloudflare's edge fetch it straight away, while an unchanged file can be cached for
a year without ever going stale.

Cache rules (set here, so Cloudflare's 4-hour default never applies):
- /static/...?v=<current hash>   -> public, max-age=31536000, immutable
- /static/... without it (or an old hash) -> no-cache: always revalidated (ETag), never served stale
- /favicon.ico, /apple-touch-icon.png  -> no-cache (devices ask for these fixed paths)
- everything else (pages, API)   -> private, no-cache (set by CacheHeaders)

CSS is served with its url(...) references rewritten to versioned URLs, so fonts and images used from a stylesheet
follow the same rules.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, Tuple

from starlette.responses import Response
from starlette.staticfiles import StaticFiles

STATIC = Path(__file__).resolve().parent.parent / "static"
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
DYNAMIC = "private, no-cache"

_hashes: Dict[str, Tuple[float, int, str]] = {}


def _rel(path: str) -> str:
    """'static/img/x.svg', '/static/img/x.svg' and 'img/x.svg' all mean static/img/x.svg."""
    p = path.split("?", 1)[0].lstrip("/")
    return p[len("static/"):] if p.startswith("static/") else p


def version(path: str) -> str:
    """First 10 hex chars of the file's SHA-256; re-hashed only when its mtime or size changes."""
    rel = _rel(path)
    f = STATIC / rel
    try:
        st = f.stat()
    except OSError:
        return "0"
    hit = _hashes.get(rel)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    h = hashlib.sha256(f.read_bytes()).hexdigest()[:10]
    _hashes[rel] = (st.st_mtime, st.st_size, h)
    return h


def asset(path: str) -> str:
    """The versioned URL of a static file: asset('css/astracore.css') -> /static/css/astracore.css?v=..."""
    rel = _rel(path)
    return f"/static/{rel}?v={version(rel)}"


_CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")


def rewrite_css(text: str, css_rel: str) -> str:
    """Point every local url(...) in a stylesheet at its versioned URL (data: and external URLs are left alone)."""
    base = (STATIC / css_rel).parent

    def sub(m: re.Match) -> str:
        quote, ref = m.group(1), m.group(2).strip()
        if ref.startswith(("data:", "http:", "https:", "//", "#")):
            return m.group(0)
        target = (STATIC / _rel(ref)) if ref.startswith("/") else (base / ref.split("?", 1)[0])
        try:
            rel = target.resolve().relative_to(STATIC.resolve()).as_posix()
        except ValueError:
            return m.group(0)
        return f"url({quote}{asset(rel)}{quote})"

    return _CSS_URL.sub(sub, text)


class VersionedStatic(StaticFiles):
    """StaticFiles that sets Cache-Control from the ?v= hash and serves CSS with versioned url()s."""

    async def get_response(self, path: str, scope) -> Response:
        resp = await super().get_response(path, scope)
        if resp.status_code not in (200, 304):
            resp.headers["cache-control"] = REVALIDATE
            return resp
        rel = _rel(path)
        qs = scope.get("query_string", b"").decode()
        wanted = dict(p.split("=", 1) for p in qs.split("&") if "=" in p).get("v")
        current = version(rel)
        if rel.endswith(".css") and resp.status_code == 200:
            body = rewrite_css((STATIC / rel).read_text(), rel).encode()
            etag = '"' + hashlib.sha256(body).hexdigest()[:16] + '"'
            if etag in scope_header(scope, b"if-none-match"):
                resp = Response(status_code=304, headers={"etag": etag})
            else:
                resp = Response(body, media_type="text/css; charset=utf-8", headers={"etag": etag})
        resp.headers["cache-control"] = IMMUTABLE if wanted == current else REVALIDATE
        return resp


def scope_header(scope, name: bytes) -> str:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin-1")
    return ""


class CacheHeaders:
    """Pages and API responses are per user: never cached by a browser or Cloudflare without revalidating."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith("/static/"):
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                h = list(message.get("headers", []))
                if not any(k.lower() == b"cache-control" for k, _ in h):
                    h.append((b"cache-control", DYNAMIC.encode()))
                message["headers"] = h
            await send(message)

        await self.app(scope, receive, send_wrapper)
