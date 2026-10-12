"""Offline candidate retention: actual template plans, synthetic solver outcomes and API cache reuse."""
from __future__ import annotations

import copy
from dataclasses import asdict

import pytest

from astracore.core.solvegate import GATE
from astracore.modules.pi import service
from astracore.modules.pi.planner import whatif
from astracore.modules.pi.settings import Settings

from test_core import browser, csrf, eve, new_id, sso_login  # noqa: F401
from test_planner import _area, _plan, pi  # noqa: F401


def row(name, settings, plan, assumptions="same synthetic inputs"):
    return {"id": name, "settings": asdict(settings), "plan": plan, "assumptions": assumptions}


@pytest.fixture()
def solved(pi):
    result = _plan(pi, max_tier=1, max_systems=1, max_jumps=1)
    assert "error" not in result
    return result


@pytest.mark.parametrize("limit,small,large", [
    ("max_tier", 1, 4), ("max_systems", 1, 0), ("max_jumps", 1, 6),
    ("per_planet", 1, 3), ("cross_character", False, True),
])
def test_relaxed_limits_retain_a_known_feasible_income_floor(solved, limit, small, large):
    narrow = Settings(max_tier=1, max_systems=1, max_jumps=1)
    setattr(narrow, limit, small)
    wide = copy.deepcopy(narrow)
    setattr(wide, limit, large)
    weaker = copy.deepcopy(solved)
    weaker["totals"]["isk_per_day"] -= 600_000  # a lower-incumbent independent solve
    candidates = [row("narrow", narrow, solved), row("wide", wide, weaker)]
    before = copy.deepcopy(candidates)
    forward = service.whatif_rows(candidates)
    reverse = list(reversed(service.whatif_rows(list(reversed(candidates)))))
    assert forward == reverse
    assert forward[1]["totals"] == forward[0]["totals"]
    assert forward[1]["facts"] == forward[0]["facts"]
    assert forward[1]["same_as"] == "narrow"
    assert candidates == before  # request-specific substitutions never pollute native cached candidates


def test_three_tiers_keep_the_best_narrower_candidate_in_any_order(solved):
    p2 = copy.deepcopy(solved)
    p3 = copy.deepcopy(solved)
    p4 = copy.deepcopy(solved)
    p3["totals"]["isk_per_day"] += 250_000
    p4["totals"]["isk_per_day"] += 20_000
    candidates = [row("P4", Settings(max_tier=4), p4), row("P2", Settings(max_tier=2), p2),
                  row("P3", Settings(max_tier=3), p3)]
    rows = {r["id"]: r for r in service.whatif_rows(candidates)}
    assert rows["P4"]["totals"]["isk_per_day"] == rows["P3"]["totals"]["isk_per_day"]
    assert rows["P4"]["same_as"] == "P3"
    assert "same_as" not in rows["P2"]


@pytest.mark.parametrize("change", [
    {"effort": 100}, {"hour_isk": 300_000_000}, {"cycle_days": 7}, {"ship_every_days": 28},
    {"use_sell_orders": True}, {"use_jita": False}, {"poco_tax_pct": 0},
    {"stack_yield_pct": 50}, {"product_blacklist": ["Water"]},
    {"hub_system": "NEXT"}, {"selected_constellations": [2]},
])
def test_changed_economics_or_effort_never_inherit_a_different_answer(solved, change):
    wide = Settings(max_tier=4)
    wide.update(change)
    weaker = copy.deepcopy(solved)
    weaker["totals"]["isk_per_day"] -= 600_000
    rows = service.whatif_rows([row("narrow", Settings(max_tier=1), solved), row("wide", wide, weaker)])
    assert "same_as" not in rows[1]
    assert rows[1]["totals"] == weaker["totals"]


def test_incomparable_area_limits_and_changed_inputs_stay_independent(solved):
    good = row("near", Settings(max_systems=1, max_jumps=6), solved)
    bad = row("many", Settings(max_systems=3, max_jumps=1), {"error": "No incumbent"})
    assert service.whatif_rows([good, bad])[1] == {"id": "many", "error": "No incumbent"}
    bad["settings"]["max_jumps"] = 6
    bad["assumptions"] = "changed prices, skills, yield, area or drop-off"
    assert "error" in service.whatif_rows([good, bad])[1]
    bad["assumptions"] = good["assumptions"]
    assert service.whatif_rows([good, bad])[1]["same_as"] == "near"


def test_exact_allocations_are_identified_but_tied_different_plans_are_not(solved):
    narrow = row(False, Settings(max_tier=1), solved)
    wide = row(True, Settings(max_tier=4), copy.deepcopy(solved))
    assert service.whatif_rows([narrow, wide])[1]["same_as"] is False
    wide["plan"]["colonies"][0]["planet_id"] = 999  # same totals alone do not establish the same plan
    assert "same_as" not in service.whatif_rows([narrow, wide])[1]


def test_identical_nested_plans_point_to_the_narrowest_answer_regardless_of_order(solved):
    candidates = [row(f"P{tier}", Settings(max_tier=tier), copy.deepcopy(solved)) for tier in (2, 3, 4)]
    forward = service.whatif_rows(candidates)
    backward = list(reversed(service.whatif_rows(list(reversed(candidates)))))
    assert forward == backward
    assert forward[1]["same_as"] == forward[2]["same_as"] == "P2"


def test_infeasible_ownership_fallback_is_not_retained(solved):
    invalid = copy.deepcopy(solved)
    invalid["transfers"] = [{"from": 1, "to": 2}]
    rows = service.whatif_rows([row("own", Settings(max_tier=1), invalid),
                               row("higher", Settings(max_tier=4), {"error": "No incumbent"})])
    assert "error" in rows[1]


def test_fingerprint_uses_actual_dropoff_values_space_and_market_inputs(pi, solved):
    ctx = {"pi": pi, "solve_s": Settings(), "values": {2396: 500}, "dropoff": "HUB", "area": _area()}
    original = whatif.candidate(ctx, solved)["assumptions"]
    for key, replacement in [("values", {2396: 499}), ("dropoff", "NEXT"), ("head_yield", 900),
                             ("books", {"buy": [123]}), ("history_at", 123)]:
        assert whatif.candidate({**ctx, key: replacement}, solved)["assumptions"] != original


def test_api_reuses_native_cache_without_cross_request_substitutions(browser, eve, monkeypatch, pi, solved):  # noqa: F811
    c = browser()
    sso_login(c, eve, new_id(), "Synthetic comparison pilot")
    GATE.clear()
    calls = []

    async def context(pid, settings, persist_default):
        return {"pi": pi, "solve_s": settings, "dropoff": "HUB"}

    def run(ctx):
        calls.append(ctx["solve_s"].max_tier)
        result = copy.deepcopy(solved)
        result["totals"]["isk_per_day"] -= 600_000 if ctx["solve_s"].max_tier == 4 else 0
        return result

    monkeypatch.setattr(service, "planning_context", context)
    monkeypatch.setattr(service, "run_plan", run)
    monkeypatch.setattr(service, "data_stamp", lambda pid: (pid, "synthetic"))
    options = [{"id": "P2", "patch": {"max_tier": 2}}, {"id": "P4", "patch": {"max_tier": 4}}]
    headers = {"X-CSRF-Token": csrf(c)}
    first = c.post("/pi/api/whatif", json={"options": options}, headers=headers)
    assert first.status_code == 200 and first.json()[1]["same_as"] == "P2"
    alone = c.post("/pi/api/whatif", json={"options": options[1:]}, headers=headers)
    assert "same_as" not in alone.json()[0]
    assert alone.json()[0]["totals"]["isk_per_day"] == solved["totals"]["isk_per_day"] - 600_000
    assert sorted(calls) == [2, 4]
    GATE.clear()
