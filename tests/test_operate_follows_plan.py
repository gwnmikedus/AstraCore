"""Operate and Home follow the active plan (#242): same area for Next up, the plan's own wizard answers,
and routes that resolve after the area changed.

Synthetic characters, systems and plans only; ESI is never called.
"""
from __future__ import annotations

import asyncio
import json
import time

from astracore import db
from astracore.modules.pi import routes, service, store
from astracore.modules.pi.intel import area as area_mod
from astracore.modules.pi.settings import Settings

from test_core import PI_SCOPES, WAYPOINT, browser, csrf, eve  # noqa: F401 (fixtures)
from test_next_up import _pilot, _plan
from test_planner import _colonies, pi  # noqa: F401 (fixture)


def _area(*systems):
    """A resolved area: (system id, name, [(planet id, planet name)])."""
    return {"query": "test area", "found": [], "systems": {str(sid): {
        "system_id": sid, "name": name, "security": -0.3, "constellation_id": 1, "constellation": "Test Con",
        "region": "Test Region", "neighbours": [], "exits": 0,
        "planets": [{"planet_id": p, "name": pn, "type": "Barren"} for p, pn in planets]}
        for sid, name, planets in systems}}


def _cache_area(pid, area):
    """What load_space leaves behind after Operate resolved the area: Home reads only this."""
    chars = service.planning_characters(pid)
    db.kv_set(area_mod.AREA_KEY + area["query"].lower(), area)
    db.kv_set(service._area_owner(chars, store.load_settings(pid)), area["query"])


def test_home_next_up_uses_operates_area(browser, eve, monkeypatch, pi):
    monkeypatch.setattr(service.sde_loader, "cached", lambda: pi)
    c = browser()
    cid, pid = _pilot(c, eve, "Area Pilot", _colonies(time.time()))
    _plan(pid, cid)
    area = _area((30000001, "Test-Sys", [(11, "Test-Sys I"), (12, "Test-Sys II")]))
    _cache_area(pid, area)

    chars = service.planning_characters(pid)
    active = store.active_plan(pid)
    s = store.load_settings(pid)
    with_area = service.operate_overview(pi, s, {}, chars, area, active)["next_up"]
    without = service.operate_overview(pi, s, {}, chars, None, active)["next_up"]
    assert with_area != without                      # the area matters: planet names come from it
    assert "Test-Sys" in json.dumps(with_area)

    tile = asyncio.run(service.dashboard_tile({"id": pid}))
    assert tile["next_up"] == with_area[:3]
    assert tile["next_up_more"] == max(0, len(with_area) - 3)

    async def ctx(profile_id, *a, **kw):    # Operate itself, with the area load_space resolved
        return {"chars": service.planning_characters(profile_id), "pi": pi, "s": store.load_settings(profile_id),
                "books": {}, "area": area, "tpl": []}

    monkeypatch.setattr(service, "planning_context", ctx)
    monkeypatch.setattr(service, "first_build", lambda ctx, active: None)
    html = c.get("/pi/operate").text
    home = c.get("/").text
    named = [item["where"] for item in with_area[:3] if "Test-Sys" in item["where"]]
    assert named
    for where in named:
        assert where in html and where in home


def test_operate_advises_with_the_active_plans_answers(browser, eve, pi):
    c = browser()
    cid, pid = _pilot(c, eve, "Answer Pilot", _colonies(time.time()))
    planned = Settings(ship_every_days=14, use_self_haul=False, sales_tax_pct=4.5)
    store.save_plan_run(pid, "planned", planned, {"totals": {}, "colonies": []}, active=True)
    # exploring the wizard after saving: the plan didn't change, so Operate's advice shouldn't either
    now = store.load_settings(pid)
    now.ship_every_days, now.use_self_haul = 3, True
    now.taxes_from_skills, now.sales_tax_pct = False, 2.0       # settings-page economics stay live
    store.save_settings(pid, now)

    chars = service.planning_characters(pid)
    active = store.active_plan(pid)
    s = service.operate_settings(store.load_settings(pid), chars, active)
    assert (s.ship_every_days, s.use_self_haul) == (14, False)
    assert (s.taxes_from_skills, s.sales_tax_pct) == (False, 2.0)
    ov = service.operate_overview(pi, store.load_settings(pid), {}, chars, None, active)
    assert ov["upkeep"]["tracks"]["ship"]["every_days"] == 14

    # no plan saved: Operate follows the current answers
    assert service.operate_settings(store.load_settings(pid), chars, None).ship_every_days == 3
    ov = service.operate_overview(pi, store.load_settings(pid), {}, chars, None, None)
    assert ov["upkeep"]["tracks"]["ship"]["every_days"] == 3


def test_settings_for_plan_keeps_live_fields_only():
    now = Settings(effort=90, use_jita=False, hour_isk=5e6, poco_tax_pct=7.0, head_yield_per_hour=2000.0,
                   guide_step=5, answered=["goal"])
    plan = json.loads(Settings(effort=10, use_jita=True, hour_isk=-1.0).to_json())
    s = now.for_plan(plan)
    assert (s.effort, s.use_jita, s.hour_isk) == (10, True, -1.0)
    assert (s.poco_tax_pct, s.head_yield_per_hour, s.guide_step, s.answered) == (7.0, 2000.0, 5, ["goal"])
    assert now.for_plan(None) is now and now.for_plan({}) is now


class _Client:
    sent = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, params=None, headers=None):
        _Client.sent.append(params["destination_id"])
        return type("R", (), {"status_code": 204})()


def test_waypoints_resolve_the_active_plans_systems_after_the_area_changed(browser, eve, monkeypatch):
    c = browser()
    cid, pid = _pilot(c, eve, "Route Pilot")
    db.save_token(cid, "rt", "at", 1199, PI_SCOPES + " " + WAYPOINT)
    store.save_plan_run(pid, "old area", Settings(), {"totals": {}, "hub": "Old-Hub", "hub_id": 30000010, "colonies": [
        {"character_id": cid, "planet_id": 21, "system": "Old-Sys", "system_id": 30000011, "kind": "miner"}]},
        active=True)
    calls = []

    async def new_area(chars, s, **kw):     # the current area no longer has the plan's systems
        calls.append(1)
        return _area((30000099, "New-Sys", []))

    async def token(character_id):
        return "at"

    monkeypatch.setattr(service, "load_space", new_area)
    monkeypatch.setattr(routes.sso, "access_token", token)
    monkeypatch.setattr(routes.httpx, "AsyncClient", _Client)
    _Client.sent = []
    t = csrf(c)
    r = c.post("/pi/api/waypoints", json={"character_id": cid, "systems": ["Old-Hub", "old-sys", "Old-Hub"]},
               headers={"X-CSRF-Token": t})
    assert r.status_code == 200, r.text
    assert _Client.sent == [30000010, 30000011, 30000010] and calls == []    # no area needed

    # a system outside the plan (an unsaved plan result) still resolves against the current area
    _Client.sent = []
    r = c.post("/pi/api/waypoints", json={"character_id": cid, "systems": ["Old-Hub", "New-Sys", "Gone"]},
               headers={"X-CSRF-Token": t})
    assert r.status_code == 200 and _Client.sent == [30000010, 30000099] and calls == [1]
