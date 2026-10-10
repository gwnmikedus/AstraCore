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
