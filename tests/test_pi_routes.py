"""AstracorePI routing and the shared number formatter."""
from __future__ import annotations

from astracore import db
from astracore.core import fmt
from astracore.modules.pi import store
from astracore.modules.pi.settings import Settings

from test_core import PI_SCOPES, browser, csrf, eve, me, new_id, sso_login  # noqa: F401 (fixtures)


def test_pi_entry_lands_where_it_should(browser, eve):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Lander", scopes="publicData")           # no PI scopes yet
    pid = me(c)
    r = c.get("/pi", follow_redirects=False)
    assert r.status_code == 200 and "Connect your characters" in r.text
    db.save_token(cid, "rt", "at", 1199, PI_SCOPES)                   # PI login done
    assert c.get("/pi", follow_redirects=False).headers["location"] == "/pi/area"
    s = store.load_settings(pid)
    s.selected_constellations = [20000001]
    store.save_settings(pid, s)
    assert c.get("/pi", follow_redirects=False).headers["location"] == "/pi/plan"
    store.save_plan_run(pid, "mine", s, {"totals": {}}, active=True)
    assert c.get("/pi", follow_redirects=False).headers["location"] == "/pi/operate"   # returning user -> Operate


def test_old_paths_redirect_permanently(browser):
    c = browser()
    for old, new in (("/space", "/pi/area"), ("/planner?view=advanced", "/pi/plan?view=advanced"),
                     ("/operate", "/pi/operate"), ("/characters", "/profile"), ("/export/plan.md", "/pi/export/plan.md")):
        r = c.get(old, follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == new


def test_wizard_save_changes_only_what_was_sent(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Saver")
    pid = me(c)
    store.save_settings(pid, Settings(effort=10, cycle_days=3, max_tier=4))
    r = c.post("/pi/api/save", json={"cycle_days": 7, "answered": ["goal", "cycle"], "guide_step": 2,
                                     "buyback_pct": 1}, headers={"X-CSRF-Token": csrf(c)})
    assert r.status_code == 200
    s = store.load_settings(pid)
    assert (s.cycle_days, s.effort, s.max_tier, s.guide_step, s.answered) == (7, 10, 4, 2, ["goal", "cycle"])
    assert s.buyback_pct == 90.0                                       # admin-only value can't be set by a profile


def test_plan_header_distinguishes_connected_and_eligible_characters(browser, eve, monkeypatch):
    from astracore.modules.pi import service

    c = browser()
    sso_login(c, eve, new_id(), "Planner")
    chars = [
        {"character_id": 1, "name": "Ready", "slots": 6, "ccu_level": 5},
        {"character_id": 2, "name": "Training", "slots": 1, "ccu_level": 0},
    ]

    async def context(pid):
        return {"s": Settings(), "chars": chars, "systems": {}, "area": {}, "calibrated": False,
                "head_yield": 1500, "dropoff": None, "seller": None}

    monkeypatch.setattr(service, "planning_context", context)
    r = c.get("/pi/plan")
    assert r.status_code == 200
    assert "2 characters (1 can plan) · 6 colony slots" in r.text

    chars[1]["ccu_level"] = 2
    r = c.get("/pi/plan")
    assert "2 characters · 7 colony slots" in r.text
    assert "(2 can plan)" not in r.text


def test_admin_values_override_profile_settings():
    pid = db.create_profile("Admin test")
    store.save_admin_settings({"buyback_pct": "85"})
    try:
        assert store.load_settings(pid).buyback_pct == 85.0
        assert "buyback_pct" not in (db.module_settings(pid, "pi") or {})
    finally:
        store.save_admin_settings({"buyback_pct": "90"})
        db.delete_profile(pid)


def test_planet_richness_override_per_profile(browser, eve):
    ca, cb = browser(), browser()
    sso_login(ca, eve, new_id(), "Scanner")
    sso_login(cb, eve, new_id(), "Other")
    ca.post("/pi/area/richness", data={"planet_id": "40000100", "richness": "1.5", "csrf_token": csrf(ca)})
    assert store.planet_overrides(me(ca)) == {40000100: 1.5}
    assert store.planet_overrides(me(cb)) == {}
    ca.post("/pi/area/richness", data={"planet_id": "40000100", "richness": "", "csrf_token": csrf(ca)})
    assert store.planet_overrides(me(ca)) == {}


def test_number_formatter_is_locale_free_and_never_negative_zero():
    assert fmt.num(123379) == "123,379"
    assert fmt.m3(210138.5) == "210,139 m³"
    assert fmt.isk(46.2e6) == "46.2M" and fmt.isk(1.24e9) == "1.24B" and fmt.isk(950_000) == "950k"
    assert fmt.num(-0.3) == "0" and fmt.isk(-0.01) == "0" and fmt.isk(-40_000) == "-40k"
    assert fmt.count(94.5) == "95"
    assert fmt.num(None) == "–" and fmt.isk("") == "–"


def test_operate_shows_the_upkeep_schedule(browser, eve, monkeypatch):
    import time

    from astracore.modules.pi import service
    from test_planner import _colonies, pi as _pi_fixture

    pi = _pi_fixture.__wrapped__()
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Upkeep Pilot")
    pid = me(c)
    db.save_token(cid, "rt", "at", 1199, PI_SCOPES)
    colonies = list(_colonies(time.time()))
    colonies[1]["pins"][2]["expiry_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3 * 3600))
    db.set_character(cid, colonies=colonies, synced_at=time.time())
    s = Settings()
    store.save_plan_run(pid, "upkeep", s, {"totals": {}, "colonies": [
        {"character_id": cid, "planet_id": 12, "character": "Upkeep Pilot", "planet": "P12", "product": "Biocells",
         "kind": "factory", "action": "keep", "layout": {"advanced": 2, "launchpads": 1},
         "in_per_day": {"Biofuels": 1920, "Precious Metals": 1920}, "out_per_day": {"Biocells": 480}}]}, active=True)

    async def ctx(profile_id, *a, **kw):
        return {"chars": service.planning_characters(profile_id), "pi": pi, "s": s, "books": {}, "area": None,
                "tpl": []}

    monkeypatch.setattr(service, "planning_context", ctx)
    r = c.get("/pi/operate")
    assert r.status_code == 200, r.text
    html = r.text
    assert 'id="upkeep"' in html and "Upkeep schedule" in html
    assert "Restock inputs" in html and "Restart extractors" in html
    assert "market shipment · every 7 days" in html
    assert "Precious Metals" in html and "doesn't send reminders" in html
    assert "50% of planned 480" in html and "not in the active plan" in html
    assert '<caption>Colony visits and upkeep</caption>' in html
    assert '<caption>Extractor restart times</caption>' in html
    assert "3.0 h · soon" in html


def test_plan_cache_ignores_wizard_bookkeeping_and_files_plans_under_the_data_they_used(monkeypatch):
    import asyncio
    from astracore.core.solvegate import GATE
    from astracore.modules.pi import service
    from astracore.modules.pi.settings import Settings

    GATE.clear()
    stamps = iter(["before-refresh", "after-refresh", "after-refresh", "after-refresh"])
    monkeypatch.setattr(service, "data_stamp", lambda pid: next(stamps))
    runs = []

    async def context(pid, s=None, persist_default=True):
        return {"solve_s": s}

    def run(ctx, s=None):
        runs.append(ctx["solve_s"].guide_step)
        return {"totals": {"isk_per_day": 1.0}}

    monkeypatch.setattr(service, "planning_context", context)
    monkeypatch.setattr(service, "run_plan", run)
    asyncio.run(service.solve(1, Settings(guide_step=2, answered=["goal"])))
    # the next request sees the refreshed data stamp and other wizard bookkeeping: same plan, no new solve
    asyncio.run(service.solve(1, Settings(guide_step=5, answered=["goal", "cycle"])))
    assert runs == [2]
    GATE.clear()


def test_area_save_never_stores_an_empty_selection(browser, eve):
    from test_core import csrf, me, new_id, sso_login
    from astracore.modules.pi import store

    c = browser()
    sso_login(c, eve, new_id(), "Picker")
    pid = me(c)
    s = store.load_settings(pid)
    s.selected_constellations = [7]
    store.save_settings(pid, s)
    r = c.post("/pi/area", data={"csrf_token": csrf(c), "hub_system": ""}, follow_redirects=False)
    assert r.status_code == 303 and "Nothing was changed" in r.headers["location"].replace("%20", " ").replace("+", " ")
    assert store.load_settings(pid).selected_constellations == [7]


def test_area_labels_are_readable_without_hover(browser, eve, monkeypatch):
    from html.parser import HTMLParser
    from astracore.modules.pi import service
    from test_planner import _area

    area = _area()
    area["sources"] = {"alliances": [], "colony_constellations": [], "extra": ["Synthetic region"]}
    area["systems"]["1"]["security"] = -0.9
    area["systems"]["2"]["security"] = -0.1
    for i, kind in enumerate(("Barren", "Oceanic", "Storm", "Shattered", "Unknown"), 14):
        area["systems"]["1"]["planets"].append({"planet_id": i, "name": f"P{i}", "type": kind})

    async def load_space(*args, **kwargs):
        return area

    monkeypatch.setattr(service, "load_space", load_space)
    c = browser()
    sso_login(c, eve, new_id(), "Area labels pilot")
    r = c.get("/pi/area")
    assert r.status_code == 200

    class VisibleText(HTMLParser):
        text = ""

        def handle_data(self, data):
            self.text += data

    visible = VisibleText()
    visible.feed(r.text)
    assert "sec -0.9 to -0.1" in visible.text
    assert "Barren×2" in visible.text
    assert "Temperate" in visible.text and "Oceanic" in visible.text and "Storm" in visible.text
    assert "Shattered" not in visible.text and "Unknown" not in visible.text
    assert 'name="con" value="1" checked' in r.text


def test_area_scan_picker_includes_unused_and_unselected_planets(browser, eve, monkeypatch):
    from astracore.modules.pi import service
    from test_planner import _area

    area = _area()
    area["sources"] = {"alliances": [], "colony_constellations": [], "extra": ["Synthetic region"]}
    area["systems"]["3"].update(constellation_id=2, constellation="Other constellation")
    area["systems"]["3"]["planets"].extend([
        {"planet_id": 32, "name": "Shattered example", "type": "Shattered"},
        {"planet_id": 33, "name": "Unknown example", "type": "Unknown"},
    ])

    async def load_space(*args, **kwargs):
        return area

    monkeypatch.setattr(service, "load_space", load_space)
    c, other = browser(), browser()
    sso_login(c, eve, new_id(), "Scanner")
    sso_login(other, eve, new_id(), "Other scanner")
    pid = me(c)
    settings = Settings(selected_constellations=[1])
    store.save_settings(pid, settings)
    store.save_plan_run(pid, "Existing plan", settings, {"totals": {}, "colonies": [{"planet_id": 11}]}, active=True)
    html = c.get("/pi/area").text
    assert 'form="scan-richness" required' in html
    assert '<optgroup label="FAR">' in html
    assert '<option value="31">P31 (Barren)</option>' in html
    assert '<option value="21">P21 (Barren)</option>' in html
    assert '<option value="32">' not in html and '<option value="33">' not in html
    assert html.count('action="/pi/area/richness" id="scan-richness"') == 1

    response = c.post("/pi/area/richness", data={"planet_id": "31", "richness": "1.5", "csrf_token": csrf(c)})
    assert response.status_code == 200
    assert "P31: rich (1.5×)" in response.text
    assert store.planet_overrides(pid) == {31: 1.5}
    assert store.planet_overrides(me(other)) == {}
    assert store.load_settings(pid).selected_constellations == [1]
    assert store.active_plan(pid)["result"]["colonies"] == [{"planet_id": 11}]
    assert c.post("/pi/area/richness", data={"planet_id": "31", "richness": "3.5", "csrf_token": csrf(c)}).status_code == 200
    assert store.planet_overrides(pid) == {31: 1.5}
    assert c.post("/pi/area/richness", data={"planet_id": "31", "richness": ""}).status_code == 403
    c.post("/pi/area/richness", data={"planet_id": "31", "richness": "", "csrf_token": csrf(c)})
    assert store.planet_overrides(pid) == {}
