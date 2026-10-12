"""First-build checklist: Multibuy list, purchase locations, landed cost (price + hauling), template
compatibility, startup costs and the build sequence per character and planet. Fake pilots, planets,
markets and courier tariffs only."""
from __future__ import annotations

import asyncio

import pytest

from astracore.esi.client import ESIError
from astracore.modules.pi import service, store
from astracore.modules.pi.planner import checklist, prices
from astracore.modules.pi.settings import Settings
from astracore.modules.pi.static_data import pi_rules as R
from astracore.modules.pi.static_data import voc

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


def _build(pi, plan=PLAN, local=False, books=CC_BOOKS, settings=None, **kw):
    return checklist.build(pi, plan, CHARS, books, _templates(), settings or {"cycle_days": 2}, local,
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
    assert "Template by DalShooth" in html and 'href="https://example.invalid/t"' in html


def test_local_market_is_only_credited_when_it_sells_the_command_centers(pi):
    barren = {**PLAN, "colonies": [_col(1, "Pilot One", 12, "Barren", "HUB", "miner")]}
    assert _build(pi, barren, local=True)["cc_local"]                  # Delve lists Barren command centers
    gas = {**PLAN, "colonies": [_col(1, "Pilot One", 12, "Gas", "HUB", "miner")]}
    assert not _build(pi, gas, local=True)["cc_local"]                 # nobody sells Gas ones: estimate, no haul saved


def _saved_plan(c, eve, pi, monkeypatch, name="Exporter"):
    """A signed-in pilot with a two-colony plan and a faked (offline) planning context."""
    cid = new_id()
    sso_login(c, eve, cid, name)
    pid = me(c)
    extra = {"out_per_day": {}, "value_per_day": 0, "m3_per_week": 0}
    plan = {**PLAN, "totals": {"isk_per_day": 1, "isk_per_week": 7, "colonies": 2, "slots_total": 6,
                               "m3_per_week": 10, "systems": 2},
            "colonies": [dict(_col(cid, name, 11, "Barren", "HUB", "miner"), **extra),
                         dict(_col(cid, name, 21, "Barren", "NEXT", "factory"), **extra)],
            "characters": [{"character_id": cid, "name": name, "used": 2, "slots": 6,
                            "route": {"order": ["HUB", "NEXT"]}}],
            "removals": [], "transfers": []}

    async def fake_ctx(profile_id, *a, **kw):
        chars = [dict(ch, ccu_level=5, colonies=[]) for ch in service.planning_characters(profile_id)]
        return {"chars": chars, "pi": pi, "s": Settings(), "books": CC_BOOKS, "area": None, "tpl": _templates()}
    monkeypatch.setattr(service, "planning_context", fake_ctx)
    return pid, plan


def test_plan_md_export_includes_the_first_build_checklist(browser, eve, pi, monkeypatch):
    c = browser()
    pid, plan = _saved_plan(c, eve, pi, monkeypatch)
    run = store.save_plan_run(pid, "Exported", Settings(cycle_days=2), plan, active=True)
    r = c.get(f"/pi/export/plan.md?plan={run}")
    assert r.status_code == 200
    md = r.text
    assert "## First build" in md and "can't buy anything or place market orders" in md
    assert "| Goods | Hauling | Landed |" in md
    assert "```\nBarren Command Center\t2\n```" in md                      # Multibuy list, ready to paste
    assert "| Barren Command Center | 2 | Jita 4-4 |" in md
    assert "```\nBiofuels\t1920\nPrecious Metals\t1920\n```" in md          # optional starter stock (2 days)
    assert "Estimated startup cost" in md and "Command center upgrades (wallet, in game)" in md
    assert "Structures (wallet, in game)" in md and "Optional factory starter stock (market)" in md
    assert "#### Exporter" in md and "**Fits**" in md
    assert "    1. Fly to HUB with a Barren Command Center" in md           # per-character steps, route order
    assert md.index("**Planet 11**") < md.index("**Planet 21**")
    assert c.get("/pi/export/plan.md").text == md                         # the active plan by default


def test_shopping_csv_export_lists_purchases_and_in_game_costs(browser, eve, pi, monkeypatch):
    import csv
    import io
    c = browser()
    pid, plan = _saved_plan(c, eve, pi, monkeypatch, "Shopper")
    run = store.save_plan_run(pid, "Shopping", Settings(cycle_days=2), plan, active=False)
    r = c.get(f"/pi/export/shopping.csv?plan={run}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "astracore-pi-shopping.csv" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    cc = [x for x in rows if x["section"] == "command_center"]
    base = {"section": "command_center", "item": "Barren Command Center", "qty": "2", "where": "Jita 4-4",
            "unit_isk": "100000", "isk": "200000", "estimated": "0", "for": ""}
    assert len(cc) == 1 and {k: cc[0][k] for k in base} == base
    # landed cost columns from the hauling check (#23): goods + hauling = landed, with how it gets there
    assert int(cc[0]["landed_isk"]) == int(cc[0]["isk"]) + int(cc[0]["haul_isk"] or 0) and cc[0]["hauling"]
    stock = {x["item"]: x for x in rows if x["section"] == "starter_stock"}
    assert stock["Biofuels"]["qty"] == "1920" and stock["Biofuels"]["where"] == "Amarr VIII"
    assert stock["Biofuels"]["isk"] == str(1920 * 550) and stock["Biofuels"]["for"] == "Planet 21"
    in_game = {x["item"]: int(x["isk"]) for x in rows if x["section"] == "in_game"}
    assert in_game["Command center upgrades"] == R.upgrade_isk(0, 4) + R.upgrade_isk(0, 5)
    assert in_game["Structures"] == (45_000 + 8 * 75_000 + 900_000) + (12 * 250_000 + 900_000)
    assert c.get("/pi/export/shopping.csv?plan=999999").status_code == 404   # unknown plan: never another one


def test_unsaved_plan_exports_its_checklist_with_current_settings(browser, eve, pi, monkeypatch):
    c = browser()
    pid, plan = _saved_plan(c, eve, pi, monkeypatch, "Drafter")
    s = store.load_settings(pid)
    s.cycle_days = 1
    store.save_settings(pid, s)

    async def fake_solve(profile_id, s=None):
        return plan
    monkeypatch.setattr(service, "solve", fake_solve)
    md = c.get("/pi/export/plan.md?current=1").text
    assert "## First build" in md and "Biofuels\t960" in md                # one day of inputs, from settings
    assert "Barren Command Center,2,Jita 4-4" in c.get("/pi/export/shopping.csv?current=1").text


def test_displayed_snapshot_exports_exact_colonies_settings_and_template_selection(browser, eve, pi, monkeypatch):
    from astracore.modules.pi.routes import _result_stamp
    from astracore.modules.pi.static_data import dalshooth

    c = browser()
    pid, plan = _saved_plan(c, eve, pi, monkeypatch, "Candidate exporter")
    settings = store.load_settings(pid)
    settings.cycle_days = 1
    store.save_settings(pid, settings)
    result_id = store.remember_plan_result(pid, settings, plan, _result_stamp(pid))

    async def must_not_solve(*args, **kwargs):
        raise AssertionError("Export must use the displayed snapshot")

    monkeypatch.setattr(service, "solve", must_not_solve)
    packed = []
    monkeypatch.setattr(dalshooth, "zip_pack", lambda files: packed.append(files) or b"synthetic zip")
    query = f"?result={result_id}"
    md = c.get("/pi/export/plan.md" + query)
    assert md.status_code == 200 and "Biofuels\t960" in md.text
    csv = c.get("/pi/export/plan.csv" + query)
    assert csv.status_code == 200 and "Planet 11" in csv.text and "Planet 21" in csv.text
    shopping = c.get("/pi/export/shopping.csv" + query)
    assert shopping.status_code == 200 and "Barren Command Center,2,Jita 4-4" in shopping.text
    assert c.get("/pi/export/templates.zip" + query).content == b"synthetic zip"
    assert packed == [plan.get("templates_needed", [])]
    assert not store.list_plan_runs(pid)  # downloading never saves a candidate


def test_template_authorship_and_source_survive_plan_exports(browser, eve, pi, monkeypatch):
    import csv
    import io
    from astracore.modules.pi.static_data import dalshooth

    c = browser()
    pid, plan = _saved_plan(c, eve, pi, monkeypatch, "Credit exporter")
    source = "https://github.com/DalShooth/EVE_PI_Templates/blob/main/PlanetaryInteractionTemplates/Example.json"
    plan["colonies"][0]["template_url"] = source
    plan["colonies"][1].pop("template_url", None)   # older saved results have no per-file URL
    run = store.save_plan_run(pid, "Credited plan", Settings(), plan, active=False)
    md = c.get(f"/pi/export/plan.md?plan={run}")
    assert md.status_code == 200
    assert f"[Template by DalShooth]({source})" in md.text
    assert f"[Template by DalShooth]({dalshooth.REPO_URL})" in md.text
    exported = c.get(f"/pi/export/plan.csv?plan={run}")
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert [row["template_author"] for row in rows] == ["DalShooth", "DalShooth"]
    assert [row["template_source"] for row in rows] == [source, dalshooth.REPO_URL]
    assert [row["planet"] for row in rows] == [col["planet"] for col in plan["colonies"]]


def test_operate_links_the_checklist_exports(browser, eve, pi, monkeypatch):
    c = browser()
    pid, plan = _saved_plan(c, eve, pi, monkeypatch, "Linker")
    run = store.save_plan_run(pid, "Linked", Settings(cycle_days=2), plan, active=True)
    html = c.get("/pi/operate").text
    assert f'href="/pi/export/shopping.csv?plan={run}"' in html and f'href="/pi/export/plan.md?plan={run}"' in html


# --------------------------------------------------------------------------- landed cost: price + hauling
JITA_ROUTE = {"origin": "7G-QIG", "dest": voc.JITA, "min_fee": 10_000_000, "per_m3": 1000, "collateral_pct": 1.0,
              "max_m3": 165_000}
AMARR_ROUTE = {"origin": "7G-QIG", "dest": voc.AMARR, "min_fee": 20_000_000, "per_m3": 650, "collateral_pct": 1.0,
               "max_m3": 165_000}
ROUTES = [JITA_ROUTE, AMARR_ROUTE]                      # VOC lists Delve -> hub only, like the fallback tariff
AREA = {"systems": {
    "1": {"system_id": 1, "name": "7G-QIG", "region": "Delve", "neighbours": [2], "planets": []},
    "2": {"system_id": 2, "name": "1DQ1-A", "region": "Delve", "neighbours": [1, 3], "planets": []},
    "3": {"system_id": 3, "name": "NEXT", "region": "Delve", "neighbours": [2], "planets": []}}}
DELVE_PLAN = {**PLAN, "hub": "7G-QIG"}


def _cc_only(ptype="Barren", n=3, hub="7G-QIG"):
    cols = [_col(1, "Pilot One", 40 + i, ptype, "HUB", "miner") for i in range(n)]
    return {**PLAN, "hub": hub, "colonies": cols, "removals": []}


def test_hauling_routes_use_voc_and_flag_an_assumed_return_tariff():
    h = checklist.hauling_routes("7G-QIG", AREA, ROUTES)
    assert h["jita"]["status"] == "courier" and h["jita"]["to"] == "7G-QIG" and h["jita"]["approx"]
    both_ways = ROUTES + [{**JITA_ROUTE, "origin": voc.JITA, "dest": "7G-QIG"}]   # site said bidirectional
    assert not checklist.hauling_routes("7G-QIG", AREA, both_ways)["jita"]["approx"]
    assert checklist.hauling_routes("Jita", None, ROUTES)["jita"]["status"] == "free"
    assert checklist.hauling_routes("Somewhere", None, ROUTES)["amarr"]["status"] == "unpriced"


def test_delve_seller_beats_a_cheaper_hub_once_the_courier_is_counted(pi):
    k = _build(pi, _cc_only(), local=True, area=AREA, voc_routes=ROUTES)
    cc = k["command_centers"][0]
    # Jita: 3 x 100k + a 10M minimum fee; Delve: 3 x 150k, no courier
    assert cc["where"] == checklist.LOCAL_MARKET and cc["isk"] == 450_000 and cc["haul_isk"] == 0
    assert k["costs"]["hauling"] == 0 and k["hauling"]["contracts"] == []


def test_courier_fee_is_shown_separately_and_counts_in_the_startup_cost(pi):
    books = {**CC_BOOKS, BARREN: {"jita_sell": 100_000.0, "amarr_sell": 120_000.0}}     # Delve doesn't list it
    k = _build(pi, _cc_only(), local=True, books=books, area=AREA, voc_routes=ROUTES)
    cc = k["command_centers"][0]
    assert cc["where"] == "Jita 4-4" and cc["isk"] == 300_000          # goods
    assert cc["haul_isk"] == 10_000_000 and cc["landed_isk"] == 10_300_000   # Jita's minimum fee
    assert k["costs"]["hauling"] == 10_000_000
    assert k["costs"]["total"] == (k["costs"]["command_centers"] + k["costs"]["hauling"] + k["costs"]["upgrades"]
                                   + k["costs"]["structures"])
    (contract,) = k["hauling"]["contracts"]
    assert contract["from"] == "Jita 4-4" and contract["to"] == "7G-QIG" and contract["m3"] == 3000
    assert contract["approx"] and k["hauling"]["approx"]                  # return direction assumed


def test_starter_stock_rides_along_and_a_lower_price_can_lose_to_a_higher_minimum_fee(pi):
    books = {**CC_BOOKS, BARREN: {"jita_sell": 100_000.0}}
    k = _build(pi, DELVE_PLAN, local=True, books=books, area=AREA, voc_routes=ROUTES)
    stock = {s["item"]: s for s in k["supplies"]}
    # Biofuels are cheaper in Amarr (550 vs 600), but Amarr's 20M minimum fee isn't worth it
    assert stock["Biofuels"]["where"] == "Jita 4-4"
    cc_m3, cc_coll = 3 * R.COMMAND_CENTER_M3, 3 * 100_000
    st_m3 = 1920 * (pi.volume(2396) + pi.volume(2399))
    st_coll = 1920 * 600 + 1920 * 700
    extra = voc.courier_fee(JITA_ROUTE, cc_m3 + st_m3, cc_coll + st_coll) - voc.courier_fee(JITA_ROUTE, cc_m3, cc_coll)
    assert k["costs"]["supplies_hauling"] == round(extra)               # only what it adds to the same contract
    assert sum(s["haul_isk"] for s in k["supplies"]) == pytest.approx(extra, abs=2)
    shared = [c for c in k["hauling"]["contracts"] if c["section"] == "starter_stock"]
    assert shared and shared[0]["shared"]


def test_unknown_courier_route_keeps_the_local_preference_and_says_hauling_isnt_priced(pi):
    k = _build(pi, {**_cc_only(hub="Far Away")}, local=False, area=None, voc_routes=ROUTES)
    cc = k["command_centers"][0]
    assert cc["where"] == "Jita 4-4" and cc["haul_isk"] == 0 and "not priced" in cc["haul_note"]
    assert k["hauling"]["self_haul"] == ["Jita 4-4"] and k["costs"]["hauling"] == 0


def test_delve_offer_names_the_station_and_the_jumps(pi):
    books = {**CC_BOOKS, BARREN: {**CC_BOOKS[BARREN], "delve_sell_at": {
        "location_id": 60_000_001, "system_id": 2, "station": "1DQ1-A - Test Station", "system": "1DQ1-A",
        "units": 2, "structure": False}}}
    cc = _build(pi, _cc_only(), local=True, books=books, area=AREA, voc_routes=ROUTES)["command_centers"][0]
    assert cc["pickup"]["station"] == "1DQ1-A - Test Station" and cc["pickup"]["jumps"] == 1
    assert "1 jump from 7G-QIG" in cc["pickup"]["text"] and cc["pickup"]["partial"]   # 2 there, 3 needed
    books[BARREN]["delve_sell_at"] = {"location_id": 1_000_000_000_123, "system_id": 3, "station": None,
                                      "system": None, "units": 5, "structure": True}
    free_time = {"cycle_days": 2, "hour_isk": 0}       # time worth nothing: the cheaper Delve price wins
    cc = _build(pi, _cc_only(), local=True, books=books, area=AREA, voc_routes=ROUTES,
                settings=free_time)["command_centers"][0]
    assert cc["pickup"]["text"].startswith("a player structure in NEXT (2 jumps")    # system from the area


def test_buying_walks_the_sell_depth_and_flags_a_short_book():
    book = {"jita_sell": 100.0, "jita_sell_depth": [[100.0, 10], [120.0, 10]]}
    o = checklist.offers(book, 15, local=False)["jita"]
    assert o["unit"] == pytest.approx((10 * 100 + 5 * 120) / 15) and o["short"] == 0
    assert checklist.offers(book, 30, local=False)["jita"]["short"] == 10


def test_courier_splits_above_voc_size_limit():
    h = {"route": JITA_ROUTE}
    fee, n = checklist.courier_cost(h, 200_000, 0)
    assert n == 2 and fee == 2 * voc.courier_fee(JITA_ROUTE, 100_000, 0)


def test_cheapest_delve_order_location_is_named_without_auth(monkeypatch):
    sells = [{"price": 120.0, "location_id": 60_000_001, "system_id": 2, "volume_remain": 5},
             {"price": 100.0, "location_id": 1_000_000_000_123, "system_id": 3, "volume_remain": 4},
             {"price": 100.0, "location_id": 1_000_000_000_123, "system_id": 3, "volume_remain": 1}]
    at = prices.cheapest_at(sells)
    assert at["location_id"] == 1_000_000_000_123 and at["units"] == 5 and at["structure"]
    npc = prices.cheapest_at(sells[:1])
    asked = []

    async def names(esi, ids):
        asked.append(set(ids))
        return {2: "1DQ1-A", 3: "NEXT", 60_000_001: "1DQ1-A - Test Station"}
    monkeypatch.setattr(prices.public, "ids_to_names", names)
    asyncio.run(prices.name_locations(None, [at, npc, None]))
    assert asked == [{2, 3, 60_000_001}]                             # structure ids never go to /universe/names
    assert (at["station"], at["system"]) == (None, "NEXT")
    assert (npc["station"], npc["system"]) == ("1DQ1-A - Test Station", "1DQ1-A")

    async def down(esi, ids):
        raise ESIError("down")
    monkeypatch.setattr(prices.public, "ids_to_names", down)
    later = prices.cheapest_at(sells[:1])
    asyncio.run(prices.name_locations(None, [later]))
    assert later["station"] is None and later["system"] is None       # unnamed, never a crash


def test_operate_shows_landed_cost_and_hauling(browser, eve, pi, monkeypatch):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Hauler")
    pid = me(c)
    plan = {**PLAN, "hub": "7G-QIG", "totals": {"isk_per_day": 1}, "colonies": [
        _col(cid, "Hauler", 11, "Barren", "HUB", "miner")],
        "characters": [{"character_id": cid, "name": "Hauler", "route": {"order": ["HUB"]}}], "removals": []}
    store.save_plan_run(pid, "Haul", Settings(cycle_days=2), plan, active=True)
    books = {**CC_BOOKS, BARREN: {"jita_sell": 100_000.0}}

    async def fake_ctx(profile_id, *a, **kw):
        chars = [dict(ch, ccu_level=5, colonies=[]) for ch in service.planning_characters(profile_id)]
        return {"chars": chars, "pi": pi, "s": Settings(), "books": books, "area": AREA, "tpl": _templates()}
    monkeypatch.setattr(service, "planning_context", fake_ctx)
    monkeypatch.setattr(voc, "routes_cached", lambda: ROUTES)
    html = c.get("/pi/operate").text
    assert "<th>Landed</th>" in html and "Hauling to 7G-QIG" in html
    assert "VOC courier Jita 4-4 → 7G-QIG" in html and "Approximation:" in html


def test_your_own_delve_trip_is_priced_at_your_hour_value(pi):
    books = {**CC_BOOKS, BARREN: {**CC_BOOKS[BARREN], "delve_sell_at": {
        "location_id": 1_000_000_000_123, "system_id": 3, "station": None, "system": None, "units": 5,
        "structure": True}}}
    cheap_time = _build(pi, _cc_only(), local=True, books=books, area=AREA, voc_routes=ROUTES,
                        settings={"cycle_days": 2, "hour_isk": 0})["command_centers"][0]
    assert cheap_time["where"] == checklist.LOCAL_MARKET
    assert cheap_time["trip"]["jumps"] == 2 and "your trip: 2 jumps each way" in cheap_time["haul_note"]
    # 2 jumps each way at 1.5 min + handling: at 90M ISK/h that trip outweighs the courier for 3 command centers
    dear_time = _build(pi, _cc_only(), local=True, books=books, area=AREA, voc_routes=ROUTES,
                       settings={"cycle_days": 2, "hour_isk": 90e6})["command_centers"][0]
    assert dear_time["where"] != checklist.LOCAL_MARKET
    trip = checklist.own_trip(2, 3000, 60e6)
    assert trip["minutes"] == 2 * 2 * checklist.MIN_PER_JUMP + 1.0 and trip["isk"] == round(trip["minutes"] * 1e6)


def test_a_seller_at_an_unknown_distance_doesnt_beat_a_priced_courier(pi):
    books = {**CC_BOOKS, BARREN: {**CC_BOOKS[BARREN], "delve_sell_at": {
        "location_id": 60_000_009, "system_id": 999, "station": "FAR - Station", "system": "FAR",
        "units": 5, "structure": False}}}
    cc = _build(pi, _cc_only(), local=True, books=books, area=AREA, voc_routes=ROUTES,
                settings={"cycle_days": 2, "hour_isk": 0})["command_centers"][0]
    assert cc["where"] != checklist.LOCAL_MARKET and cc["haul_isk"] > 0    # outside the area: courier instead


def test_a_courier_fee_above_the_goods_value_suggests_flying_it_yourself(pi):
    k = _build(pi, _cc_only(), local=False, area=AREA, voc_routes=ROUTES)
    c = k["hauling"]["contracts"][0]
    assert c["fee"] > c["collateral"] and c["self_haul_trips"] == 1      # 3,000 m3: one DST trip
