"""Operate counts only PI activity (#87) and compares the plan with the colonies you have now (#88).

Synthetic characters, colonies, contracts and wallet entries only; nothing touches the network.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from astracore import db
from astracore.esi import character as esi_char
from astracore.modules.pi import store
from astracore.modules.pi.planner import operate, upkeep
from astracore.modules.pi.settings import Settings

from test_core import PI_SCOPES, browser, eve, me, new_id, sso_login  # noqa: F401 (fixtures)
from test_planner import BOOKS, CC, LAUNCHPAD, _colonies, pi  # noqa: F401 (fixture)

CC_TYPE = 2524   # a command center: not a PI product


def _iso(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _locations():
    db.kv_set(esi_char.LOCATIONS_KEY, {
        "1": {"name": "Drop-off - Keepstar", "system": "7G-QIG", "system_id": 1},
        "2": {"name": "Jita IV - Moon 4 - Caldari Navy Assembly Plant", "system": "Jita", "system_id": 2},
    })


def _courier(cid, *, pi_items, start=1, status="in_progress", collateral=0.0, reward=0.0, hours=-30, voc=True):
    items = [{"type_id": 2329, "qty": 1000}] if pi_items else [{"type_id": CC_TYPE, "qty": 3}]
    return {"contract_id": cid, "type": "courier", "status": status, "voc": voc, "pi": pi_items,
            "collateral": collateral, "reward": reward, "volume": 1000, "date_issued": _iso(hours),
            "start_location_id": start, "end_location_id": 2, "items": items}


def _trader():
    sale_t = _iso(-10)
    old_sale_t = _iso(-20)
    order_t = _iso(-12)
    return {
        "character_id": 1, "name": "Trader", "colonies": [], "assets": [],
        "contracts": [
            _courier(11, pi_items=True, collateral=5e8, reward=1e7),                    # PI to market
            _courier(12, pi_items=False, collateral=3e8, reward=5e6),                   # command centers
            _courier(13, pi_items=True, start=2, collateral=1e8, reward=2e6),           # starter stock coming in
            _courier(14, pi_items=True, collateral=7e8, reward=9e6, voc=False),         # not VOC
        ],
        "orders": [{"order_id": 501, "type_id": 2329, "price": 12000.0, "volume_remain": 5, "volume_total": 10,
                    "location_id": 2, "is_buy_order": False, "issued": order_t}],
        "wallet": {"balance": 0, "sales": [
            {"date": sale_t, "type_id": 2329, "qty": 10, "unit_price": 10000.0, "transaction_id": 9001},
            {"date": old_sale_t, "type_id": 2329, "qty": 1, "unit_price": 10000.0},     # synced before ids were kept
        ], "journal": [
            {"date": _iso(-29), "ref_type": "contract_reward", "amount": -1e7, "context_id": 11},
            {"date": _iso(-29), "ref_type": "contract_reward", "amount": -5e6, "context_id": 12},
            {"date": _iso(-29), "ref_type": "contract_reward", "amount": -2e6, "context_id": 13},
            {"date": sale_t, "ref_type": "transaction_tax", "amount": -3000.0, "context_id": 9001},
            {"date": old_sale_t, "ref_type": "transaction_tax", "amount": -300.0, "context_id": 9002},
            {"date": _iso(-3), "ref_type": "transaction_tax", "amount": -77_000.0, "context_id": 4444},  # ships sold
            {"date": order_t, "ref_type": "brokers_fee", "amount": -1500.0, "context_id": 501},
            {"date": _iso(-4), "ref_type": "brokers_fee", "amount": -55_000.0, "context_id": 777},     # other order
            {"date": _iso(-5), "ref_type": "planetary_export_tax", "amount": -800.0, "context_id": 40000001},
        ]},
    }


def test_in_transit_and_courier_costs_count_only_pi_shipments(pi):
    _locations()
    ch = _trader()
    pipe = operate.pipeline(pi, BOOKS, [ch])
    assert [c["reward"] for c in pipe["courier"]] == [1e7]
    assert pipe["in_transit_value"] == 5e8

    earned = operate.earnings(pi, [ch], days=7)
    assert earned["courier_costs"] == 1e7                       # not the command-center or starter-stock courier
    assert earned["taxes"] == 3000 + 300 + 1500 + 800           # PI sale tax, PI order fee and customs only
    assert earned["market_sales"] == 110_000
    assert earned["net"] == 110_000 - 1e7 - (3000 + 300 + 1500 + 800)


def test_a_non_pi_contract_is_no_market_shipment(pi):
    _locations()
    now = time.time()
    ch = {"character_id": 1, "name": "Hauler", "colonies": [], "assets": [], "orders": [], "wallet": {},
          "contracts": [_courier(12, pi_items=False, hours=-24 * 2),          # command centers two days ago
                        _courier(13, pi_items=True, start=2, hours=-24)]}    # starter stock coming in
    ship = upkeep.schedule(pi, Settings(ship_every_days=7), [ch], None, now=now)["tracks"]["ship"]
    assert ship["last"] is None and ship["next_days"] is None and not ship["due"]

    ch["contracts"].append(_courier(11, pi_items=True, hours=-24 * 10))
    ship = upkeep.schedule(pi, Settings(ship_every_days=7), [ch], None, now=now)["tracks"]["ship"]
    assert ship["next_days"] == pytest.approx(-3, abs=0.05)
    assert not ship["has_stock"] and not ship["due"]                    # nothing in hangars: nothing to ship

    ch["assets"] = [{"type_id": 2329, "qty": 500, "location_id": 1, "flag": "Hangar"}]
    ship = upkeep.schedule(pi, Settings(ship_every_days=7), [ch], None, now=now)["tracks"]["ship"]
    assert ship["has_stock"] and ship["due"]


# --- plan progress (#88) -------------------------------------------------------------------------
def _col(planet_id, *schematics, extractor=None):
    pins = [{"type_id": LAUNCHPAD, "contents": []}, {"type_id": CC, "contents": []}]
    pins += [{"type_id": 2474, "schematic_id": s} for s in schematics]
    if extractor:
        pins.append({"type_id": 2848, "extractor_details": {"product_type_id": extractor}})
    return {"planet_id": planet_id, "pins": pins}


def _plan_col(planet_id, product, product_id, action, cid=1):
    return {"character_id": cid, "character": "Builder", "planet_id": planet_id, "planet": f"P{planet_id}",
            "system": "S", "planet_type": "Barren", "product": product, "product_id": product_id, "kind": "factory",
            "action": action, "template": "t", "template_file": "t.json", "layout": {}, "in_per_day": {},
            "out_per_day": {product: 100}}


def _plan():
    return {"characters": [{"character_id": 1, "name": "Builder"}],
            "colonies": [_plan_col(12, "Biocells", 2329, "keep"),       # built and making Biocells
                         _plan_col(11, "Coolant", 9832, "new"),         # holds a Biofuels miner instead
                         _plan_col(13, "Coolant", 9832, "new"),         # not built yet
                         _plan_col(15, "Biocells", 2329, "rebuild")],   # rebuilt since the plan was saved
            "removals": [{"character": "Builder", "planet_id": 99, "current": "Water"}]}   # abandoned since


def _builder(*colonies, cid=1, name="Builder", ccu=5):
    return {"character_id": cid, "name": name, "ccu_level": ccu, "colonies": list(colonies)}


def test_progress_matches_planet_and_product_and_recomputes_removals(pi):
    ch = _builder(_col(12, 70), _col(11, 121), _col(15, 70), _col(14, 66))
    live = operate.progress_against(pi, _plan(), [ch])
    acts = {c["planet_id"]: c["action"] for c in live["colonies"]}
    assert acts == {12: "keep", 11: "rebuild", 13: "new", 15: "keep"}
    assert next(c for c in live["colonies"] if c["planet_id"] == 11)["current"] == "Biofuels"
    assert [(r["planet_id"], r["current"]) for r in live["removals"]] == [(14, "Coolant")]   # 99 is gone
    assert operate.build_progress(live) == {"done": 2, "todo": 2, "total": 4, "removals": 1, "rebuild": 1, "new": 1}

    done = operate.progress_against(pi, _plan(), [_builder(_col(12, 70), _col(11, 66), _col(13, 66), _col(15, 70))])
    assert operate.build_progress(done) == {"done": 4, "todo": 0, "total": 4, "removals": 0, "rebuild": 0, "new": 0}


def test_plan_drift_ignores_progress_and_reports_what_the_plan_didnt_foresee(pi):
    as_planned = _builder(_col(12, 70), _col(11, 66), _col(15, 70))
    assert operate.plan_drift(pi, _plan(), [as_planned]) is None        # built, rebuilt, removed: progress

    off_plan = _builder(_col(12, 66), _col(11, 66), _col(16, 70))        # kept colony changed, colony off plan
    newcomer = _builder(cid=2, name="Newcomer")
    rookie = _builder(cid=3, name="Rookie", ccu=1)                        # can't place templates: not planned
    d = operate.plan_drift(pi, _plan(), [off_plan, newcomer, rookie])
    assert d["colonies"] == 2 and d["added"] == ["Newcomer"] and d["removed"] == []
    assert d["summary"] == "2 colonies differ, 1 character changed"

    gone = operate.plan_drift(pi, _plan(), [newcomer])
    assert gone["removed"] == ["Builder"] and gone["colonies"] == 0


def test_a_colony_making_another_product_says_so(pi):
    now = time.time()
    factory, _ = _colonies(now)                                           # a Biocells factory
    wrong = upkeep.colony_upkeep(pi, factory, {"product": "Coolant", "out_per_day": {"Coolant": 480}}, now)
    assert wrong["output"]["product"] == "Biocells" and wrong["output"]["expects"] == "Coolant"
    assert wrong["output"]["planned"] is None and wrong["output"]["pct"] is None


def test_an_idle_factory_has_no_restock_rhythm(pi):
    now = time.time()
    idle = {"planet_id": 14, "last_update": _iso(0), "pins": [
        {"type_id": LAUNCHPAD, "contents": []}, {"type_id": CC, "contents": []}, {"type_id": 2474, "schematic_id": 66}]}
    sch = upkeep.schedule(pi, Settings(), [_builder(idle)], None, now=now)
    assert sch["colonies"][0]["idle"]
    assert sch["tracks"]["restock"]["colonies"] == 1 and sch["tracks"]["restock"]["every_days"] is None


def test_planets_outside_the_area_keep_their_synced_name(pi):
    col = {**_col(40000001, 70), "planet_name": "Somewhere IV", "system_name": "Somewhere"}
    sch = upkeep.schedule(pi, Settings(), [_builder(col)], None, now=time.time())
    assert (sch["colonies"][0]["planet"], sch["colonies"][0]["system"]) == ("Somewhere IV", "Somewhere")
    assert operate.colony_name({}, {"planet_id": 7}) == {"name": "Planet 7", "system": "", "type": ""}


def test_operate_says_when_the_plan_is_out_of_date(browser, eve, monkeypatch, pi):
    from astracore.modules.pi import service

    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Drift Pilot")
    pid = me(c)
    db.save_token(cid, "rt", "at", 1199, PI_SCOPES)
    factory, _ = _colonies(time.time())
    db.set_character(cid, colonies=[factory, {**_col(40000077, 66), "planet_name": "Elsewhere II"}],
                     synced_at=time.time())
    s = Settings()
    plan = {"totals": {}, "characters": [{"character_id": cid, "name": "Drift Pilot"}], "removals": [],
            "colonies": [{**_plan_col(12, "Coolant", 9832, "keep", cid), "character": "Drift Pilot",
                          "out_per_day": {"Coolant": 480}}]}
    store.save_plan_run(pid, "drift", s, plan, active=True)

    async def ctx(profile_id, *a, **kw):
        return {"chars": service.planning_characters(profile_id), "pi": pi, "s": s, "books": {}, "area": None,
                "tpl": []}

    monkeypatch.setattr(service, "planning_context", ctx)
    r = c.get("/pi/operate")
    assert r.status_code == 200, r.text
    html = r.text
    assert "Your plan is out of date (2 colonies differ)" in html and 'href="/pi/plan">Update plan' in html
    assert "makes Biocells, plan expects Coolant" in html and "0% of planned" not in html
    assert "0 of 1 planned colonies are built as planned" in html and "1 to rebuild · 1 to remove" in html
    assert "Elsewhere II" in html
