"""Next up on Operate (#90), Home as a launcher (#109) and refresh on visit (#75).

Synthetic characters, colonies and plans only; ESI is never called (refreshes are faked).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from astracore import db
from astracore.core import freshness
from astracore.modules.pi import service, store
from astracore.modules.pi.planner import nextup, upkeep
from astracore.modules.pi.settings import Settings

from test_core import PI_SCOPES, browser, csrf, eve, me, new_id, sso_login  # noqa: F401 (fixtures)
from test_planner import _colonies, pi  # noqa: F401 (fixture)

NOW = time.time()   # fmt.ago reads the clock


def _row(character, planet, system, **kw):
    base = {"character": character, "planet": planet, "system": system, "restart_hours": None,
            "collect_hours": None, "value_per_day": 0, "route_issues": 0}
    base.update(kw)
    return base


def _upkeep(colonies=(), shortages=(), freshness_=(), ship=None, tracks=None):
    t = {"restart": {"next_hours": None}, "restock": {"next_hours": None}, "collect": {"next_hours": None},
         "ship": ship or {"due": False}}
    t.update(tracks or {})
    return {"colonies": list(colonies), "shortages": list(shortages), "tracks": t,
            "freshness": list(freshness_) or [{"character": "Ann", "synced_at": NOW - 60, "colony_update": NOW - 3600}]}


def test_next_up_puts_stale_data_first_then_colonies_by_deadline_then_market_then_plan():
    up = _upkeep(
        colonies=[
            _row("Ann", "Alpha I", "7G-QIG", restart_hours=-2, value_per_day=5e6),     # stopped
            _row("Ann", "Alpha II", "7G-QIG", restart_hours=6, value_per_day=1e6),     # same system: grouped
            _row("Bob", "Beta I", "UEJX-G", restart_hours=30),                         # not within 24 h
            _row("Bob", "Beta II", "UEJX-G", collect_hours=10),
            _row("Bob", "Beta III", "UEJX-G", route_issues=2),
        ],
        shortages=[{"character": "Bob", "planet": "Beta IV", "system": "UEJX-G", "item": "Biofuels",
                    "have": 0, "days_left": 0.0, "value_per_day": 9e6},
                   {"character": "Ann", "planet": "Alpha III", "system": "7G-QIG", "item": "Biofuels",
                    "have": 50, "days_left": 1.5, "value_per_day": 0}],
        freshness_=[{"character": "Ann", "synced_at": NOW - 60, "colony_update": NOW - 100 * 3600},
                    {"character": "Bob", "synced_at": NOW - 80 * 3600, "colony_update": NOW - 80 * 3600}],
        ship={"due": True})
    stock = [{"character": "Ann", "location": "Keepstar", "system": "7G-QIG", "jita_value": 6e8},
             {"character": "Bob", "location": "Fortizar", "system": "UEJX-G", "jita_value": 5e7}]
    pipe = {"orders": [{"character": "Ann", "location": "Jita IV", "undercut": True, "value": 1e7},
                       {"character": "Ann", "location": "Jita IV", "undercut": True, "value": 2e7},
                       {"character": "Ann", "location": "Jita IV", "undercut": False, "value": 9e9}]}
    progress = {"done": 3, "total": 10, "new": 5, "rebuild": 2, "removals": 1, "todo": 7}
    items = nextup.next_up(up, stock=stock, consolidated={"total_value": 6.508e8, "advice": [{"label": "VOC buyback"}]},
                           pipe=pipe, plan={"totals": {}}, progress=progress, drift={"summary": "1 colony differs"},
                           now=NOW)
    kinds = [i["kind"] for i in items]
    assert kinds == ["refresh", "view", "restart", "restock", "collect", "restock", "ship", "undercut",
                     "build", "rebuild", "remove", "replan", "routes"]
    refresh, view, restart = items[0], items[1], items[2]
    assert (refresh["character"], refresh["when"]) == ("Bob", "updated 3 days ago")
    assert view["character"] == "Ann" and view["when"].startswith("colony data")
    # two colonies in one system make one line with the earliest deadline and their ISK together
    assert (restart["where"], restart["system"], restart["character"], restart["when"], restart["level"]) == \
        ("2 planets", "7G-QIG", "Ann", "stopped", "bad")
    assert restart["isk"] == 6e6 and restart["href"] == "#extractors"
    assert (items[3]["where"], items[3]["when"]) == ("Beta IV", "idle now")
    assert items[4]["when"] == "full in 10.0 h" and items[4]["href"] == "#pickups"
    assert items[5]["when"] == "runs out in 36.0 h"
    ship = items[6]
    assert ship["verb"] == "Sell 650.8M in hangars · VOC buyback" and ship["where"] == "Keepstar + 1 more"
    assert ship["character"] == "2 characters" and ship["when"] == "shipment due"
    assert items[7]["verb"] == "Update 2 undercut sell orders" and items[7]["isk"] == 3e7
    assert items[8]["verb"] == "Build 5 new colonies" and items[8]["when"] == "3 of 10 built"
    assert items[12]["where"] == "Beta III" and items[12]["when"] == "2 structure issues"


def test_ties_in_a_group_go_to_the_colonies_with_more_isk_at_stake():
    up = _upkeep(colonies=[_row("Ann", "Small", "A", restart_hours=-1, value_per_day=1e6),
                           _row("Bob", "Big", "B", restart_hours=-5, value_per_day=8e6)])
    items = nextup.next_up(up, now=NOW)
    assert [i["where"] for i in items] == ["Big", "Small"]   # both stopped: same urgency, ISK decides


def test_hangar_stock_waits_for_the_shipment_unless_it_is_worth_a_trip():
    up = _upkeep(ship={"due": False})
    small = [{"character": "Ann", "location": "Keepstar", "system": "X", "jita_value": 4e8}]
    assert nextup.next_up(up, stock=small, now=NOW) == []
    big = [{**small[0], "jita_value": 9e8}]
    [item] = nextup.next_up(up, stock=big, now=NOW)
    assert item["kind"] == "ship" and item["hours"] is None and item["character"] == "Ann"


def test_recalculate_replaces_update_plan_and_a_calm_list_says_when_to_come_back():
    items = nextup.next_up(_upkeep(), plan={"totals": {"needs_recalculation": True}}, drift={"summary": "x"}, now=NOW)
    assert [i["kind"] for i in items] == ["recalculate"]
    calm = _upkeep(tracks={"restart": {"next_hours": 50.0}, "collect": {"next_hours": 30.0}})
    assert nextup.next_up(calm, now=NOW) == []
    assert nextup.all_clear(calm) == "Next pickup before storage fills in 30.0 h."
    assert nextup.all_clear(_upkeep()) is None


def test_next_up_from_a_real_upkeep_schedule(pi):
    now = time.time()
    factory, miner = _colonies(now)
    ch = {"character_id": 1, "name": "Test Pilot", "synced_at": now - 60, "colonies": [factory, miner]}
    up = upkeep.schedule(pi, Settings(), [ch], None, now=now)
    items = nextup.next_up(up, now=now)
    assert items[0]["kind"] == "view"          # the miner wasn't opened in game for 4 days
    assert "restock" in [i["kind"] for i in items]
    assert all(i["character"] == "Test Pilot" for i in items)


# --------------------------------------------------------------------------- Home (#109)
def _pilot(c, eve, name, colonies=()):
    cid = new_id()
    sso_login(c, eve, cid, name)
    pid = me(c)
    db.save_token(cid, "rt", "at", 1199, PI_SCOPES)
    db.set_character(cid, status="ok", colonies=list(colonies), synced_at=time.time(), ccu_level=4)
    s = Settings()
    s.selected_constellations = [1]
    store.save_settings(pid, s)
    db.update_profile(pid, onboarded=1)
    return cid, pid


def _plan(pid, cid):
    store.save_plan_run(pid, "home", Settings(), {"totals": {"isk_per_day": 7_300_000}, "colonies": [
        {"character_id": cid, "planet_id": 12, "character": "x", "planet": "P12", "product": "Biocells",
         "kind": "factory", "action": "new", "value_per_day": 1e6,
         "in_per_day": {"Biofuels": 1920, "Precious Metals": 1920}, "out_per_day": {"Biocells": 480}},
        {"character_id": cid, "planet_id": 99, "character": "x", "planet": "P99", "product": "Biofuels",
         "kind": "miner", "action": "new"}]}, active=True)


def test_home_shows_operates_top_three_and_one_plan_line(browser, eve, monkeypatch, pi):
    monkeypatch.setattr(service.sde_loader, "cached", lambda: pi)
    c = browser()
    cid, pid = _pilot(c, eve, "Home Pilot", _colonies(time.time()))
    _plan(pid, cid)
    tile = asyncio.run(service.dashboard_tile({"id": pid}))
    chars = service.planning_characters(pid)
    plan = store.active_plan(pid)["result"]
    full = service.operate_overview(pi, store.load_settings(pid), {}, chars, None, plan)["next_up"]
    assert tile["state"] == "operate" and len(full) > 3
    assert tile["next_up"] == full[:3] and tile["next_up_more"] == len(full) - 3
    assert tile["has_colonies"] and (tile["built"], tile["planned"]) == (1, 2)

    html = c.get("/").text
    assert 'class="next-up-list"' in html and html.count('class="next-up-item') == 3
    assert f'href="/pi/operate{full[0]["href"]}"' in html
    assert "Forecast <b>7.3M</b> ISK/day · Built <b>1 / 2</b> · Earned 7d <b>0</b>" in html
    assert "Running operation" not in html and "Extractors ending within 24 h" not in html
    assert 'class="setup-path"' not in html


def test_home_before_any_colony_says_tracking_starts_instead_of_zeros(browser, eve, monkeypatch, pi):
    monkeypatch.setattr(service.sde_loader, "cached", lambda: pi)
    c = browser()
    cid, pid = _pilot(c, eve, "New Pilot")
    _plan(pid, cid)
    html = c.get("/").text
    assert "Tracking starts once your first colony is built" not in html     # build items lead instead
    assert "Build 2 new colonies" in html
    assert "Earned 7d" not in html and "In hangars" not in html

    store.save_plan_run(pid, "empty", Settings(), {"totals": {"isk_per_day": 1}, "colonies": [],
                                                   "characters": [{"character_id": cid, "name": "New Pilot"}]},
                        active=True)
    html = c.get("/").text
    assert "Tracking starts once your first colony is built" in html


# --------------------------------------------------------------------------- Operate (#90)
def test_operate_opens_with_next_up_and_sections(browser, eve, monkeypatch, pi):
    c = browser()
    cid, pid = _pilot(c, eve, "Deck Pilot", _colonies(time.time()))
    _plan(pid, cid)

    async def ctx(profile_id, *a, **kw):
        return {"chars": service.planning_characters(profile_id), "pi": pi, "s": Settings(), "books": {},
                "area": None, "tpl": []}

    monkeypatch.setattr(service, "planning_context", ctx)
    monkeypatch.setattr(service, "first_build", lambda ctx, active: {"todo": 1, "rebuild": 0, "blocked": 0,
                        "costs": {"total": 0, "command_centers": 0, "upgrades": 0, "structures": 0, "supplies": 0},
                        "cc_qty": 0, "command_centers": [], "supplies": [], "characters": [], "multibuy": ""})
    html = c.get("/pi/operate").text
    assert html.index('id="next-up"') < html.index('id="build"') < html.index('id="upkeep"') \
        < html.index('id="sell"') < html.index('id="income"')
    assert '<nav class="operate-nav" aria-label="Operate sections">' in html
    for anchor in ("#build", "#upkeep", "#sell", "#income"):
        assert f'href="{anchor}"' in html
    for target in ('id="extractors"', 'id="factories"', 'id="pickups"', 'id="consolidate"', 'id="orders"',
                   'id="schedule"', 'id="first-build"'):
        assert target in html
    # one colony is built as planned: the first-build checklist folds to one line
    assert '<details class="box first-build" id="first-build">' in html
    assert "Restock factory inputs" in html


# --------------------------------------------------------------------------- refresh on visit (#75)
def test_freshness_state_asks_for_a_refresh_only_when_stale_and_allowed(browser, eve):
    c = browser()
    cid, pid = _pilot(c, eve, "Fresh Pilot")
    now = time.time()
    st = freshness.state(pid, now)
    assert st["fresh"] and not st["stale"] and not st["auto"]

    db.set_character(cid, synced_at=now - 6 * 3600)
    st = freshness.state(pid, now)
    assert st["stale"] and st["auto"] and not st["fresh"] and st["behind"] == []

    db.update_profile(pid, last_esi_refresh_at=now - 60)       # read a minute ago: ESI won't have more
    assert not freshness.state(pid, now)["auto"]

    db.update_profile(pid, last_esi_refresh_at=0)
    db.set_character(cid, status="needs_login")                 # can't be read: nothing to refresh
    assert not freshness.state(pid, now)["auto"]


def test_refresh_on_visit_reads_only_stale_characters_once(browser, eve, monkeypatch):
    c = browser()
    fresh_id, pid = _pilot(c, eve, "Alpha")
    stale_id = new_id()
    sso_login(c, eve, stale_id, "Bravo", path="/auth/login?intent=add")
    db.save_token(stale_id, "rt", "at", 1199, PI_SCOPES)
    db.set_character(stale_id, status="ok", synced_at=time.time() - 3600)
    calls = []

    async def fake_refresh(profile_id, only=None, waits=None, ids=None):
        calls.append(set(ids))
        await asyncio.sleep(0.05)
        for i in ids:
            db.set_character(i, synced_at=time.time())
        return {}

    monkeypatch.setattr(service, "refresh_profile", fake_refresh)
    st = freshness.state(pid)
    assert st["auto"] and [b["name"] for b in st["behind"]] == ["Bravo"]

    async def two_tabs():
        return await asyncio.gather(freshness.refresh_stale(pid), freshness.refresh_stale(pid))
    first, second = asyncio.run(two_tabs())
    assert first["refreshed"] and second["refreshed"]
    assert calls == [{stale_id}]                       # one refresh, of the stale character only

    again = asyncio.run(freshness.refresh_stale(pid))  # nothing stale any more
    assert not again["refreshed"] and calls == [{stale_id}]


def test_refresh_endpoint_needs_csrf_and_pages_carry_the_trigger(browser, eve, monkeypatch, pi):
    monkeypatch.setattr(service.sde_loader, "cached", lambda: pi)
    c = browser()
    cid, pid = _pilot(c, eve, "Trigger Pilot")
    _plan(pid, cid)
    db.set_character(cid, synced_at=time.time() - 2 * 3600)

    async def fake_refresh(profile_id, only=None, waits=None, ids=None):
        for i in ids:
            db.set_character(i, synced_at=time.time())
        return {}

    monkeypatch.setattr(service, "refresh_profile", fake_refresh)
    html = c.get("/").text
    assert 'data-auto-refresh="/refresh/auto"' in html and "refreshing…" in html
    assert "Updated 2 h ago" in html and "ESI only updates a colony after you open it in game" in html
    assert "js/freshness.js" in html

    assert c.post("/refresh/auto", json={}).status_code == 403
    r = c.post("/refresh/auto", json={}, headers={"X-CSRF-Token": csrf(c)})
    assert r.status_code == 200 and r.json()["refreshed"] is True

    html = c.get("/").text
    assert "data-auto-refresh" not in html and "Updated just now" in html
    # within five minutes of a read the page doesn't start another one
    db.set_character(cid, synced_at=time.time() - 2 * 3600)
    assert c.post("/refresh/auto", json={}, headers={"X-CSRF-Token": csrf(c)}).json() == \
        {"refreshed": False, "problems": {}, "wait": pytest.approx(300, abs=5)}
    assert "data-auto-refresh" not in c.get("/").text
