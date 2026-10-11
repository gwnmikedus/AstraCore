"""Plan comparisons: effort and uncertainty facts, saved-plan tables, multi-character and multi-system plans.

Fake characters, systems and plans only.
"""
from __future__ import annotations

import re

from astracore import db
from astracore.core import fmt
from astracore.core.web import templates
from astracore.modules.pi import service, store
from astracore.modules.pi.planner import compare
from astracore.modules.pi.settings import Settings

from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401 (fixtures)
from test_planner import _plan, pi  # noqa: F401 (fixture)

THREE_CHARS = [{"character_id": i, "name": f"Pilot {i}", "slots": 2, "ccu_level": 5, "colonies": []} for i in (1, 2, 3)]


def _fake_plan(chars=3, systems=("HUB", "NEXT", "FAR", "EDGE", "RIM"), calibrated=False, batches=()):
    colonies = [{"character_id": i % chars + 1, "system": systems[i % len(systems)], "kind": "miner", "tier": 1}
                for i in range(6)]
    return {
        "hub": "HUB", "colonies": colonies,
        "characters": [{"character_id": i + 1, "name": f"Pilot {i + 1}", "used": 2} for i in range(chars)]
        + [{"character_id": 99, "name": "Idle alt", "used": 0}],
        "totals": {"isk_per_day": 46_200_000, "isk_per_week": 323_400_000, "m3_per_week": 120_000, "systems": len(systems),
                   "colonies": 6, "slots_total": 8, "factories": 1, "restarts_per_week": 11.7, "transfers": 2},
        "selling": {"net_per_day": 40_000_000, "batches": list(batches), "unsellable": []},
        "yield": {"calibrated": calibrated, "head_yield": 9000},
    }


def test_duration_is_readable_and_never_shows_60_minutes():
    assert fmt.duration(45) == "45 min"
    assert fmt.duration(119.6) == "2 h 00 min"
    assert fmt.duration(65) == "1 h 05 min"
    assert fmt.duration(None) == "–" and fmt.duration(float("inf")) == "–" and fmt.duration(-3) == "0 min"


def test_effort_counts_restarts_logins_rounds_hauling_and_contracts():
    totals = {"colonies": 6, "systems": 3, "factories": 1, "restarts_per_week": 10, "m3_per_week": 60000, "transfers": 2}
    s = Settings(cycle_days=7, ship_every_days=7, use_sell_orders=True)
    # 10*1.5 restarts + 1*3 logins + 1*(6 + 3*5) round + 20 hauling + 3 restock + 2*2 transfers + 5 batch + 20 orders
    assert compare.effort_minutes(totals, s, characters=3) == 15 + 3 + 21 + 20 + 3 + 4 + 5 + 20
    assert compare.effort_minutes(totals, {"cycle_days": 7, "ship_every_days": 7}, 3) == 15 + 3 + 21 + 20 + 3 + 4 + 5
    assert compare.effort_minutes({}, s, 3) is None


def test_uncertainty_names_its_reasons():
    sure = compare.uncertainty(True, False, False, 0, 0)
    assert sure["level"] == "lower" and sure["reasons"] == ["Measured yield and instant sales"]
    shaky = compare.uncertainty(False, True, True, 2, 0)
    assert shaky["level"] == "higher"
    assert any("estimate" in r for r in shaky["reasons"]) and any("Sell orders" in r for r in shaky["reasons"])
    assert "2 batches held" in "; ".join(shaky["reasons"])
    assert compare.uncertainty(None, False, False, 0, 0)["level"] == "medium"   # old saved plan: source unknown


def test_facts_for_a_multi_character_plan_across_systems(pi):
    res = _plan(pi, chars=THREE_CHARS, max_jumps=2)
    assert "error" not in res, res
    facts = compare.plan_facts(res, Settings(cycle_days=3, ship_every_days=7))
    used = {c["character_id"] for c in res["colonies"]}
    assert facts["characters_used"] == len(used) >= 2 and facts["characters_total"] == 3
    assert facts["system_names"] == sorted({c["system"] for c in res["colonies"]})
    assert len(facts["system_names"]) == res["totals"]["systems"] >= 2
    assert facts["minutes_per_week"] == compare.effort_minutes(res["totals"], Settings(cycle_days=3), len(used))
    assert facts["yield_measured"] is None                              # optimizer output alone has no yield source
    summary = service.whatif_summary(res, Settings())
    assert summary["facts"]["characters_used"] == facts["characters_used"]


def test_courier_sell_orders_and_holds_raise_uncertainty():
    batches = [{"channel": "jita_sell", "hold": False}, {"channel": "buyback", "hold": False},
               {"channel": "amarr_buy", "hold": True}]
    facts = compare.plan_facts(_fake_plan(batches=batches), {"use_sell_orders": True})
    assert facts["sell_orders"] and facts["courier"] and facts["held_batches"] == 1
    assert facts["uncertainty"]["level"] == "higher"
    calm = compare.plan_facts(_fake_plan(calibrated=True, batches=[{"channel": "buyback"}]), {})
    assert calm["uncertainty"]["level"] == "lower"
    assert compare.plan_facts({"error": "nothing fits"}) == {}


def test_saved_plans_list_facts_even_for_old_plans():
    pid = db.create_profile("Compare saved")
    try:
        store.save_plan_run(pid, "old", Settings(), {"totals": {}}, active=True)
        store.save_plan_run(pid, "three pilots", Settings(cycle_days=2, ship_every_days=14), _fake_plan())
        plans = {p["label"]: p for p in store.list_plan_runs(pid)}
        assert plans["old"]["facts"]["minutes_per_week"] is None
        new = plans["three pilots"]["facts"]
        assert new["characters_used"] == 3 and new["characters_total"] == 4
        assert new["system_names"] == ["EDGE", "FAR", "HUB", "NEXT", "RIM"]
        assert new["minutes_per_week"] == compare.effort_minutes(_fake_plan()["totals"],
                                                                 {"cycle_days": 2, "ship_every_days": 14}, 3)
    finally:
        db.delete_profile(pid)


def test_saved_plan_table_has_units_labels_and_one_activate_form_per_inactive_plan():
    pid = db.create_profile("Compare table")
    try:
        store.save_plan_run(pid, "Active <b>plan</b>", Settings(), _fake_plan(chars=2, systems=("HUB", "NEXT")), active=True)
        store.save_plan_run(pid, "Wide", Settings(use_sell_orders=True),
                            _fake_plan(batches=[{"channel": "jita_sell"}]))
        store.save_plan_run(pid, "legacy", Settings(), {"totals": {}})
        macro = templates.env.get_template("pi/_plan_compare.html").module.plan_compare_table
        html = str(macro(store.list_plan_runs(pid), "csrf-test"))
    finally:
        db.delete_profile(pid)
    assert "Active &lt;b&gt;plan&lt;/b&gt;" in html and "<b>plan</b>" not in html
    assert html.count('aria-current="true"') == 1
    assert html.count('action="/pi/plans/') == 2 and 'value="csrf-test"' in html
    for unit in ("46.2M ISK/day", "323.4M ISK/week", "120,000 m³ / week", "12 / week", "6 of 8 slots",
                 "2 transfers between characters", "/ week"):
        assert unit in html, unit
    assert "3 of 4" in html and "2 of 3" in html                     # characters used of characters in the plan
    assert "EDGE, FAR, HUB, NEXT +1 more" in html and "drop-off HUB" in html
    for label in ("Income", "Your time", "Colonies", "Characters", "Systems", "Restarts", "Haul", "Uncertainty"):
        assert len(re.findall(f'data-label="{label}"', html)) == 3
    assert "Sell orders" in html and "Higher" in html
    assert "votes" not in html.lower() and "demand" not in html.lower()


def test_wizard_can_save_an_answer_while_jumping_to_a_later_step(browser, eve):  # noqa: F811
    c = browser()
    sso_login(c, eve, new_id(), "Jumper")
    pid = me(c)
    store.save_settings(pid, Settings(cycle_days=3, max_tier=2, answered=["goal", "cycle", "area", "tier"], guide_step=8))
    r = c.post("/pi/api/save", json={"cycle_days": 1, "answered": ["goal", "cycle", "area", "tier"], "guide_step": 3},
               headers={"X-CSRF-Token": csrf(c)})
    assert r.status_code == 200
    s = store.load_settings(pid)
    assert (s.cycle_days, s.max_tier, s.guide_step) == (1, 2, 3)      # later answers stay
    assert s.answered == ["goal", "cycle", "area", "tier"]
