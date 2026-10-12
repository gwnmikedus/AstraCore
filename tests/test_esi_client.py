"""ESI hygiene: honour ESI's cache on refresh, revalidate with ETags, identify ourselves (issue #70).

ESI is faked with httpx.MockTransport; nothing reaches the network."""
from __future__ import annotations

import asyncio
import email.utils
import time

import httpx

from astracore import config, db
from astracore.core import releases
from astracore.esi import character as esi_char
from astracore.esi.client import COMPATIBILITY_DATE, ESIClient


def http_date(ts: float) -> str:
    return email.utils.formatdate(ts, usegmt=True)


def run(handler, steps):
    """Run `steps(esi)` against a fake ESI; returns (result, requests seen)."""
    seen = []

    def api(request):
        seen.append(request)
        return handler(request)

    async def go():
        async with ESIClient() as esi:
            await esi._client.aclose()
            esi._client = httpx.AsyncClient(transport=httpx.MockTransport(api))
            return await steps(esi)

    return asyncio.run(go()), seen


def test_authenticated_refresh_rechecks_permissions_without_using_a_cached_copy():
    cid = 93_000_001

    def handler(request):
        return httpx.Response(200, json=[{"planet_id": 1}], headers={"expires": http_date(time.time() + 600),
                                                                      "etag": '"v1"'})

    async def steps(esi):
        first = await esi.get(f"/characters/{cid}/planets/", token="T", owner=cid)
        again = await esi.get(f"/characters/{cid}/planets/", token="T", owner=cid, force=True)
        return first, again, esi_char.esi_waits(esi, cid)

    (first, again, waits), seen = run(handler, steps)
    assert first == again == [{"planet_id": 1}]
    assert len(seen) == 2
    assert waits == {}
    assert all("if-none-match" not in request.headers for request in seen)


def test_force_skips_our_ttl_but_not_esis_expiry():
    path = "/markets/prices/"
    db_key = "https://esi.evetech.net/latest/markets/prices/?"

    def handler(request):
        if request.headers.get("if-none-match") == '"p1"':
            return httpx.Response(304, headers={"expires": http_date(time.time() + 3600), "etag": '"p1"'})
        return httpx.Response(200, json=[{"type_id": 34}], headers={"expires": http_date(time.time() + 3600),
                                                                     "etag": '"p1"'})

    async def first(esi):
        return await esi.get(path, ttl=3600)

    _, seen = run(handler, first)
    assert len(seen) == 1
    _, seen = run(handler, lambda esi: esi.get(path, ttl=3600, force=True))
    assert seen == []                                        # ESI's expiry hasn't passed: no request

    # ESI's copy expired, our own (longer) ttl hasn't: a forced refresh revalidates with the ETag
    with db.session() as c:
        c.execute("UPDATE http_cache SET esi_expires=? WHERE url=?", (time.time() - 1, db_key))
    body, seen = run(handler, lambda esi: esi.get(path, ttl=3600, force=True))
    assert body == [{"type_id": 34}]
    assert len(seen) == 1 and seen[0].headers["if-none-match"] == '"p1"'
    with db.session() as c:
        row = c.execute("SELECT * FROM http_cache WHERE url=?", (db_key,)).fetchone()
    assert row["esi_expires"] > time.time() + 3000 and row["etag"] == '"p1"'


def test_expired_copy_is_revalidated_with_if_none_match():
    path = "/universe/systems/30000001/"

    def handler(request):
        if request.headers.get("if-none-match") == '"s1"':
            return httpx.Response(304, headers={"expires": http_date(time.time() + 120)})
        return httpx.Response(200, json={"name": "Synthetic system"}, headers={"expires": http_date(time.time() - 5),
                                                                  "etag": '"s1"'})

    async def steps(esi):
        first = await esi.get(path)
        again = await esi.get(path)
        return first, again

    (first, again), seen = run(handler, steps)
    assert first == again == {"name": "Synthetic system"}
    assert len(seen) == 2 and "if-none-match" not in seen[0].headers
    assert seen[1].headers["if-none-match"] == '"s1"'


def test_requests_carry_user_agent_and_compatibility_date(monkeypatch):
    monkeypatch.setitem(config._ENV, "ASTRACORE_CONTACT", "ops@example.invalid")
    releases.user_agent.cache_clear()
    try:
        def handler(request):
            return httpx.Response(200, json={"ok": True}, headers={"expires": http_date(time.time() + 60)})

        _, seen = run(handler, lambda esi: esi.get("/status-test/", ttl=60))
        version = releases.current()["version"]
        assert seen[0].headers["user-agent"] == \
            f"AstraCore/{version} (+https://astracore.hoppyhome.nl; ops@example.invalid)"
        assert seen[0].headers["x-compatibility-date"] == COMPATIBILITY_DATE
        _, seen = run(handler, lambda esi: esi.post("/universe/names-test/", [1], ttl=60))
        assert seen[0].headers["x-compatibility-date"] == COMPATIBILITY_DATE
    finally:
        releases.user_agent.cache_clear()


def test_user_agent_without_contact(monkeypatch):
    monkeypatch.setitem(config._ENV, "ASTRACORE_CONTACT", "")
    releases.user_agent.cache_clear()
    try:
        assert releases.user_agent() == f"AstraCore/{releases.current()['version']} (+https://astracore.hoppyhome.nl)"
    finally:
        releases.user_agent.cache_clear()


def test_wait_note_names_what_esi_has_not_updated():
    assert esi_char.wait_note({}) == ""
    assert esi_char.wait_note({"wallet": 30}) == "Wallet is unchanged until EVE updates it (in up to 1 min)."
    assert esi_char.wait_note({"wallet": 90, "colonies": 400}) == \
        "Colonies and wallet are unchanged until EVE updates them (in up to 7 min)."
