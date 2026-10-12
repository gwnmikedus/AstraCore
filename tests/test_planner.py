"""Offline tests: PI rules, template-based setups and the suggestion engine.

Uses a hand-built subset of the SDE and fake template metadata, so no network is needed.
"""
from __future__ import annotations

import pytest

from astracore.modules.pi.settings import HOUR_DEFAULTS, Settings, hour_value, time_weights
from astracore.modules.pi.planner import optimizer, setups
from astracore.modules.pi.static_data import pi_rules as R
from astracore.modules.pi.static_data.sde_loader import build_from_rows

# --- minimal SDE fixture: 4 P0 -> 4 P1 -> 2 P2 ------------------------------------------
P0 = {"Carbon Compounds": 2288, "Noble Metals": 2270, "Ionic Solutions": 2309, "Aqueous Liquids": 2268}
P1 = {"Biofuels": 2396, "Precious Metals": 2399, "Electrolytes": 2390, "Water": 3645}
P2 = {"Biocells": 2329, "Coolant": 9832}
SCHEMS = [
    (121, "Biofuels", 1800, {2288: 3000}, (2396, 20)),
    (122, "Precious Metals", 1800, {2270: 3000}, (2399, 20)),
    (123, "Electrolytes", 1800, {2309: 3000}, (2390, 20)),
    (124, "Water", 1800, {2268: 3000}, (3645, 20)),
    (70, "Biocells", 3600, {2396: 40, 2399: 40}, (2329, 5)),
    (66, "Coolant", 3600, {2390: 40, 3645: 40}, (9832, 5)),
]


@pytest.fixture()
def pi():
    schem_rows = [{"schematicID": str(i), "schematicName": n, "cycleTime": str(c)} for i, n, c, _, _ in SCHEMS]
    map_rows = []
    for i, _, _, ins, (out, q) in SCHEMS:
        for t, qty in ins.items():
            map_rows.append({"schematicID": str(i), "typeID": str(t), "quantity": str(qty), "isInput": "1"})
        map_rows.append({"schematicID": str(i), "typeID": str(out), "quantity": str(q), "isInput": "0"})
    data = build_from_rows(schem_rows, map_rows)
    for n, t in {**P0, **P1, **P2}.items():
        data.items[t]["name"] = n
    data._index()
    data.p0_by_planet = {"Barren": [2288, 2270, 2268], "Gas": [2309, 2268],
                         "Storm": [2309, 2268], "Temperate": [2288, 2268]}
    return data


def _tpl(kind, product_id, name, sec=None, **counts):
    base = dict(kind=kind, sec=sec, product_name=name, file=f"{kind} - {name}.json",
                path=f"PlanetaryInteractionTemplates/{kind} - {name}.json", product_id=product_id,
                ecus=0, heads=0, basic=0, advanced=0, hightech=0, launchpads=1, storage=0)
    base.update(counts)
    return base


TEMPLATES = [
    _tpl("miner", 2396, "Biofuels", "00", ecus=1, heads=10, basic=8),
    _tpl("miner", 2399, "Precious Metals", "00", ecus=1, heads=10, basic=8),
    _tpl("miner", 2390, "Electrolytes", "00", ecus=1, heads=10, basic=8),
    _tpl("miner", 3645, "Water", "00", ecus=1, heads=10, basic=8),
    _tpl("factory", 2329, "Biocells", advanced=12),
    _tpl("factory", 9832, "Coolant", advanced=12),
]


def test_tiers(pi):
    assert pi.tier(2288) == 0 and pi.tier(2396) == 1 and pi.tier(2329) == 2


def test_real_planet_p0_table_is_complete():
    for ptype, p0s in R.P0_BY_PLANET.items():
        assert len(p0s) == (0 if ptype == "Shattered" else 5)


def test_only_template_setups(pi):
    res = setups.for_planet(pi, "Barren", 1000, TEMPLATES, -0.5, max_tier=4, factory_ok=True)
    assert res and all(x.template for x in res)
    kinds = {(x.kind, pi.name(x.product)) for x in res}
    assert ("miner", "Biofuels") in kinds and ("miner", "Water") in kinds
    assert ("factory", "Biocells") in kinds
    # No miner template for a P1 -> nothing suggested for it
    no_tpl = setups.for_planet(pi, "Barren", 1000, [t for t in TEMPLATES if t["product_name"] != "Water"],
                               -0.5, max_tier=1, factory_ok=False)
    assert "Water" not in {pi.name(x.product) for x in no_tpl}


def test_miner_output_capped_by_template_factories(pi):
    lo = setups.miners(pi, "Barren", 500, TEMPLATES, -0.5)[0].out
    hi = setups.miners(pi, "Barren", 1_000_000, TEMPLATES, -0.5)[0].out
    assert list(hi.values())[0] == pytest.approx(8 * 40 * 24)   # 8 basic factories max
    assert list(lo.values())[0] < list(hi.values())[0]


def test_max_tier_1_means_no_factories(pi):
    res = setups.for_planet(pi, "Barren", 1000, TEMPLATES, -0.5, max_tier=1, factory_ok=True)
    assert all(x.kind == "miner" for x in res)


def test_time_weights_follow_the_value_of_your_time():
    passive, balanced, most = (time_weights(Settings(effort=e)) for e in (0, 50, 100))
    assert passive["isk_per_m3"] > balanced["isk_per_m3"] > most["isk_per_m3"] == 0
    assert most["isk_per_system"] == most["isk_per_factory"] == 0
    own = time_weights(Settings(effort=0, hour_isk=0))           # the pilot's own value wins over the goal
    assert own == most
    double = time_weights(Settings(effort=50, hour_isk=2 * HOUR_DEFAULTS["balanced"]))
    assert double["isk_per_m3"] == 2 * balanced["isk_per_m3"]
    # the same minutes as the time estimate: 20 min per 60,000 m3, 5 min per system per pickup round,
    # 3 min per factory restock per extractor cycle
    s = Settings(effort=50, hour_isk=60e6, ship_every_days=7, cycle_days=3)
    w = time_weights(s)
    assert w["isk_per_m3"] == 1e6 * 20 / 60000
    assert w["isk_per_system"] == 1e6 * 5 / 7 and w["isk_per_factory"] == 1e6 * 3 / 3
    assert hour_value(Settings(effort=30)) == HOUR_DEFAULTS["balanced"]


def test_valuing_time_more_never_plans_more_work(pi):
    def run(hour):
        return _plan(pi, effort=50, hour_isk=hour, max_tier=2)["totals"]
    cheap, dear = run(0), run(5e9)
    assert dear["m3_per_week"] <= cheap["m3_per_week"] and dear["systems"] <= cheap["systems"]
    assert dear["isk_per_day"] <= cheap["isk_per_day"]


def _area():
    def planet(pid, t):
        return {"planet_id": pid, "name": f"P{pid}", "type": t, "type_id": 0}
    return {"systems": {
        "1": {"system_id": 1, "name": "HUB", "security": -0.6, "constellation_id": 1, "constellation": "C",
              "planets": [planet(11, "Barren"), planet(12, "Gas"), planet(13, "Temperate")], "neighbours": [2]},
        "2": {"system_id": 2, "name": "NEXT", "security": -0.6, "constellation_id": 1, "constellation": "C",
              "planets": [planet(21, "Barren"), planet(22, "Storm")], "neighbours": [1, 3]},
        "3": {"system_id": 3, "name": "FAR", "security": -0.6, "constellation_id": 1, "constellation": "C",
              "planets": [planet(31, "Barren")], "neighbours": [2]},
    }}


CHARS = [
    {"character_id": 1, "name": "A", "slots": 2, "ccu_level": 5, "colonies": []},
    {"character_id": 2, "name": "B", "slots": 2, "ccu_level": 5, "colonies": []},
]
PRICES = {2329: 10000.0, 9832: 9000.0, 2396: 500.0, 2399: 500.0, 2390: 500.0, 3645: 500.0}


def _plan(pi, chars=CHARS, prices=PRICES, **kw):
    s = Settings(hub_system="HUB", max_jumps=1, max_systems=0, effort=100, max_tier=1)
    for k, v in kw.items():
        setattr(s, k, v)
    area = _area()
    systems = {int(k): v for k, v in area["systems"].items()}
    return optimizer.plan(pi, s, area, systems, chars, prices, TEMPLATES)


def test_respects_slots_planets_and_jumps(pi):
    res = _plan(pi)
    assert "error" not in res, res
    cols = res["colonies"]
    assert len(cols) == 4
    assert {c["planet_id"] for c in cols} <= {11, 12, 13, 21, 22}   # FAR is 2 jumps away
    assert len({c["planet_id"] for c in cols}) == 4                  # 1 colony per planet
    for cid in (1, 2):
        assert sum(c["character_id"] == cid for c in cols) <= 2
    assert all(c["template_file"] for c in cols)


def test_max_systems_limits_spread(pi):
    res = _plan(pi, max_systems=1)
    assert res["totals"]["systems"] == 1


def test_low_ccu_character_excluded(pi):
    res = _plan(pi, chars=CHARS + [{"character_id": 3, "name": "Low", "slots": 6, "ccu_level": 1, "colonies": []}])
    assert all(c["character"] != "Low" for c in res["colonies"])
    assert any("Low" in w for w in res["warnings"])
    assert res["totals"]["slots_total"] == sum(c["slots"] for c in CHARS)
    assert res["totals"]["slots_total"] == sum(c["slots"] for c in res["characters"])


def test_no_transfers_when_cross_character_off(pi):
    chars = [{"character_id": i, "name": f"C{i}", "slots": 3, "ccu_level": 5, "colonies": []} for i in (1, 2)]
    prices = {**PRICES, 2329: 400000.0}  # make factories very attractive
    res = _plan(pi, chars=chars, prices=prices, max_tier=2, cross_character=False, max_jumps=2)
    assert res["transfers"] == []
    for f in [c for c in res["colonies"] if c["kind"] == "factory"]:
        same = [c for c in res["colonies"] if c["character_id"] == f["character_id"] and c["kind"] == "miner"]
        assert {k for k in f["in_per_day"]} <= {k for c in same for k in c["out_per_day"]}


def test_factory_never_consumes_more_than_produced(pi):
    chars = [{"character_id": i, "name": f"C{i}", "slots": 3, "ccu_level": 5, "colonies": []} for i in (1, 2)]
    prices = {**PRICES, 2329: 400000.0}
    res = _plan(pi, chars=chars, prices=prices, max_tier=2, cross_character=True, max_jumps=2)
    assert any(c["kind"] == "factory" for c in res["colonies"])
    produced, consumed = {}, {}
    for c in res["colonies"]:
        for k, v in c["out_per_day"].items():
            produced[k] = produced.get(k, 0) + v
        for k, v in c["in_per_day"].items():
            consumed[k] = consumed.get(k, 0) + v
    for k, v in consumed.items():
        assert produced.get(k, 0) + 1e-3 >= v


def test_existing_colony_kept_on_same_character(pi):
    chars = [dict(CHARS[0], colonies=[{"planet_id": 11, "pins": [{"schematic_id": 121}]}]), CHARS[1]]
    res = _plan(pi, chars=chars, prices={**PRICES, 2396: 5000.0})
    kept = [c for c in res["colonies"] if c["action"] == "keep"]
    assert kept and kept[0]["character_id"] == 1 and kept[0]["planet_id"] == 11


def test_removals_name_the_planet(pi):
    # a colony on FAR (2 jumps, out of reach) can't be kept, so it's listed by planet name, not id
    chars = [dict(CHARS[0], colonies=[{"planet_id": 31, "pins": [{"schematic_id": 121}]}]), CHARS[1]]
    res = _plan(pi, chars=chars)
    assert {(r["planet_id"], r["planet"], r["system"]) for r in res["removals"]} == {(31, "P31", "FAR")}


def test_ccu4_character_gets_only_fitting_templates(pi):
    tpls = [dict(t) for t in TEMPLATES]
    for t in tpls:
        if t["kind"] == "miner":
            t["heads"], t["ecus"], t["basic"] = 16, 2, 4    # LS-style miner: needs CCU 5
    assert setups.template_min_ccu(tpls[0]) == 5
    assert setups.template_min_ccu(TEMPLATES[0]) == 4
    chars = [{"character_id": 1, "name": "Four", "slots": 4, "ccu_level": 4, "colonies": []}]
    s = Settings(hub_system="HUB", max_jumps=1, max_systems=0, effort=100, max_tier=1)
    area = _area()
    res = optimizer.plan(pi, s, area, {int(k): v for k, v in area["systems"].items()}, chars, PRICES, tpls)
    assert res.get("colonies", []) == [] or all(c["min_ccu"] <= 4 for c in res["colonies"])


# --- selling ------------------------------------------------------------------------------
from astracore.modules.pi.planner import selling  # noqa: E402

BOOKS = {
    2396: {"jita_buy": 800.0, "jita_sell": 850.0, "amarr_buy": 790.0, "amarr_sell": 840.0, "delve_buy": 150.0},
    2329: {"jita_buy": 10000.0, "jita_sell": 11000.0, "amarr_buy": 9500.0, "amarr_sell": 10500.0, "delve_buy": 7000.0},
}


def test_p1_is_never_bought_back_and_courier_cost_is_deducted(pi):
    s = Settings()
    ch = selling.channel_values(pi, s, BOOKS, 2396, "7G-QIG")
    assert "buyback" not in ch                                  # VOC refuses P1
    vol = pi.volume(2396)
    assert ch["jita_buy"] == pytest.approx(800 * (1 - s.sales_tax_pct / 100) - (vol * 1000 + 800 * 0.01))
    cheap = {2396: {"jita_buy": 400.0, "amarr_buy": 390.0}}
    ch2 = selling.channel_values(pi, Settings(use_local=False), cheap, 2396, "7G-QIG")
    assert "jita_buy" not in ch2                     # costs more to haul to Jita than it's worth
    assert 0 < ch2["amarr_buy"] < 0.4 * 390          # Amarr is cheaper per m3 but still eats most of it


def test_p2_buyback_is_90_percent_of_jita_buy(pi):
    ch = selling.channel_values(pi, Settings(), BOOKS, 2329, "7G-QIG")
    assert ch["buyback"] == pytest.approx(9000.0)


def test_disabled_channels_and_outside_delve(pi):
    s = Settings(use_buyback=False, use_local=False, use_amarr=False)
    assert set(selling.channel_values(pi, s, BOOKS, 2329, "7G-QIG")) == {"jita_buy"}
    # stock already in Jita: no courier cost, no buyback/local
    ch = selling.channel_values(pi, Settings(), BOOKS, 2329, "Jita", local=False)
    assert ch["jita_buy"] == pytest.approx(10000 * (1 - Settings().sales_tax_pct / 100))
    assert "buyback" not in ch and "local_buy" not in ch


def test_small_courier_batch_falls_back_or_holds(pi):
    s = Settings(use_buyback=True)
    plan = selling.sell_plan(pi, s, BOOKS, "7G-QIG", {2329: 10}, per_day=False)   # 10 units: tiny
    chans = {b["channel"] for b in plan["batches"] if not b.get("hold")}
    assert "jita_buy" not in chans                    # 10M minimum fee would eat it
    big = selling.sell_plan(pi, Settings(use_buyback=False, use_local=False, use_amarr=False),
                            BOOKS, "7G-QIG", {2329: 100_000}, per_day=False)
    b = big["batches"][0]
    assert b["channel"] == "jita_buy" and b["contract"]["reward"] >= 10_000_000
    assert b["contract"]["collateral"] == pytest.approx(100_000 * 10000)


# --- operate --------------------------------------------------------------------------------
from datetime import datetime, timedelta, timezone  # noqa: E402

from astracore import db  # noqa: E402
from astracore.esi import character as esi_char  # noqa: E402
from astracore.modules.pi.planner import operate  # noqa: E402


def _iso(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_operate_flow(pi):
    db.kv_set(esi_char.LOCATIONS_KEY, {"1": {"name": "7G-QIG - Keepstar", "system": "7G-QIG", "system_id": 1}})
    ch = {
        "character_id": 1, "name": "A",
        "colonies": [
            {"planet_id": 11, "planet_type": "barren", "pins": [
                {"extractor_details": {"product_type_id": 2288, "heads": [{}] * 10}, "expiry_time": _iso(-2)},
                {"contents": [{"type_id": 2396, "amount": 5000}]},                       # Biofuels ready
            ]},
            {"planet_id": 12, "planet_type": "gas", "pins": [
                {"schematic_id": 70},                                                   # Biocells factory
                {"contents": [{"type_id": 2396, "amount": 100}, {"type_id": 2399, "amount": 5000}]},
            ]},
        ],
        "assets": [{"type_id": 2329, "qty": 100_000, "location_id": 1, "flag": "Hangar"}],
        "contracts": [
            {"contract_id": 7, "type": "courier", "status": "in_progress", "voc": True, "collateral": 5e8,
             "reward": 1.2e7, "volume": 75000, "date_issued": _iso(-30), "start_location_id": 1, "end_location_id": 1},
            {"contract_id": 8, "type": "item_exchange", "status": "finished", "voc": True, "price": 9e7,
             "date_issued": _iso(-40), "items": [{"type_id": 2329, "qty": 10000}]},
        ],
        "orders": [{"order_id": 1, "type_id": 2329, "price": 12000.0, "volume_remain": 50, "volume_total": 100,
                    "location_id": 1, "is_buy_order": False}],
        "wallet": {"balance": 1e9, "sales": [{"date": _iso(-5), "type_id": 2329, "qty": 10, "unit_price": 10000.0}],
                   "journal": [{"date": _iso(-20), "ref_type": "contract_price", "amount": 9e7, "context_id": 8},
                               {"date": _iso(-30), "ref_type": "contract_reward", "amount": -1.2e7, "context_id": 7}]},
    }
    st = operate.colonies_status(pi, [ch], None)
    assert st["extractors"][0]["state"] == "expired"
    assert st["pickups"][0]["items"] == {"Biofuels": 5000}
    assert {r["item"] for r in st["restock"]} == {"Biofuels"}       # 100 Biofuels < 2 days for a Biocells factory

    stock = operate.hangar_stock(pi, Settings(), BOOKS, [ch])
    assert stock[0]["items"] == {"Biocells": 100000}
    assert stock[0]["plan"]["batches"][0]["channel"] == "buyback"   # P2 in Delve -> buyback pays most here

    pipe = operate.pipeline(pi, BOOKS, [ch])
    assert pipe["in_transit_value"] == 5e8 and pipe["courier"][0]["status"] == "in_progress"
    assert pipe["orders"][0]["value"] == 12000.0 * 50 and pipe["orders"][0]["undercut"] is False

    earned = operate.earnings(pi, [ch], days=7)
    assert earned["market_sales"] == 100000 and earned["buyback"] == 9e7 and earned["courier_costs"] == 1.2e7
    assert earned["net"] == 100000 + 9e7 - 1.2e7


# --- review 2026-10-10 fixes ------------------------------------------------------------------
from astracore.modules.pi.intel import richness as rich  # noqa: E402
from astracore.modules.pi.planner import skills  # noqa: E402
from astracore.modules.pi.static_data import extraction  # noqa: E402


def test_cycle_factor_follows_ccp_formula():
    assert extraction.cycle_factor(3) == pytest.approx(1.0)
    assert 1.45 < extraction.cycle_factor(1) < 1.6        # shorter programs: more per hour
    assert 0.6 < extraction.cycle_factor(7) < 0.67
    assert extraction.cycle_seconds(47.5) == 1800 and extraction.cycle_seconds(24) == 900


def _extractor(qty, cycle_s, days, heads=10):
    install = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return {"extractor_details": {"heads": [{}] * heads, "cycle_time": cycle_s, "qty_per_cycle": qty,
                                  "product_type_id": 2288},
            "install_time": install.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expiry_time": (install + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_calibration_uses_bar_width_and_decay():
    # Same base value per 15-minute bar, different program lengths -> same normalised head yield.
    one = rich.calibrate_head_yield({1: [{"planet_id": 5, "pins": [_extractor(4000, 900, 1)]}]}, {5: 0.0})
    three = rich.calibrate_head_yield({1: [{"planet_id": 5, "pins": [_extractor(4000, 3600, 3)]}]}, {5: 0.0})
    assert one == pytest.approx(three, rel=0.06)
    real = extraction.avg_per_hour(4000, 3600, 3 * 86400) / 10
    assert three == pytest.approx(real, rel=0.01)       # richness 1.0 at 0.0 sec, 3-day program


def test_measured_richness_per_planet():
    cols = {1: [{"planet_id": 5, "pins": [_extractor(4000, 3600, 3)]},
                {"planet_id": 6, "pins": [_extractor(8000, 3600, 3)]}]}
    base = extraction.avg_per_hour(4000, 3600, 3 * 86400) / 10
    m = rich.measured_richness(cols, base)
    assert m[5] == pytest.approx(1.0, abs=0.02) and m[6] > 1.8


def test_stacked_colonies_share_deposits(pi):
    chars = [{"character_id": i, "name": f"C{i}", "slots": 1, "ccu_level": 5, "colonies": []} for i in (1, 2, 3)]
    one_planet = {"systems": {"1": {"system_id": 1, "name": "HUB", "security": -0.6, "constellation_id": 1,
                                    "constellation": "C", "planets": [{"planet_id": 11, "name": "P11",
                                                                       "type": "Gas", "type_id": 13}],
                                    "neighbours": []}}}
    s = Settings(hub_system="HUB", max_jumps=0, max_systems=0, effort=100, max_tier=1, per_planet=3,
                 stack_yield_pct=50.0)
    res = optimizer.plan(pi, s, one_planet, {1: one_planet["systems"]["1"]}, chars, {2390: 500.0, 3645: 500.0},
                         TEMPLATES, head_yield=300)
    cols = res["colonies"]
    assert len(cols) == 3
    by_product = {}
    for c in cols:
        by_product.setdefault(c["product"], []).append(list(c["out_per_day"].values())[0])
    # two P0 on Gas: the solver spreads over both before stacking, the stacked one yields half
    assert len(by_product) == 2
    stacked = max(by_product.values(), key=len)
    assert min(stacked) == pytest.approx(max(stacked) * 0.5, rel=0.01)
    assert any(c["notes"] for c in cols)


def test_taxes_from_skills():
    assert skills.sales_tax(0) == 7.5 and skills.sales_tax(4) == pytest.approx(4.2) and skills.sales_tax(5) == pytest.approx(3.375)
    assert skills.broker_fee(5) == pytest.approx(1.5)
    chars = [{"character_id": 1, "name": "Zero", "skills": {"Accounting": 0}},
             {"character_id": 2, "name": "Han", "skills": {"Accounting": 4, "Broker Relations": 5},
              "standings": [{"from_type": "faction", "from_id": 500001, "standing": 5.0}]}]
    seller = skills.best_seller(chars)
    assert seller["name"] == "Han" and seller["broker_by_hub"]["jita"] == pytest.approx(1.35)
    s = skills.apply(Settings(), seller)
    assert s.sales_tax_pct == pytest.approx(4.2)
    assert skills.apply(Settings(taxes_from_skills=False), seller).sales_tax_pct == Settings().sales_tax_pct


def test_non_voc_dropoff_couriers_from_nearest_pickup(pi):
    area = {"systems": {
        "1": {"system_id": 1, "name": "HZAQ-W", "region": "Delve", "planets": [], "neighbours": [2]},
        "2": {"system_id": 2, "name": "X", "region": "Delve", "planets": [], "neighbours": [1, 3]},
        "3": {"system_id": 3, "name": "7G-QIG", "region": "Delve", "planets": [], "neighbours": [2]},
    }}
    assert selling.courier_origin("HZAQ-W", area) == ("7G-QIG", 2)
    s = Settings()
    assert selling.channel_values(pi, s, BOOKS, 2396, "HZAQ-W") == {} or \
        "jita_buy" not in selling.channel_values(pi, s, BOOKS, 2396, "HZAQ-W")
    ch = selling.channel_values(pi, s, BOOKS, 2396, "HZAQ-W", origin="7G-QIG")
    assert ch["jita_buy"] > 0
    plan = selling.sell_plan(pi, Settings(use_buyback=False, use_local=False, use_amarr=False), BOOKS, "HZAQ-W",
                             {2329: 100_000}, per_day=False, origin="7G-QIG", origin_jumps=2)
    c = plan["batches"][0]["contract"]
    assert c["from"] == "7G-QIG" and "move" in c["move_first"].lower()


def test_stock_outside_voc_reach_can_still_be_sold(pi):
    ch = selling.channel_values(pi, Settings(), BOOKS, 2396, "Konora", local=False, self_haul=True)
    assert ch["jita_self"] == pytest.approx(800 * (1 - Settings().sales_tax_pct / 100))
    plan = selling.sell_plan(pi, Settings(), BOOKS, "Konora", {2396: 1000}, per_day=False, local=False,
                             self_haul=True)
    assert not plan["unsellable"] and plan["batches"][0]["channel"].endswith("_self")


def test_pipeline_hides_old_and_non_pi(pi):
    ch = {"character_id": 1, "name": "A", "orders": [], "contracts": [
        {"contract_id": 1, "type": "courier", "status": "finished", "voc": True, "date_issued": _iso(-24 * 20),
         "date_completed": _iso(-24 * 18)},
        {"contract_id": 2, "type": "courier", "status": "finished", "voc": True, "date_issued": _iso(-48),
         "date_completed": _iso(-24)},
        {"contract_id": 3, "type": "item_exchange", "status": "outstanding", "voc": True, "price": 1e6,
         "date_issued": _iso(-2), "items": [{"type_id": 34, "qty": 100}]},
        {"contract_id": 4, "type": "item_exchange", "status": "outstanding", "voc": True, "price": 1e6,
         "date_issued": _iso(-2), "items": [{"type_id": 2329, "qty": 10}, {"type_id": 34, "qty": 5}]},
    ]}
    pipe = operate.pipeline(pi, BOOKS, [ch])
    assert pipe["courier"] == [] and len(pipe["done"]) == 1          # finished: not "in the pipeline"
    assert len(pipe["buyback"]) == 1 and pipe["buyback"][0]["items"] == {"Biocells": 10}
    assert pipe["buyback"][0]["other_items"] == 1


def test_more_effort_never_shows_less_isk(pi):
    s = Settings(hub_system="HUB", max_jumps=1, max_systems=0, max_tier=1)
    area = _area()
    alts = optimizer.alternatives(pi, s, area, {int(k): v for k, v in area["systems"].items()}, CHARS, PRICES,
                                  TEMPLATES)
    isk = [a["totals"]["isk_per_day"] for a in alts]
    assert isk == sorted(isk)


# --- upkeep schedule (issue #4) ---------------------------------------------------------------
import time  # noqa: E402

from astracore.modules.pi.planner import upkeep  # noqa: E402

LAUNCHPAD, CC = 2544, 2524


def test_plan_buffer_checks_inputs_and_outputs_against_storage(pi):
    tight = {"kind": "factory", "layout": {"advanced": 12, "launchpads": 1},
             "in_per_day": {"Biofuels": 11520, "Precious Metals": 11520}, "out_per_day": {"Biocells": 1440}}
    b = upkeep.plan_buffer(pi, tight, 3)
    assert b["capacity_m3"] == 10_500                            # launchpad + command center
    assert b["in_m3_day"] == pytest.approx(23040 * 0.38, abs=0.1)
    assert b["visit_every_days"] == pytest.approx(10_500 / (23040 * 0.38), abs=0.05)
    assert b["restock"]["Biofuels"] == round(11520 * 10_500 / (23040 * 0.38))   # one launchpad load
    assert b["issues"] and "restock visit every 1.2 days" in b["issues"][0]
    roomy = upkeep.plan_buffer(pi, {**tight, "layout": {"advanced": 12, "launchpads": 1, "storage": 2}}, 3)
    assert roomy["issues"] == [] and roomy["fill_days"] > 3

    miner = {"kind": "miner", "layout": {"launchpads": 1}, "out_per_day": {"Biofuels": 7680}}
    m = upkeep.plan_buffer(pi, miner, 3)
    assert m["issues"] == [] and m["visit_every_days"] == 3 and m["reason"] == "extractor restart"
    m7 = upkeep.plan_buffer(pi, miner, 7)                        # a 7-day program outlasts the launchpad
    assert m7["reason"] == "collection" and m7["visit_every_days"] < 7 and "before the 7-day" in m7["issues"][0]
    bare = upkeep.plan_buffer(pi, {**miner, "layout": {}}, 3)
    assert "No launchpad or storage facility" in bare["issues"][0]


def test_plans_carry_a_storage_check_per_colony(pi):
    chars = [{"character_id": i, "name": f"C{i}", "slots": 3, "ccu_level": 5, "colonies": []} for i in (1, 2)]
    res = _plan(pi, chars=chars, prices={**PRICES, 2329: 400000.0}, max_tier=2, cross_character=True, max_jumps=2)
    assert res["colonies"] and all("visit_every_days" in c["upkeep"] for c in res["colonies"])
    tight = any(c["upkeep"]["issues"] for c in res["colonies"])
    assert tight == any(w.startswith("Storage check") for w in res["warnings"])


def _colonies(now):
    def iso(h):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + h * 3600))
    factory = {"planet_id": 12, "last_update": iso(0), "pins": [
        {"type_id": LAUNCHPAD, "contents": [{"type_id": 2396, "amount": 5760}, {"type_id": 2399, "amount": 960}]},
        {"type_id": CC, "contents": []},
        {"type_id": 2474, "schematic_id": 70}, {"type_id": 2474, "schematic_id": 70},
    ]}
    miner = {"planet_id": 11, "last_update": iso(-96), "pins": [
        {"type_id": LAUNCHPAD, "contents": [{"type_id": 2396, "amount": 20000}]},
        {"type_id": CC},
        {"type_id": 2848, "extractor_details": {"product_type_id": 2288, "heads": [{}] * 10, "cycle_time": 3600,
                                                "qty_per_cycle": 1500},
         "install_time": iso(-24), "expiry_time": iso(48)},
        {"type_id": 2473, "schematic_id": 121},
    ]}
    return factory, miner


def test_upkeep_schedule_derives_visits_from_each_colony(pi):
    now = time.time()
    factory, miner = _colonies(now)
    ch = {"character_id": 1, "name": "Test Pilot", "synced_at": now - 2 * 86400, "colonies": [factory, miner],
          "wallet": {"sales": [{"date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 5 * 86400)),
                                "type_id": 2329, "qty": 1, "unit_price": 1.0}]}}
    plan = {"colonies": [
        {"character_id": 1, "planet_id": 12, "character": "Test Pilot", "planet": "P12", "product": "Biocells",
         "kind": "factory", "layout": {"advanced": 2, "launchpads": 1},
         "in_per_day": {"Biofuels": 1920, "Precious Metals": 1920}, "out_per_day": {"Biocells": 480}},
        {"character_id": 1, "planet_id": 13, "character": "Test Pilot", "planet": "P13", "product": "Coolant",
         "kind": "factory", "layout": {"advanced": 12, "launchpads": 1},
         "in_per_day": {"Electrolytes": 11520, "Water": 11520}, "out_per_day": {"Coolant": 1440}},
    ]}
    sch = upkeep.schedule(pi, Settings(ship_every_days=7, cycle_days=3), [ch], plan, now=now)
    rows = {r["planet"]: r for r in sch["colonies"]}

    f = rows["Planet 12"]
    assert f["capacity_m3"] == 10_500 and f["used_m3"] == pytest.approx(6720 * 0.38, abs=0.1)
    assert f["next"] == "restock" and f["next_hours"] == pytest.approx(12, abs=0.1)   # 960 PM at 1,920/day
    assert f["visit_every_days"] == pytest.approx(10_500 / (3840 * 0.38), abs=0.05)
    assert f["restock"]["Biofuels"] == pytest.approx(1920 * 10_500 / (3840 * 0.38), rel=0.01)
    assert f["output"] == {"product": "Biocells", "actual": 240.0, "planned": 480, "pct": 50, "state": "soon"}
    assert [s["item"] for s in sch["shortages"]] == ["Precious Metals"]
    assert not f["stale"]

    m = rows["Planet 11"]
    p0_day = extraction.avg_per_hour(1500, 3600, 3 * 86400) * 24
    assert m["next"] == "restart" and m["next_hours"] == pytest.approx(48, abs=0.1)
    assert m["output"]["actual"] == pytest.approx(min(960.0, 960.0 * p0_day / 144_000), abs=0.1)
    assert m["output"]["planned"] is None                     # not in the active plan
    assert m["stale"] and 20000 * 0.38 < m["used_m3"] <= 10_500   # projected from the 4-day-old snapshot
    assert m["visit_every_days"] == 3.0                       # the extractor program, not the launchpad

    t = sch["tracks"]
    assert t["restart"]["next_hours"] == pytest.approx(48, abs=0.1) and t["restart"]["every_days"] == 3.0
    assert t["restock"]["colonies"] == 1 and t["restock"]["due"] == 1
    assert t["ship"]["every_days"] == 7 and t["ship"]["next_days"] == pytest.approx(2, abs=0.05)
    fr = sch["freshness"][0]
    assert fr["sync_stale"] and fr["colony_stale"] and sch["stale"]
    assert [c["planet"] for c in sch["plan_checks"]] == ["P13"]    # 12 Coolant factories can't buffer 3 days


def test_upkeep_flags_missing_storage_and_idle_factories(pi):
    now = time.time()
    col = {"planet_id": 14, "pins": [{"type_id": CC, "contents": []}, {"type_id": 2474, "schematic_id": 66}]}
    u = upkeep.colony_upkeep(pi, col, None, now)
    assert u["capacity_m3"] == 500 and "No launchpad or storage facility" in u["issues"][0]
    assert u["next"] == "restock" and u["next_hours"] == 0 and u["state"] == "expired"
    assert u["output"] is None                                   # nothing made while inputs are missing
    assert {s["item"] for s in u["shortages"]} == {"Electrolytes", "Water"}
    unknown = upkeep.colony_upkeep(pi, {"planet_id": 15, "pins": [
        {"schematic_id": 66}, {"contents": [{"type_id": 2390, "amount": 100}]}]}, None, now)
    assert unknown["capacity_m3"] is None and "not recognised" in unknown["issues"][0]


# --- route check (issue #25) ------------------------------------------------------------------
def _routed(col, routes):
    """Give the fake colony ESI-style pin ids (in pin order) and the given routes."""
    pins = [dict(p, pin_id=i + 1) for i, p in enumerate(col["pins"])]
    return {**col, "pins": pins, "links": [], "routes": [
        {"source_pin_id": a, "destination_pin_id": b, "content_type_id": t, "quantity": q} for a, b, t, q in routes]}


def _route_issues(u):
    return [i for i in u["issues"] if "routed" in i]


def test_upkeep_flags_unrouted_factory_inputs_and_outputs(pi):
    now = time.time()
    factory, _ = _colonies(now)   # pins: 1 launchpad, 2 command center, 3 + 4 Biocells factories
    full = [(1, f, t, 40) for f in (3, 4) for t in (2396, 2399)] + [(3, 1, 2329, 5), (4, 1, 2329, 5)]
    legacy = upkeep.colony_upkeep(pi, factory, None, now)
    assert not legacy["routes_known"] and not _route_issues(legacy)    # old stored colony: unknown, no error

    ok = upkeep.colony_upkeep(pi, _routed(factory, full), None, now)
    assert ok["routes_known"] and not _route_issues(ok)
    assert ok["output"] == legacy["output"]

    no_pm = upkeep.colony_upkeep(pi, _routed(factory, [r for r in full if r[1:3] != (4, 2399)]), None, now)
    assert _route_issues(no_pm) == [
        "Precious Metals isn't routed into 1 of 2 Advanced Industry Facilities making Biocells."]
    assert no_pm["output"]["actual"] == pytest.approx(legacy["output"]["actual"] / 2, abs=0.1)

    stuck = upkeep.colony_upkeep(pi, _routed(factory, [r for r in full if r[2] != 2329]), None, now)
    assert _route_issues(stuck) == ["Biocells isn't routed out of all 2 Advanced Industry Facilities making "
                                    "Biocells to storage, a launchpad or another factory."]
    assert stuck["output"] is None and not stuck["has_imports"]          # neither factory can run

    one = {**factory, "pins": factory["pins"][:3]}
    lone = upkeep.colony_upkeep(pi, _routed(one, [(1, 3, 2396, 40)]), None, now)
    assert "Precious Metals isn't routed into the Advanced Industry Facility making Biocells." in lone["issues"]


def test_upkeep_flags_unrouted_extractor_but_keeps_its_restart(pi):
    now = time.time()
    _, miner = _colonies(now)     # pins: 1 launchpad, 2 command center, 3 extractor, 4 Biofuels factory
    routed = upkeep.colony_upkeep(pi, _routed(miner, [(3, 4, 2288, 1500), (4, 1, 2396, 20)]), None, now)
    assert not _route_issues(routed) and routed["output"]["actual"] > 0

    lost = upkeep.colony_upkeep(pi, _routed(miner, [(4, 1, 2396, 20)]), None, now)
    assert any(i.endswith("from an extractor isn't routed anywhere: the extracted product is lost.")
               for i in lost["issues"])
    assert "isn't routed into the Basic Industry Facility" in " ".join(lost["issues"])
    assert lost["output"] is None                                          # nothing reaches the factory
    assert lost["next"] == "restart" and lost["restart_hours"] == pytest.approx(48, abs=0.1)


def test_character_sync_keeps_links_and_routes_compactly():
    from astracore.esi.character import _layout_network
    det = {"pins": [], "links": [{"source_pin_id": 1, "destination_pin_id": 3, "link_level": 2}],
           "routes": [{"route_id": 9, "source_pin_id": 1, "destination_pin_id": 3, "content_type_id": 2396,
                       "quantity": 40, "waypoints": [2]}]}
    assert _layout_network(det) == {
        "links": [{"source_pin_id": 1, "destination_pin_id": 3, "link_level": 2}],
        "routes": [{"source_pin_id": 1, "destination_pin_id": 3, "content_type_id": 2396, "quantity": 40}]}
    assert _layout_network({"pins": []}) == {"links": [], "routes": []}


def test_solves_end_on_a_node_limit_so_results_dont_depend_on_machine_load(pi, monkeypatch):
    seen = []
    real = optimizer.pulp.PULP_CBC_CMD

    def spy(**kw):
        seen.append(kw)
        return real(**kw)

    monkeypatch.setattr(optimizer.pulp, "PULP_CBC_CMD", spy)
    first = _plan(pi, max_tier=2, effort=50)
    second = _plan(pi, max_tier=2, effort=50)
    assert seen and all(k["maxNodes"] == optimizer.SOLVER_MAX_NODES and k["threads"] == 1 for k in seen)
    assert all(k["timeLimit"] >= optimizer.SOLVER_SAFETY_SECONDS for k in seen)
    assert first["totals"] == second["totals"] and first["colonies"] == second["colonies"]
