"""One home for planner assumptions (issue #105): the Expert panel on Settings, "Never produce" and
richness on the plan result, and the Area page's read-only richness list."""
from __future__ import annotations

import re

from astracore.modules.pi import routes, service, store
from astracore.modules.pi.settings import Settings

from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401 (fixtures)
from test_planner import _plan, pi  # noqa: F401 (fixture)


def test_expert_panel_is_collapsed_and_holds_the_expert_assumptions(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Expert")
    html = c.get("/pi/settings").text
    panel = re.search(r'<details class="box expert" id="expert"\s*>', html)
    assert panel, "the Expert panel is collapsed by default"
    assert 'id="expert-yield"' in html and 'id="expert-sharing"' in html and 'id="expert-taxes"' in html
    assert "Estimate: 1,000 P0/h per head" in html                       # no extractors: a status, not just an input
    assert "Customs tax % where the real rate is unknown (export; import is charged at half)" in html
    assert "Import tax is half of this" not in html
    assert 'class="tax-manual"' in html                                  # shown by CSS only when "from skills" is off
    assert 'name="sales_tax_pct"' in html and " disabled" not in html.split('class="tax-manual"')[1].split("</div>")[0]
    assert 'name="stack_yield_pct"' in html
    assert re.search(r'<details class="box expert" id="expert" open>', c.get("/pi/settings?expert=1").text)


def test_saving_expert_values_returns_to_the_open_panel(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Saver")
    r = c.post("/pi/settings", data={"csrf_token": csrf(c), "__bool_fields__": ["taxes_from_skills", "auto_calibrate"],
                                     "auto_calibrate": "on", "sales_tax_pct": "3.6", "stack_yield_pct": "60",
                                     "buyback_pct": "1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pi/settings?expert=1")
    assert r.headers["location"].endswith("#expert")
    s = store.load_settings(me(c))
    assert (s.taxes_from_skills, s.sales_tax_pct, s.stack_yield_pct, s.buyback_pct) == (False, 3.6, 60.0, 90.0)
    html = c.get("/pi/settings").text
    assert "You entered sales tax 3.6% and broker fee 3% yourself" in html


def test_yield_status_says_when_it_is_calibrated(browser, eve, monkeypatch):
    c = browser()
    sso_login(c, eve, new_id(), "Calibrated")
    monkeypatch.setattr(service, "calibrated_yield", lambda chars, area: 2345.0)
    html = c.get("/pi/settings").text
    assert "Calibrated from your extractors: 2,345 P0/h per head" in html
    s = store.load_settings(me(c))
    s.auto_calibrate = False
    store.save_settings(me(c), s)
    html = c.get("/pi/settings").text
    assert "Estimate: 1,000 P0/h per head" in html and "measuring from your extractors is switched off" in html


def test_richness_is_set_from_the_plan_result(browser, eve):
    ca, cb = browser(), browser()
    sso_login(ca, eve, new_id(), "Scanner")
    sso_login(cb, eve, new_id(), "Other")
    post = lambda body, c=ca: c.post("/pi/api/richness", json=body, headers={"X-CSRF-Token": csrf(c)})
    r = post({"planet_id": 40000100, "richness": 1.5})
    assert r.status_code == 200 and r.json() == {"ok": True, "planet_id": 40000100, "richness": 1.5}
    assert store.planet_overrides(me(ca)) == {40000100: 1.5}
    assert store.planet_overrides(me(cb)) == {}
    assert post({"planet_id": 40000100, "richness": 9}).status_code == 400
    assert post({"planet_id": "x", "richness": 1}).status_code == 400
    assert post({"planet_id": 40000100, "richness": "rich"}).status_code == 400
    assert store.planet_overrides(me(ca)) == {40000100: 1.5}
    assert post({"planet_id": 40000100, "richness": None}).status_code == 200
    assert store.planet_overrides(me(ca)) == {}
    assert ca.post("/pi/api/richness", json={"planet_id": 1, "richness": 1}).status_code == 403   # CSRF header required


def test_plan_rows_say_where_richness_comes_from():
    cols = [{"planet_id": 1}, {"planet_id": 2}, {"planet_id": 3}]
    service.richness_sources(cols, manual={1: 1.5}, measured={1: 0.8, 2: 1.1})
    assert [c["richness_source"] for c in cols] == ["scan", "extractors", "estimate"]


def test_never_produce_is_returned_as_product_names(pi):
    res = _plan(pi, product_blacklist=["coolant ", "Coolent", "WATER"], max_jumps=2)
    assert res["never_produce"] == ["Coolant", "Water"]
    assert not any(c["product"] in ("Coolant", "Water") for c in res["colonies"])
    assert _plan(pi, max_jumps=2)["never_produce"] == []


def test_advanced_never_produce_is_a_checkbox_per_pi_product(browser, eve, monkeypatch, pi):
    c = browser()
    sso_login(c, eve, new_id(), "Picker")

    async def context(pid, *a, **kw):
        return {"s": Settings(product_blacklist=["Water"]), "chars": [], "systems": {}, "area": {}, "pi": pi,
                "calibrated": False, "head_yield": 1000, "dropoff": None, "seller": None}

    monkeypatch.setattr(service, "planning_context", context)
    html = c.get("/pi/plan?view=advanced").text
    assert 'id="product_blacklist"' not in html                            # no free text any more
    boxes = re.findall(r'<input type="checkbox" data-never-all value="([^"]+)">', html)
    assert "Water" in boxes and "Coolant" in boxes
    assert all(p["name"] in boxes for p in routes._product_names(pi))
    assert not any(pi.tier(t) == 0 and pi.name(t) in boxes for t in pi.items)   # raw resources can't be produced
    assert 'href="/pi/settings?expert=1#expert"' in html
    guided = c.get("/pi/plan").text
    assert "/pi/settings?expert=1#expert" in guided and "const RICHNESS = [[" in guided


def test_area_lists_scans_and_measurements_alongside_the_grouped_scan_picker(browser, eve, monkeypatch):
    from test_planner import _area

    c = browser()
    sso_login(c, eve, new_id(), "Area Pilot")
    area = _area()
    planet = next(p for v in area["systems"].values() for p in v["planets"])
    other = next(p for v in area["systems"].values() for p in v["planets"] if p["planet_id"] != planet["planet_id"])

    async def load_space(chars, s, **kw):
        return area

    monkeypatch.setattr(service, "load_space", load_space)
    monkeypatch.setattr(routes, "_measured_richness", lambda chars, area, s: {other["planet_id"]: 0.85,
                                                                              planet["planet_id"]: 1.1})
    store.set_planet_override(me(c), planet["planet_id"], 1.25)
    r = c.get("/pi/area")
    assert r.status_code == 200
    html = r.text
    assert 'form="richness-form"' not in html
    assert 'name="planet_id" form="scan-richness" required' in html
    assert '<optgroup label="HUB">' in html
    assert f"{planet['name']}: good (1.25×)" in html
    assert f"{other['name']}: 0.85×" in html and "Measured from your extractors" in html
    assert f"{planet['name']}: 1.1×" not in html                          # a scan wins over a measurement
    assert f'id="rm-richness-{planet["planet_id"]}"' in html               # removing an override still works
