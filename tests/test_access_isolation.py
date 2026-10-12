import asyncio
import json
import time

import httpx
import pytest

from astracore import db
from astracore.core import accounts
from astracore.esi import character
from astracore.esi.client import ESI_BASE, ESIClient, ESIError
from astracore.modules.pi import store
from astracore.modules.pi.settings import Settings
from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401
from test_planner import BOOKS, pi  # noqa: F401


@pytest.mark.parametrize("added_after_choice", [False, True])
def test_merge_only_moves_the_authenticated_character_from_a_multi_character_profile(browser, eve, added_after_choice):
    source, destination = browser(), browser()
    claimed, other = new_id(), new_id()
    sso_login(source, eve, claimed, "Claimed")
    src = me(source)
    store.save_plan_run(src, "Source plan", Settings(), {"totals": {}})
    if not added_after_choice:
        sso_login(source, eve, other, "Other", path="/auth/login?intent=add")
    sso_login(destination, eve, new_id(), "Destination")
    dst = me(destination)
    sso_login(destination, eve, claimed, "Claimed", path="/auth/login?intent=add")
    destination.get("/auth/choose")
    if added_after_choice:
        sso_login(source, eve, other, "Other", path="/auth/login?intent=add")
    other_token = db.get_token(other)["refresh_token"]

    response = destination.post("/auth/choose", data={"action": "merge", "csrf_token": csrf(destination)})

    assert response.status_code == 200
    assert db.character_profile(claimed) == dst
    assert db.character_profile(other) == src
    assert db.get_token(other)["refresh_token"] == other_token
    assert me(source) == src
    assert [p["label"] for p in store.list_plan_runs(src)] == ["Source plan"]
    assert store.list_plan_runs(dst) == []


def test_merge_requires_the_source_profiles_current_sole_character():
    src, dst = db.create_profile("Source"), db.create_profile("Destination")
    cid = new_id()
    db.link_character(cid, src, "Sole character")
    try:
        assert accounts.merge_profiles(src, dst, cid + 1) is False
        assert db.character_profile(cid) == src
        assert db.get_profile(src)
    finally:
        db.delete_profile(src)
        db.delete_profile(dst)


def cached(key, data):
    with db.session() as c:
        c.execute("REPLACE INTO http_cache(url,body,etag,expires) VALUES(?,?,?,?)",
                  (key, json.dumps(data), '"old-etag"', time.time() + 86400))


def test_authenticated_requests_ignore_legacy_shared_cache_and_never_share_a_copy():
    path = "/corporations/900001/customs_offices/"
    cached(ESI_BASE + path + "?#auth", [{"office_id": 1}])      # an old shared copy is never served
    calls = []

    def transport(request):
        calls.append(request)
        if request.headers["authorization"] == "Bearer synthetic-director":
            return httpx.Response(200, json=[{"office_id": 2}], headers={"expires": "Fri, 01 Jan 2100 00:00:00 GMT"})
        return httpx.Response(403, json={"error": "Forbidden"})

    async def run():
        async with ESIClient() as esi:
            await esi._client.aclose()
            esi._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
            assert await esi.get(path, token="synthetic-director", owner=900001, ttl=86400) == [{"office_id": 2}]
            with pytest.raises(ESIError, match="403"):       # another character asks ESI itself
                await esi.get(path, token="synthetic-member", owner=900002, ttl=86400)
            # the director's own fresh copy is reused until ESI's expiry (no early re-fetch)
            assert await esi.get(path, token="synthetic-director", owner=900001, ttl=86400) == [{"office_id": 2}]

    asyncio.run(run())
    assert len(calls) == 2


def test_public_requests_still_cache_and_revalidate():
    path = "/universe/stations/60000001/"
    key = ESI_BASE + path + "?"
    calls = []

    def transport(request):
        calls.append(request)
        if request.headers.get("if-none-match"):
            return httpx.Response(304, headers={"etag": '"public-etag"'})
        return httpx.Response(200, json={"name": "Public station"}, headers={"etag": '"public-etag"'})

    async def run():
        async with ESIClient() as esi:
            await esi._client.aclose()
            esi._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
            assert await esi.get(path, ttl=3600) == {"name": "Public station"}
            assert await esi.get(path, ttl=3600) == {"name": "Public station"}
            with db.session() as c:
                c.execute("UPDATE http_cache SET expires=0 WHERE url=?", (key,))
            assert await esi.get(path, ttl=3600) == {"name": "Public station"}

    with db.session() as c:
        c.execute("DELETE FROM http_cache WHERE url=?", (key,))
    asyncio.run(run())
    assert len(calls) == 2
    assert calls[1].headers["if-none-match"] == '"public-etag"'


def test_structure_locations_are_resolved_for_each_character_without_shared_names(monkeypatch):
    lid = 1_000_000_000_001
    db.kv_set(character.LOCATIONS_KEY, {str(lid): {"name": "Legacy private name", "system_id": 30000001}})

    async def names(esi, ids):
        return {30000001: "Synthetic system"}

    monkeypatch.setattr(character.public, "ids_to_names", names)
    calls = []

    class ESI:
        cache_waits = {}
        async def get(self, path, **options):
            calls.append(options["token"])
            if options["token"] == "allowed":
                return {"name": "Private structure", "solar_system_id": 30000001}
            raise ESIError("403 Forbidden")

    allowed = asyncio.run(character.resolve_locations(ESI(), "allowed", [lid], 900001))
    denied = asyncio.run(character.resolve_locations(ESI(), "denied", [lid], 900002))
    assert allowed[lid]["name"] == "Private structure"
    assert denied[lid]["unknown"]
    assert calls == ["allowed", "denied"]
    assert lid not in character.locations()
    assert str(lid) not in (db.kv_get(character.LOCATIONS_KEY) or {})


def test_legacy_cleanup_removes_private_cache_and_only_resets_customs_once():
    src = db.create_profile("Cleanup")
    cid = new_id()
    db.link_character(cid, src, "Cleanup character")
    db.set_character(cid, customs_offices=[{"office_id": 1}])
    public_key = ESI_BASE + "/universe/stations/60000002/?"
    private_key = ESI_BASE + "/corporations/900001/customs_offices/?#auth"
    cached(public_key, {"name": "Public station"})
    cached(private_key, [{"office_id": 1}])
    db.kv_set(character.LOCATIONS_KEY, {
        "60000002": {"name": "Public station"},
        "1000000000001": {"name": "Private structure"},
    })
    with db.session() as c:
        c.execute("DELETE FROM kv WHERE key=?", (character.PRIVATE_CACHE_CLEANUP,))
    try:
        character.clear_legacy_private_cache()
        with db.session() as c:
            assert c.execute("SELECT body FROM http_cache WHERE url=?", (public_key,)).fetchone()
            assert c.execute("SELECT body FROM http_cache WHERE url=?", (private_key,)).fetchone() is None
        assert set(db.kv_get(character.LOCATIONS_KEY)) == {"60000002"}
        assert db.get_character(cid)["customs_offices"] == []

        db.set_character(cid, customs_offices=[{"office_id": 2}])
        character.clear_legacy_private_cache()
        assert db.get_character(cid)["customs_offices"] == [{"office_id": 2}]
    finally:
        db.delete_profile(src)


def test_sync_keeps_private_locations_with_the_character_and_clears_denied_customs(monkeypatch, pi):
    from astracore.modules.pi.planner import operate
    from test_core import CUSTOMS, PI_SCOPES

    pid, cid = db.create_profile("Location owner"), new_id()
    lid = 1_000_000_000_001
    db.link_character(cid, pid, "Location character")
    db.save_token(cid, "synthetic-refresh", "synthetic-access", 1199, PI_SCOPES + " " + CUSTOMS)
    db.set_character(cid, customs_offices=[{"office_id": 1}])

    async def token(character_id):
        return "synthetic-access"

    async def affiliation(esi, character_id):
        return {"corporation_id": 900001}

    async def names(esi, ids):
        return {30000001: "Synthetic system"}

    monkeypatch.setattr(character.sso, "access_token", token)
    monkeypatch.setattr(character, "affiliation", affiliation)
    monkeypatch.setattr(character.public, "ids_to_names", names)
    monkeypatch.setattr(character.sde_loader, "cached", lambda: pi)

    class ESI:
        cache_waits = {}
        async def get(self, path, **options):
            if path.endswith("/skills/"):
                return {"skills": []}
            if path.endswith("/assets/"):
                return [{"item_id": 1, "type_id": 2329, "quantity": 10, "location_id": lid,
                         "location_flag": "Hangar", "location_type": "station"}]
            if path.endswith("/contracts/"):
                return [{"contract_id": 1, "type": "item_exchange", "status": "outstanding",
                         "start_location_id": lid, "end_location_id": lid}]
            if path.endswith("/items/"):
                return [{"type_id": 2329, "quantity": 5}]
            if path.endswith("/orders/"):
                return [{"order_id": 1, "type_id": 2329, "location_id": lid, "price": 100,
                         "volume_remain": 10, "volume_total": 10}]
            if "/universe/structures/" in path:
                return {"name": "Private structure", "solar_system_id": 30000001}
            if path.endswith("/wallet/"):
                return None
            if path.endswith("/customs_offices/"):
                raise ESIError("403 Forbidden")
            return []

    try:
        asyncio.run(character.sync_character(ESI(), cid))
        own = db.get_character(cid)
        assert own["customs_offices"] == []
        assert own["assets"][0]["location"]["name"] == "Private structure"
        assert own["contracts"][0]["start_location"]["name"] == "Private structure"
        assert own["orders"][0]["location"]["name"] == "Private structure"
        assert lid not in character.locations()

        other = {"name": "Other character", "assets": [{"type_id": 2329, "qty": 10, "location_id": lid}]}
        assert operate.hangar_stock(pi, Settings(), BOOKS, [own])[0]["location"] == "Private structure"
        assert operate.hangar_stock(pi, Settings(), BOOKS, [other])[0]["unknown_location"]
        assert operate.pipeline(pi, BOOKS, [own])["other"][0]["from"] == "Private structure"
        assert operate.pipeline(pi, BOOKS, [own])["orders"][0]["location"] == "Private structure"
    finally:
        db.delete_profile(pid)
