"""Async ESI client with sqlite caching, pagination and error-limit handling."""
from __future__ import annotations

import asyncio
import email.utils
import json
import time
from typing import Any, Dict, List, Optional

import httpx

from astracore import db
from astracore.core.releases import user_agent

ESI_BASE = "https://esi.evetech.net/latest"
# ESI serves every route in the version of the compatibility date a request names; a request without one
# gets the *oldest* date. We pin it so an ESI upgrade is a deliberate, tested change here and never a
# surprise. 2020-01-01 is what `/latest` without the header has always given us, so this keeps today's
# response shapes. Raise it (to a date from https://esi.evetech.net/meta/compatibility-dates) after
# checking the routes we read against the ESI changelog.
COMPATIBILITY_DATE = "2020-01-01"

# Static universe data rarely changes; keep it for a month regardless of headers.
STATIC_TTL = 30 * 24 * 3600


class ESIError(RuntimeError):
    pass


def auth_suffix(character_id: int) -> str:
    """Cache-key suffix for a character's authenticated responses (see db.forget_character_cache)."""
    return f"#auth:{int(character_id)}"


def _esi_expires(resp: httpx.Response) -> float:
    """When ESI itself has new data: its `Expires` header. Asking again before then only returns the
    same cached copy, and ESI's best practices treat it as circumventing the cache."""
    exp = resp.headers.get("expires")
    if exp:
        try:
            return email.utils.parsedate_to_datetime(exp).timestamp()
        except (TypeError, ValueError):
            pass
    return time.time() + 300


def _expires(resp: httpx.Response, ttl: Optional[int]) -> float:
    """When we ask again: after our own `ttl` if we keep a response longer, never before ESI's expiry."""
    esi = _esi_expires(resp)
    return esi if ttl is None else max(esi, time.time() + ttl)


class _Budget:
    """One ESI budget for the whole process: every user shares this machine's IP, so the error limit,
    the rate limits and the number of requests in flight are tracked globally, not per client."""

    MAX_IN_FLIGHT = 20

    def __init__(self) -> None:
        self.pause_until = 0.0
        self._sems: Dict[int, asyncio.Semaphore] = {}

    def sem(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        key = id(loop)
        if key not in self._sems:
            self._sems = {key: asyncio.Semaphore(self.MAX_IN_FLIGHT)}   # one loop in practice
        return self._sems[key]

    def observe(self, resp: httpx.Response) -> None:
        h = resp.headers
        remain = h.get("x-esi-error-limit-remain")
        if remain is not None and remain.isdigit() and int(remain) < 20:
            reset = h.get("x-esi-error-limit-reset", "10")
            self.pause_until = max(self.pause_until, time.time() + (int(reset) if reset.isdigit() else 10))
        rl_remain = h.get("x-ratelimit-remaining")
        if rl_remain is not None and rl_remain.isdigit() and int(rl_remain) < 5:
            self.pause_until = max(self.pause_until, time.time() + 5)
        if resp.status_code in (420, 429):
            try:
                retry = float(h.get("retry-after", "10"))
            except ValueError:
                retry = 10.0
            self.pause_until = max(self.pause_until, time.time() + min(retry, 120))


BUDGET = _Budget()


def default_headers() -> Dict[str, str]:
    return {"User-Agent": user_agent(), "Accept": "application/json",
            "X-Compatibility-Date": COMPATIBILITY_DATE}


class ESIClient:
    def __init__(self, concurrency: int = 20) -> None:
        self._client = httpx.AsyncClient(timeout=30)
        # path -> ESI expiry, for responses served from cache because ESI has nothing newer yet
        self.cache_waits: Dict[str, float] = {}

    async def __aenter__(self) -> "ESIClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, *, params: Optional[dict] = None,
                       json_body: Any = None, token: Optional[str] = None,
                       etag: Optional[str] = None) -> httpx.Response:
        headers = default_headers()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if etag:
            headers["If-None-Match"] = etag
        for attempt in range(5):
            wait = BUDGET.pause_until - time.time()
            if wait > 0:
                await asyncio.sleep(min(wait, 120))
            async with BUDGET.sem():
                try:
                    resp = await self._client.request(method, url, params=params,
                                                      json=json_body, headers=headers)
                except httpx.TransportError:
                    await asyncio.sleep(1 + attempt * 2)
                    continue
            BUDGET.observe(resp)
            if resp.status_code in (420, 429):
                continue          # observe() set the global pause
            if resp.status_code in (500, 502, 503, 504):
                await asyncio.sleep(1 + attempt * 2)
                continue
            return resp
        raise ESIError(f"ESI request kept failing: {method} {url}")

    async def get(self, path: str, *, params: Optional[dict] = None, token: Optional[str] = None,
                  owner: Optional[int] = None, ttl: Optional[int] = None, force: bool = False) -> Any:
        """GET with cache. Returns parsed JSON. Follows X-Pages pagination.
        Authenticated calls name the character whose token they use (`owner`): their cached copy belongs to
        that character only, is never served to another one and is deleted with the character.

        A cached copy is used until it expires, then revalidated with its ETag (If-None-Match).
        `force` skips our own longer `ttl`, never ESI's `Expires`: before that ESI has nothing newer."""
        url = f"{ESI_BASE}{path}"
        params = dict(params or {})
        cache_key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if token:
            if not owner:
                raise ValueError("An authenticated ESI call needs the character it is made for.")
            cache_key += auth_suffix(owner)
        with db.session() as c:
            row = c.execute("SELECT * FROM http_cache WHERE url=?", (cache_key,)).fetchone()
        if row:
            now = time.time()
            esi_until = row["esi_expires"] if row["esi_expires"] is not None else (0 if force else row["expires"])
            if (esi_until if force else row["expires"]) > now:
                if esi_until > now:
                    self.cache_waits[path] = esi_until
                return json.loads(row["body"])

        resp = await self._request("GET", url, params=params, token=token, etag=row["etag"] if row else None)
        if resp.status_code == 304 and row:
            body = row["body"]
        elif resp.status_code == 404:
            raise ESIError(f"404 {path}")
        elif resp.status_code >= 400:
            raise ESIError(f"{resp.status_code} {path}: {resp.text[:200]}")
        else:
            data = resp.json()
            pages = int(resp.headers.get("x-pages", "1"))
            if pages > 1 and isinstance(data, list):
                rest = await asyncio.gather(*[
                    self._request("GET", url, params={**params, "page": p}, token=token)
                    for p in range(2, pages + 1)
                ])
                for r in rest:
                    if r.status_code == 200:
                        data.extend(r.json())
            body = json.dumps(data)
        with db.session() as c:
            c.execute(
                "REPLACE INTO http_cache(url, body, etag, expires, esi_expires) VALUES(?,?,?,?,?)",
                (cache_key, body, resp.headers.get("etag") or (row["etag"] if resp.status_code == 304 else None),
                 _expires(resp, ttl), _esi_expires(resp)),
            )
        return json.loads(body)

    async def post(self, path: str, body: Any, ttl: Optional[int] = None) -> Any:
        """POST (e.g. /universe/ids/, /universe/names/), cached by body."""
        url = f"{ESI_BASE}{path}"
        cache_key = url + "#" + json.dumps(body, sort_keys=True)
        with db.session() as c:
            row = c.execute("SELECT * FROM http_cache WHERE url=?", (cache_key,)).fetchone()
        if row and row["expires"] > time.time():
            return json.loads(row["body"])
        resp = await self._request("POST", url, json_body=body)
        if resp.status_code >= 400:
            raise ESIError(f"{resp.status_code} {path}: {resp.text[:200]}")
        data = resp.json()
        with db.session() as c:
            c.execute("REPLACE INTO http_cache(url, body, etag, expires, esi_expires) VALUES(?,?,?,?,?)",
                      (cache_key, json.dumps(data), None, _expires(resp, ttl), _esi_expires(resp)))
        return data

    async def gather_get(self, paths: List[str], ttl: Optional[int] = None) -> Dict[str, Any]:
        results = await asyncio.gather(*[self.get(p, ttl=ttl) for p in paths], return_exceptions=True)
        return {p: r for p, r in zip(paths, results) if not isinstance(r, Exception)}
