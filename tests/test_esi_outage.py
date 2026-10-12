"""ESI outages (#80), the error-limit back-off (#124) and small security/privacy hardening (#92).

ESI is faked with httpx.MockTransport that never answers; nothing reaches the network. Waiting is
replaced by a recorder (`client._sleep`), so back-off is checked without slowing the suite down."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet

import astracore.app  # noqa: F401  (import before asyncio.run: Python 3.9 module-level locks need a loop)
from astracore import config, db
from astracore.core import accounts, crypto
from astracore.esi import client as esi_client
from astracore.esi import errors as esi_errors
from astracore.esi import sso
from astracore.esi.client import BUDGET, ESIClient, ESIError, ESIUnavailable
from astracore.modules.pi import service, store
from astracore.modules.pi.intel import area as area_mod
from astracore.modules.pi.planner import prices
from astracore.modules.pi.settings import LIST_ITEM_MAX, LIST_MAX, TEXT_LIMITS, Settings
from astracore.modules.pi.static_data import voc

from test_core import PI_SCOPES, browser, csrf, eve, me, new_id, sso_login  # noqa: F401 (fixtures)
from test_planner import TEMPLATES, _colonies, pi  # noqa: F401 (fixture)

RAW = "upstream connect error <html>secret raw body</html>"


@pytest.fixture(autouse=True)
def fresh_budget(monkeypatch):
    """Every test starts with a healthy ESI budget and never really sleeps."""
    slept = []

    async def sleep(seconds):
        slept.append(round(seconds, 1))

    BUDGET.reset()
    monkeypatch.setattr(esi_client, "_sleep", sleep)
    yield slept
    BUDGET.reset()


def fake_esi(handler):
    """An ESIClient class whose requests go to `handler(request)` (may raise httpx errors)."""
    class Fake(ESIClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Fake


def unreachable(request):
    raise httpx.ConnectError(RAW, request=request)


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- client: back-off (#124)
def test_error_limit_pauses_every_caller(fresh_budget):
    events = []

    def handler(request):
        events.append(request.url.path)
        if len(events) == 1:
            return httpx.Response(420, json={"error": "error limited"},
                                  headers={"retry-after": "7", "x-esi-error-limit-remain": "0",
                                           "x-esi-error-limit-reset": "7"})
        return httpx.Response(200, json={"ok": True}, headers={"expires": "0"})

    async def go():
        async with fake_esi(handler)() as first, fake_esi(handler)() as second:
            r1 = await first._request("GET", "https://esi.test/a/")
            paused = BUDGET.pause_until - time.time()
            fresh_budget.clear()
            r2 = await second._request("GET", "https://esi.test/b/")     # another caller, same budget
            return r1, r2, paused

    r1, r2, paused = run(go())
    assert r1.status_code == r2.status_code == 200
    assert 5 < paused <= 7                         # the 420's Retry-After became the shared pause
    assert fresh_budget and 5 < fresh_budget[0] <= 7   # the second caller waited before asking ESI
    assert events == ["/a/", "/a/", "/b/"]


def test_low_error_limit_header_pauses_before_any_420(fresh_budget):
    def handler(request):
        return httpx.Response(404, json={"error": "not found"},
                              headers={"x-esi-error-limit-remain": "12", "x-esi-error-limit-reset": "30"})

    async def go():
        async with fake_esi(handler)() as esi:
            with pytest.raises(ESIError) as e:
                await esi.get("/universe/types/999999999/")
            return e.value

    err = run(go())
    assert err.status == 404 and not isinstance(err, ESIUnavailable)
    assert 25 < BUDGET.pause_until - time.time() <= 30


def test_one_route_answering_5xx_backs_off_but_never_stops_other_requests(fresh_budget):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if "broken" in request.url.path:
            return httpx.Response(503, text=RAW)
        return httpx.Response(200, json={"ok": True})

    async def go():
        async with fake_esi(handler)() as esi:
            with pytest.raises(ESIUnavailable) as first:
                await esi.get("/outage-test/broken/")
            n = len(calls)
            other = await esi.get("/outage-test/fine/")   # a flaky route doesn't take the site down
            return first.value, other, n

    first, other, n = run(go())
    assert n == esi_client.ATTEMPTS and first.kind == "server" and first.status == 503
    assert fresh_budget == [esi_client.backoff(i) for i in range(esi_client.ATTEMPTS - 1)] == [1, 3, 5, 7]
    assert other == {"ok": True} and len(calls) == n + 1
    assert RAW not in esi_errors.explain(first) and "trouble" in esi_errors.explain(first)


def test_esi_unreachable_makes_every_caller_fail_fast(fresh_budget):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        raise httpx.ConnectError("no route to host")

    async def go():
        async with fake_esi(handler)() as esi:
            with pytest.raises(ESIUnavailable) as first:
                await esi.get("/outage-test/down/")
            n = len(calls)
            with pytest.raises(ESIUnavailable) as second:
                await esi.get("/outage-test/next-caller/")
            return first.value, second.value, n

    first, second, n = run(go())
    assert n == esi_client.ATTEMPTS and first.kind == "unreachable"
    assert len(calls) == n                          # ESI is down: the next caller doesn't ask again
    assert second.kind == "unreachable" and BUDGET.outage() == "unreachable"


def test_error_limit_that_never_lifts_is_reported_plainly():
    def handler(request):
        return httpx.Response(420, headers={"retry-after": "1"})

    async def go():
        async with fake_esi(handler)() as esi:
            with pytest.raises(ESIUnavailable) as e:
                await esi.get("/outage-test/error-limit/")
            return e.value

    err = run(go())
    assert err.kind == "error_limit" and "slow down" in esi_errors.explain(err)
    assert BUDGET.down_until == 0                   # the error limit has its own pause, no extra lock-out


def test_timeouts_are_called_timeouts():
    def handler(request):
        raise httpx.ReadTimeout(RAW, request=request)

    async def go():
        async with fake_esi(handler)() as esi:
            with pytest.raises(ESIUnavailable) as e:
                await esi.post("/universe/names/", [1])
            return e.value

    err = run(go())
    assert err.kind == "timeout" and "too long" in esi_errors.explain(err)


def test_expired_public_copy_beats_an_error_but_private_data_never_does():
    cid = new_id()
    old = time.time() - 60
    with db.session() as c:
        for key in (f"{esi_client.ESI_BASE}/universe/systems/30099999/?",
                    f"{esi_client.ESI_BASE}/characters/{cid}/skills/?{esi_client.auth_suffix(cid)}"):
            c.execute("REPLACE INTO http_cache(url, body, etag, expires, esi_expires) VALUES(?,?,?,?,?)",
                      (key, '{"name": "Old copy"}', None, old, old))

    async def go():
        async with fake_esi(unreachable)() as esi:
            system = await esi.get("/universe/systems/30099999/", stale_ok=True)
            with pytest.raises(ESIUnavailable):
                await esi.get(f"/characters/{cid}/skills/", token="T", owner=cid, stale_ok=True)
            return system, dict(esi.stale)

    system, stale = run(go())
    assert system == {"name": "Old copy"} and "/universe/systems/30099999/" in stale


def test_trade_history_keeps_the_last_copy_when_esi_does_not_answer(monkeypatch, pi):  # noqa: F811
    saved = db.kv_get(prices.HISTORY_KEY)
    item = next(t for t in pi.items if pi.tier(t) >= 1)
    old = {"at": 1.0, "markets": {"jita": {str(item): {"avg_volume": 5.0, "days": 30}}}}
    db.kv_set(prices.HISTORY_KEY, old)

    async def down(esi, region_id, type_id):
        return None

    async def partly(esi, region_id, type_id):
        return None if type_id == item else []

    try:
        monkeypatch.setattr(prices.public, "region_history", down)
        with pytest.raises(ESIUnavailable):
            run(prices.refresh_history(None, pi))
        assert db.kv_get(prices.HISTORY_KEY) == old                     # untouched: retried later
        monkeypatch.setattr(prices.public, "region_history", partly)
        out = run(prices.refresh_history(None, pi))
        assert out["jita"][item]["avg_volume"] == 5.0                   # last summary, not "nothing traded"
    finally:
        db.kv_set(prices.HISTORY_KEY, saved)


# --------------------------------------------------------------------------- plain messages (#80)
@pytest.mark.parametrize("exc, words", [
    (ESIUnavailable(RAW, "timeout"), "too long"),
    (ESIUnavailable(RAW, "unreachable"), "couldn't be reached"),
    (ESIUnavailable(RAW, "server", 502), "daily downtime"),
    (ESIUnavailable(RAW, "error_limit", 420), "slow down"),
    (ESIError(f"403 /characters/1/assets/: {RAW}", 403), "grant the permissions"),
    (sso.NeedsLogin(RAW), "Log in with this character again"),
    (sso.Transferred(RAW), "transferred to another player"),
    (httpx.ConnectError(RAW), "didn't answer"),
    (RuntimeError(RAW), "has been logged"),
])
def test_every_known_failure_has_a_plain_message_with_a_next_step(exc, words):
    msg = esi_errors.explain(exc)
    assert words in msg and RAW not in msg and "secret" not in msg


def test_profile_refresh_never_shows_raw_exception_text(browser, eve, monkeypatch):
    from astracore.esi import character as esi_char
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Refresher")

    async def broken(esi, character_id):
        raise ESIError(f"502 /characters/{character_id}/skills/: {RAW}", 502)

    monkeypatch.setattr(esi_char, "sync_character", broken)
    r = c.post("/profile/refresh", data={"csrf_token": csrf(c)}, follow_redirects=False)
    msg = parse_qs(urlparse(r.headers["location"]).query)["msg"][0]
    assert "Refresher: EVE's API (ESI) is having trouble" in msg
    assert RAW not in msg and "502" not in msg and "/characters/" not in msg


# --------------------------------------------------------------------------- pages with ESI down (#80)
AREA_QUERY = "Outage Test Area"
AREA = {"query": AREA_QUERY, "found": [], "systems": {"30099001": {
    "system_id": 30099001, "name": "OUT-1", "security": -0.3, "constellation_id": 20099001,
    "constellation": "Outage Con", "region_id": 10099001, "region": "Outage Region",
    "sov_alliance_id": None, "sov_alliance": "", "neighbours": [], "exits": 0,
    "planets": [{"planet_id": 11, "name": "OUT-1 I", "type": "Barren", "type_id": 2016},
                {"planet_id": 12, "name": "OUT-1 II", "type": "Temperate", "type_id": 11}]}}}


@pytest.fixture()
def esi_down(monkeypatch, pi):  # noqa: F811
    """ESI never answers. Static data and the last area, prices and character data are stored."""
    monkeypatch.setattr(service, "ESIClient", fake_esi(unreachable))

    async def static():
        return pi, TEMPLATES

    async def no_routes():
        return []

    monkeypatch.setattr(service, "load_static", static)
    monkeypatch.setattr(voc, "refresh_routes", no_routes)          # VOC's site, not ESI
    monkeypatch.setattr(service, "refresh_history_soon", lambda pi: None)
    saved = {k: db.kv_get(k) for k in (prices.BOOKS_KEY, area_mod.AREA_KEY + AREA_QUERY.lower())}
    books_at = time.time() - 2 * 86400
    db.kv_set(prices.BOOKS_KEY, {"at": books_at, "failed": 0, "books": {}})
    db.kv_set(area_mod.AREA_KEY + AREA_QUERY.lower(), AREA)
    yield books_at
    for k, v in saved.items():
        db.kv_set(k, v)


def _pilot(c, eve, remember_area=True):  # noqa: F811
    cid = new_id()
    sso_login(c, eve, cid, "Outage Pilot")
    pid = me(c)
    db.save_token(cid, "rt", "at", 1199, PI_SCOPES)
    now = time.time()
    factory, miner = _colonies(now)
    for col, planet_type in ((factory, "temperate"), (miner, "barren")):
        col.update(solar_system_id=30099001, planet_type=planet_type)
    db.set_character(cid, colonies=[factory, miner], synced_at=now - 3 * 3600)
    s = store.load_settings(pid)
    s.selected_constellations = [20099001]
    store.save_settings(pid, s)
    if remember_area:
        db.kv_set(service._area_owner(service.planning_characters(pid), s), AREA_QUERY)
    return pid


def _shows_last_data(r):
    assert r.status_code == 200, r.text[-3000:]
    assert "data-esi-outage" in r.text and esi_errors.HEADLINE.replace("'", "&#39;") in r.text
    assert "Showing data from" in r.text and "Retry" in r.text
    assert "Something went wrong" not in r.text and "secret raw body" not in r.text


@pytest.mark.parametrize("path", ["/pi/area", "/pi/plan", "/pi/operate"])
def test_main_pages_show_last_known_data_when_esi_is_down(browser, eve, esi_down, path):
    c = browser()
    _pilot(c, eve)
    store.save_plan_run(me(c), "kept", store.load_settings(me(c)), {"totals": {}, "colonies": []}, active=True)
    r = c.get(path)
    _shows_last_data(r)
    assert "OUT-1" in r.text or path == "/pi/plan"
    if path != "/pi/area":
        assert "Showing data from 2 days ago" in r.text           # the order books it plans with


def test_page_without_any_stored_copy_explains_instead_of_crashing(browser, eve, esi_down):
    c = browser()
    _pilot(c, eve, remember_area=False)
    r = c.get("/pi/area")
    assert r.status_code == 503
    assert "couldn" in r.text and "Try again" in r.text and 'href="/pi/area"' in r.text
    assert "Something went wrong" not in r.text and "secret raw body" not in r.text


def test_dashboard_says_when_esi_is_down(browser, eve):
    c = browser()
    _pilot(c, eve, remember_area=False)
    assert "data-esi-outage" not in c.get("/").text
    BUDGET.trip("timeout")
    page = c.get("/").text
    assert "data-esi-outage" in page and "Showing data from 3 h ago" in page and "too long" in page
    BUDGET.last_ok = time.time() + 1                                 # ESI answered again
    assert "data-esi-outage" not in c.get("/").text


def test_prices_refresh_says_it_did_not_refresh(browser, eve, esi_down):
    c = browser()
    _pilot(c, eve)
    r = c.post("/pi/api/prices/refresh", json={}, headers={"X-CSRF-Token": csrf(c)})
    assert r.status_code == 503 and r.json()["ok"] is False
    assert "Prices weren't refreshed" in r.json()["error"]


# --------------------------------------------------------------------------- hardening (#92)
def test_free_text_settings_cannot_end_the_script_block(browser, eve, monkeypatch):
    c = browser()
    sso_login(c, eve, new_id(), "Scripter")
    s = Settings(extra_area="</script><script>alert(1)</script>")

    async def context(pid, *a, **kw):
        return {"s": s, "chars": [], "systems": {}, "area": {}, "calibrated": False, "head_yield": 1500,
                "dropoff": None, "seller": None}

    monkeypatch.setattr(service, "planning_context", context)
    for path in ("/pi/plan", "/pi/plan?view=advanced"):
        html = c.get(path).text
        assert "</script><script>alert(1)" not in html
        assert "\\u003c/script\\u003e" in html


def test_free_text_settings_have_server_side_limits():
    s = Settings()
    s.update({"extra_area": "x" * 5000, "hub_system": "y" * 5000, "product_blacklist": ["z" * 500] * 1000,
              "answered": ",".join(["q"] * 1000)})
    assert len(s.extra_area) == TEXT_LIMITS["extra_area"] and len(s.hub_system) == TEXT_LIMITS["hub_system"]
    assert len(s.product_blacklist) == LIST_MAX and all(len(x) == LIST_ITEM_MAX for x in s.product_blacklist)
    assert len(s.answered) == LIST_MAX


def test_area_form_limits_free_text(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Long Area")
    c.post("/pi/area", data={"csrf_token": csrf(c), "hub_system": "h" * 999, "con": "1"})
    assert len(store.load_settings(me(c)).hub_system) == TEXT_LIMITS["hub_system"]


def test_data_export_includes_feedback_reports(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Reporter")
    now = time.time()
    with db.session() as conn:
        conn.execute("INSERT INTO community_feedback(id,profile_id,submission_key,kind,title,body,version,created_at,"
                     "updated_at,delivery,issue_number) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (f"fb-{me(c)}", me(c), "k1", "idea", "Shiny idea", "More planets", "0.1.0", now, now,
                      "published", 42))
    export = c.get("/profile/export.json").json()
    assert [(f["title"], f["delivery"], f["issue_number"]) for f in export["feedback"]] == \
        [("Shiny idea", "published", 42)]
    assert accounts.export_profile(me(c))["feedback"][0]["body"] == "More planets"


def test_reset_says_when_eve_did_not_confirm_revocation(browser, eve, monkeypatch):
    c = browser()
    sso_login(c, eve, new_id(), "Unrevoked")

    async def not_confirmed(rt):
        return False

    monkeypatch.setattr(sso, "revoke", not_confirmed)
    r = c.post("/profile/reset", data={"csrf_token": csrf(c), "confirm": "Unrevoked"}, follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert "didn't confirm that it revoked the EVE login" in q["msg"][0]
    assert sso.AUTHORIZED_APPS_URL in q["msg"][0] and q["kind"] == ["warn"]


def test_reset_confirms_when_eve_revoked_everything(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Revoked")
    r = c.post("/profile/reset", data={"csrf_token": csrf(c), "confirm": "Revoked"}, follow_redirects=False)
    assert "EVE confirmed every login is revoked" in parse_qs(urlparse(r.headers["location"]).query)["msg"][0]


def test_privacy_page_says_published_feedback_stays_on_github(browser):
    html = browser().get("/privacy").text
    assert "Published feedback stays on GitHub after you reset your profile" in html
    assert sso.AUTHORIZED_APPS_URL in html


def test_token_key_rotation_with_multifernet(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    cid = new_id()
    pid = db.create_profile("Rotator")
    db.link_character(cid, pid, "Rotator")
    try:
        monkeypatch.setitem(config._ENV, "ASTRACORE_TOKEN_KEY", old)
        crypto._fernet.cache_clear()
        db.save_token(cid, "refresh-secret", "access-secret", 1199, "x")
        assert not crypto.rotating()

        monkeypatch.setitem(config._ENV, "ASTRACORE_TOKEN_KEY", f" {new} , {old} ")
        crypto._fernet.cache_clear()
        assert crypto.rotating() and db.get_token(cid)["refresh_token"] == "refresh-secret"   # old key reads
        assert Fernet(new.encode()).decrypt(crypto.encrypt("x").encode()) == b"x"            # first key writes
        assert db.reencrypt_tokens() >= 1

        monkeypatch.setitem(config._ENV, "ASTRACORE_TOKEN_KEY", new)                        # old key dropped
        crypto._fernet.cache_clear()
        assert db.get_token(cid)["access_token"] == "access-secret"
    finally:
        db.delete_profile(pid)
        crypto._fernet.cache_clear()
