"""First-build checklist: Multibuy list, purchase locations, template compatibility, startup costs
and the build sequence per character and planet. Fake pilots and planets only."""
from __future__ import annotations

from astracore.modules.pi import service, store
from astracore.modules.pi.planner import checklist
from astracore.modules.pi.settings import Settings
from astracore.modules.pi.static_data import pi_rules as R

from test_core import browser, eve, me, new_id, sso_login  # noqa: F401 (fixtures)
from test_planner import TEMPLATES, _plan, _tpl, pi  # noqa: F401 (fixtures)

BARREN, GAS = R.COMMAND_CENTER_TYPES["Barren"], R.COMMAND_CENTER_TYPES["Gas"]
CC_BOOKS = {
    BARREN: {"jita_sell": 100_000.0, "amarr_sell": 120_000.0, "delve_sell": 150_000.0},
    GAS: {"jita_sell": 0.0, "amarr_sell": 0.0, "delve_sell": 0.0},     # nobody sells it: estimate
    2396: {"jita_sell": 600.0, "amarr_sell": 550.0},                   # Biofuels
    2399: {"jita_sell": 700.0},                                        # Precious Metals
}
FILES = {"miner": "miner - Biofuels.json", "factory": "factory - Biocells.json"}


def _templates():
    out = []
    for t in TEMPLATES:
        t = dict(t)
        if t["file"] == FILES["miner"]:
            t.update(planet_type_id=2016, ccu_level=4)           # saved on a Barren planet
        if t["file"] == FILES["factory"]:
            t.update(planet_type_id=2016, ccu_level=5)
        out.append(t)
    return out


def _col(cid, name, planet, ptype, system, kind, action="new", **kw):
    base = {"character_id": cid, "character": name, "planet_id": planet, "planet": f"Planet {planet}",
            "planet_type": ptype, "system": system, "kind": kind, "action": action,
            "tier": 1 if kind == "miner" else 2,
            "product": "Biofuels" if kind == "miner" else "Biocells", "p0": ["Carbon Compounds"] if kind == "miner" else [],
            "template": FILES[kind][:-5], "template_file": FILES[kind], "template_url": "https://example.invalid/t",
            "layout": {"ecus": 1, "heads": 10, "basic": 8, "launchpads": 1} if kind == "miner"
            else {"advanced": 12, "launchpads": 1},
            "min_ccu": 4 if kind == "miner" else 3,
            "in_per_day": {} if kind == "miner" else {"Biofuels": 960.0, "Precious Metals": 960.0}}
    base.update(kw)
    return base


PLAN = {
    "hub": "HUB",
    "colonies": [
        _col(1, "Pilot One", 11, "Barren", "HUB", "miner"),
        _col(1, "Pilot One", 21, "Barren", "NEXT", "factory"),
        _col(1, "Pilot One", 12, "Gas", "HUB", "miner", action="rebuild"),
        _col(2, "Pilot Two", 31, "Barren", "FAR", "miner"),
        _col(2, "Pilot Two", 22, "Gas", "NEXT", "miner", action="keep"),
    ],
    "characters": [{"character_id": 1, "name": "Pilot One", "route": {"order": ["NEXT", "HUB"]}},
                   {"character_id": 2, "name": "Pilot Two", "route": {"order": ["FAR"]}}],
    "removals": [{"character": "Pilot Two", "planet_id": 99, "current": "Water"}],
}
CHARS = [
    {"character_id": 1, "name": "Pilot One", "ccu_level": 5,
     "colonies": [{"planet_id": 12, "upgrade_level": 2}]},
    {"character_id": 2, "name": "Pilot Two", "ccu_level": 3, "colonies": []},
]


def _build(pi, plan=PLAN, local=False, books=CC_BOOKS, **kw):
    return checklist.build(pi, plan, CHARS, books, _templates(), {"cycle_days": 2}, local,
                           {99: {"name": "Old Rock", "system": "FAR"}}, **kw)


def test_multibuy_lists_one_command_center_per_new_planet_by_type(pi):
    k = _build(pi)
    assert k["todo"] == 4 and k["new"] == 3 and k["rebuild"] == 1        # 'keep' is already built
    # the rebuild keeps its command center; the kept colony needs nothing
    assert {c["name"]: c["qty"] for c in k["command_centers"]} == {"Barren Command Center": 3}
    assert k["multibuy"] == "Barren Command Center\t3"
    assert k["cc_m3"] == 3000


def test_purchase_location_prefers_local_market_then_cheapest_hub(pi):
    assert checklist.buy_source(CC_BOOKS[BARREN], local=False) == ("Jita 4-4", 100_000.0)
    assert checklist.buy_source(CC_BOOKS[BARREN], local=True) == (checklist.LOCAL_MARKET, 150_000.0)
    assert checklist.buy_source(CC_BOOKS[2396], local=True) == ("Amarr VIII", 550.0)   # no Delve seller
    assert checklist.buy_source(CC_BOOKS[GAS], local=False) is None


def test_unpriced_command_center_uses_a_labelled_estimate(pi):
    plan = {**PLAN, "colonies": [_col(1, "Pilot One", 12, "Gas", "HUB", "miner")]}
    k = _build(pi, plan)
    cc = k["command_centers"][0]
    assert cc["name"] == "Gas Command Center" and cc["estimated"] and k["costs"]["estimated_cc"]
    assert cc["isk"] == R.COMMAND_CENTER_ISK_ESTIMATE


def test_startup_costs_split_market_from_planetary_interface(pi):
    k = _build(pi)
    costs = k["costs"]
    assert costs["command_centers"] == 3 * 100_000
    # upgrades: new miner 0->4 (P1), new factory 0->5 (P1 trained 5, template saved at 5),
    # rebuild 2->4, Pilot Two's miner can't go past its skill (3) and is flagged instead
    assert costs["upgrades"] == (R.upgrade_isk(0, 4) + R.upgrade_isk(0, 5) + R.upgrade_isk(2, 4)
                                 + R.upgrade_isk(0, 4))
    miner = 45_000 + 8 * 75_000 + 900_000
    factory = 12 * 250_000 + 900_000
    assert costs["structures"] == 3 * miner + factory
    # starter stock: two days of the factory's inputs, priced where they're cheapest
    assert {s["item"]: s["qty"] for s in k["supplies"]} == {"Biofuels": 1920, "Precious Metals": 1920}
    assert costs["supplies"] == 1920 * 550 + 1920 * 700
    assert k["supplies_multibuy"] == "Biofuels\t1920\nPrecious Metals\t1920"
    assert costs["total"] == costs["command_centers"] + costs["upgrades"] + costs["structures"]   # stock is optional


def test_template_compatibility_per_planet(pi):
    k = _build(pi)
    one, two = k["characters"]
    by_planet = {p["planet"]: p for p in one["planets"] + two["planets"]}
    assert by_planet["Planet 11"]["compat"]["status"] == "ok"
    gas = by_planet["Planet 12"]["compat"]                     # Barren template on a Gas planet
    assert gas["status"] == "warn" and "Saved on a Barren planet" in gas["text"]
    blocked = by_planet["Planet 31"]["compat"]                 # skill 3, miner needs 4
    assert blocked["status"] == "bad" and blocked["label"] == "Train first"
    assert k["blocked"] == 1
    missing = _build(pi, {**PLAN, "colonies": [_col(1, "Pilot One", 11, "Barren", "HUB", "miner",
                                                     template_file="gone.json")]})
    assert missing["characters"][0]["planets"][0]["compat"]["label"] == "Template missing"


def test_build_sequence_follows_route_and_never_claims_to_buy(pi):
    k = _build(pi)
    one, two = k["characters"]
    assert [p["planet"] for p in one["planets"]] == ["Planet 21", "Planet 11", "Planet 12"]   # NEXT, then HUB
    assert one["command_centers"] == {"Barren": 2}
    first = one["planets"][0]["steps"]
    assert first[0].startswith("Fly to NEXT with a Barren Command Center")
    assert any("Upgrade the command center from level 0 to 5" in s for s in first)
    assert any("factory - Biocells" in s and "12× Advanced Industry Facility" in s for s in first)
    assert any("starter stock" in s for s in first)
    rebuild = one["planets"][2]["steps"]
    assert "decommission" in rebuild[0] and "level 2 to 4" in rebuild[1]
    miner = one["planets"][1]["steps"]
    assert any("2-day program" in s for s in miner)
    assert two["removals"] == [{"planet": "Old Rock", "system": "FAR", "current": "Water"}]
    text = " ".join(s for ch in k["characters"] for p in ch["planets"] for s in p["steps"]).lower()
    assert "order" not in text and "automatic" not in text


def test_fully_built_plan_needs_no_checklist(pi):
    plan = {**PLAN, "colonies": [dict(c, action="keep") for c in PLAN["colonies"]]}
    assert _build(pi, plan) == {"todo": 0}
    assert checklist.build(pi, {"totals": {}}, CHARS, {}, []) is None


def test_checklist_matches_optimizer_output(pi):
    res = _plan(pi, max_tier=2)
    assert res["colonies"]
    chars = [{"character_id": 1, "name": "A", "ccu_level": 5, "colonies": []},
             {"character_id": 2, "name": "B", "ccu_level": 5, "colonies": []}]
    k = checklist.build(pi, res, chars, CC_BOOKS, TEMPLATES)
    want = {}
    for c in res["colonies"]:
        want[f"{c['planet_type']} Command Center"] = want.get(f"{c['planet_type']} Command Center", 0) + 1
    assert {c["name"]: c["qty"] for c in k["command_centers"]} == want
    assert sum(len(ch["planets"]) for ch in k["characters"]) == len(res["colonies"])


def test_operate_shows_the_checklist_for_the_active_plan(browser, eve, pi, monkeypatch):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Builder")
    pid = me(c)
    plan = {**PLAN, "totals": {"isk_per_day": 1}, "colonies": [
        _col(cid, "Builder", 11, "Barren", "HUB", "miner"),
        _col(cid, "Builder", 21, "Barren", "NEXT", "factory")],
        "characters": [{"character_id": cid, "name": "Builder", "route": {"order": ["HUB", "NEXT"]}}],
        "removals": []}
    store.save_plan_run(pid, "First build", Settings(cycle_days=2), plan, active=True)

    async def fake_ctx(profile_id, *a, **kw):
        chars = [dict(ch, ccu_level=5, colonies=[]) for ch in service.planning_characters(profile_id)]
        return {"chars": chars, "pi": pi, "s": Settings(), "books": CC_BOOKS, "area": None,
                "tpl": _templates()}
    monkeypatch.setattr(service, "planning_context", fake_ctx)
    r = c.get("/pi/operate")
    assert r.status_code == 200
    html = r.text
    assert 'id="first-build"' in html and 'href="#first-build"' in html
    assert "Barren Command Center\t2" in html                       # copyable Multibuy list
    assert "Copy Multibuy list" in html and "can’t buy anything or place market orders" in html
    assert "Optional · Factory starter stock" in html and "Biofuels\t1920" in html
    assert "Fly to HUB with a Barren Command Center" in html


def test_local_market_is_only_credited_when_it_sells_the_command_centers(pi):
    barren = {**PLAN, "colonies": [_col(1, "Pilot One", 12, "Barren", "HUB", "miner")]}
    assert _build(pi, barren, local=True)["cc_local"]                  # Delve lists Barren command centers
    gas = {**PLAN, "colonies": [_col(1, "Pilot One", 12, "Gas", "HUB", "miner")]}
    assert not _build(pi, gas, local=True)["cc_local"]                 # nobody sells Gas ones: estimate, no haul saved
