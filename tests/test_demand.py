"""Market demand: does the plan's output fit the buyers and the trade volume at the chosen market?

Offline: fake order-book depth and trade history on top of the planner's hand-built SDE subset."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from astracore.modules.pi.planner import demand, prices, selling
from astracore.modules.pi.settings import Settings
from test_planner import pi  # noqa: F401 - shared SDE fixture

BIOCELLS = 2329


def books(**extra):
    b = {"jita_buy": 10000.0, "jita_sell": 11000.0, "amarr_buy": 9500.0, "amarr_sell": 10500.0, "delve_buy": 7000.0}
    b.update(extra)
    return {BIOCELLS: b}


def history(avg_volume=50_000.0, days=30, cv=0.04, market="jita"):
    return {market: {BIOCELLS: {"avg_volume": avg_volume, "days": days, "window": 30,
                                "last": "2026-10-10", "price_cv": cv}}}


def assess(pi, s, bk, hist, dropoff, units, local=True):  # noqa: F811
    sp = selling.sell_plan(pi, s, bk, dropoff, units, per_day=False, local=local)
    rows = selling.compare_table(pi, s, bk, dropoff, list(units), local)
    return demand.assess(pi, s, bk, hist, sp, rows, units, books_at=1.0, history_at=2.0)


def test_fill_walks_the_book_and_reports_the_shortfall():
    f = demand.fill([[100.0, 10], [90.0, 10]], 15)
    assert f["filled"] == 15 and f["short"] == 0 and f["levels"] == 2 and f["worst_price"] == 90.0
    assert f["avg_price"] == pytest.approx((10 * 100 + 5 * 90) / 15)
    short = demand.fill([[100.0, 10]], 25)
    assert short["filled"] == 10 and short["short"] == 15
    assert demand.fill([], 5)["filled"] == 0


def test_depth_merges_levels_and_skips_minimum_volume_orders():
    orders = [{"price": 10.0, "volume_remain": 5}, {"price": 12.0, "volume_remain": 3},
              {"price": 10.0, "volume_remain": 2}, {"price": 13.0, "volume_remain": 100, "min_volume": 50}]
    assert prices.depth(orders, best_first=max) == [[12.0, 3], [10.0, 7]]
    assert prices.depth(orders, best_first=min) == [[10.0, 7], [12.0, 3]]


def test_history_summary_covers_only_the_recent_window():
    today = date(2026, 10, 11)
    rows = [{"date": (today - timedelta(days=d)).isoformat(), "volume": 300, "average": 100 + d % 2 * 10}
            for d in range(1, 11)]
    rows.append({"date": (today - timedelta(days=60)).isoformat(), "volume": 1_000_000, "average": 5})
    h = prices.summarise_history(rows, today)
    assert h["days"] == 10 and h["window"] == 30 and h["last"] == "2026-10-10"
    assert h["avg_volume"] == pytest.approx(10 * 300 / 30)      # quiet days count as zero traded
    assert 0 < h["price_cv"] < 0.1
    assert prices.summarise_history([], today)["days"] == 0


def test_too_few_buyers_is_flagged_with_real_proceeds(pi):  # noqa: F811
    s = Settings(use_buyback=False, use_local=False, use_amarr=False)
    bk = books(jita_buy_depth=[[10000.0, 300], [9900.0, 200]])
    d = assess(pi, s, bk, history(), "Jita", {BIOCELLS: 1000}, local=False)
    row = d["rows"][0]
    assert row["status"] == "short" and row["visible_units"] == 500
    im = row["immediate"]
    tax = 1 - s.sales_tax_pct / 100
    assert im["filled"] == 500 and im["short"] == 500
    assert im["avg_net"] == pytest.approx((300 * 10000 + 200 * 9900) / 500 * tax, rel=1e-6)
    assert "only 500 of the 1,000" in row["advice"] and "smaller batches" in row["advice"]
    assert d["warnings"] and d["books_at"] == 1.0 and d["history_at"] == 2.0


def test_thin_book_suggests_a_market_that_can_take_the_batch(pi):  # noqa: F811
    s = Settings(use_buyback=False, use_local=True, use_amarr=True)
    bk = books(jita_buy_depth=[[10000.0, 1000], [8000.0, 500_000]],
               amarr_buy_depth=[[9500.0, 500_000]])
    d = assess(pi, s, bk, history(avg_volume=1e7), "7G-QIG", {BIOCELLS: 100_000})
    row = next(r for r in d["rows"] if r["channel"] == "jita_buy")
    assert row["status"] == "thin" and row["immediate"]["short"] == 0
    assert row["immediate"]["avg_net"] < row["immediate"]["quoted_net"]      # hauling + tax stay consistent
    assert row["alternative"]["channel"] == "amarr_buy"


def test_output_large_against_daily_volume_is_thin(pi):  # noqa: F811
    s = Settings(use_buyback=False, use_local=False, use_amarr=False)
    bk = books(jita_buy_depth=[[10000.0, 1_000_000]])
    d = assess(pi, s, bk, history(avg_volume=2000), "Jita", {BIOCELLS: 1000}, local=False)
    assert d["rows"][0]["status"] == "thin" and d["rows"][0]["volume_share"] == 0.5


def test_sell_orders_get_an_estimated_horizon_and_uncertainty(pi):  # noqa: F811
    s = Settings(use_buyback=False, use_local=False, use_amarr=False, use_sell_orders=True, ship_every_days=7)
    bk = books(jita_buy_depth=[[10000.0, 1_000_000]])
    d = assess(pi, s, bk, history(avg_volume=100, cv=0.08), "Jita", {BIOCELLS: 1000}, local=False)
    row = d["rows"][0]
    assert row["side"] == "sell" and row["immediate"] is None
    assert row["horizon_days"] == [pytest.approx(33.3), pytest.approx(100.0)]
    assert row["price_uncertainty_pct"] == 8.0
    assert row["status"] == "slow" and "Estimate" in row["advice"]
    fast = assess(pi, s, bk, history(avg_volume=1e6), "Jita", {BIOCELLS: 1000}, local=False)
    assert fast["rows"][0]["status"] == "ok" and not fast["warnings"]


def test_missing_history_is_called_out_without_alarming(pi):  # noqa: F811
    s = Settings(use_buyback=False, use_local=False, use_amarr=False)
    bk = books(jita_buy_depth=[[10000.0, 1_000_000]])
    d = assess(pi, s, bk, {}, "Jita", {BIOCELLS: 1000}, local=False)
    row = d["rows"][0]
    assert row["status"] == "unknown" and "No trade history" in row["advice"]
    assert not d["warnings"] and d["history_days_min"] == 0


def test_buyback_explains_unpublished_capacity(pi):  # noqa: F811
    d = assess(pi, Settings(), books(), history(), "7G-QIG", {BIOCELLS: 100})
    row = next(r for r in d["rows"] if r["channel"] == "buyback")
    assert row["side"] == "buyback" and row["status"] == "ok" and "doesn't publish" in row["advice"]


# --- demand shapes the plan -------------------------------------------------------------
def test_realistic_values_price_flagged_batches_at_what_buyers_pay(pi):  # noqa: F811
    s = Settings(use_buyback=False, use_local=False, use_amarr=False)
    tax = 1 - s.sales_tax_pct / 100
    short = assess(pi, s, books(jita_buy_depth=[[10000.0, 300], [9900.0, 200]]), history(), "Jita",
                   {BIOCELLS: 1000}, local=False)
    walked = (300 * 10000 + 200 * 9900) * tax
    real = demand.realistic_values(short, {BIOCELLS: 10000 * tax})
    assert real[BIOCELLS] == pytest.approx(walked / 1000, rel=1e-4)    # unsold half earns nothing
    ok = assess(pi, s, books(jita_buy_depth=[[10000.0, 1_000_000]]), history(), "Jita", {BIOCELLS: 1000}, local=False)
    assert demand.realistic_values(ok, {BIOCELLS: 10000 * tax}) == {}
    # a cheaper channel that takes the whole batch is worth more than leaving half of it unsold
    s2 = Settings(use_buyback=False, use_local=False, use_amarr=True)
    alt = assess(pi, s2, books(jita_buy_depth=[[10000.0, 300]], amarr_buy_depth=[[9500.0, 1_000_000]]),
                 history(), "7G-QIG", {BIOCELLS: 20_000})          # big enough to beat VOC's minimum fee
    row = alt["rows"][0]
    assert row["status"] == "short" and row["alternative"]["channel"] == "amarr_buy"
    expected = (300 * row["immediate"]["avg_net"] + 19_700 * row["alternative"]["value"]) / 20_000
    real = demand.realistic_values(alt, {BIOCELLS: row["immediate"]["quoted_net"]})
    assert real[BIOCELLS] == pytest.approx(expected, rel=1e-4)
    held = {**alt, "rows": [{**row, "hold": True}]}
    assert demand.realistic_values(held, {BIOCELLS: 10000.0}) == {}    # held batches aren't sold this cycle


from astracore.modules.pi import service  # noqa: E402
from astracore.modules.pi.planner import optimizer  # noqa: E402
from test_planner import CHARS, TEMPLATES, _area  # noqa: E402

BIOFUELS, OTHER_P1 = 2396, (2399, 2390, 3645)
_real_warm_history = service.warm_history   # conftest swaps it for a no-op in every test


def _ctx(pi, biofuels_depth):  # noqa: F811
    """A miners-only plan sold in Jita: Biofuels quotes 2,000 ISK, everything else 800 with deep books."""
    s = Settings(hub_system="HUB", max_jumps=1, max_systems=0, effort=100, max_tier=1,
                 use_buyback=False, use_local=False, use_amarr=False)
    bk = {t: {"jita_buy": 800.0, "jita_buy_depth": [[800.0, 10_000_000]]} for t in OTHER_P1}
    bk[BIOFUELS] = {"jita_buy": 2000.0, "jita_buy_depth": biofuels_depth}
    area = _area()
    return dict(pi=pi, s=s, solve_s=s, area=area, systems={int(k): v for k, v in area["systems"].items()},
                chars=CHARS, tpl=TEMPLATES, overrides={}, head_yield=s.head_yield_per_hour, books=bk,
                books_at=1.0, history={}, history_at=None, dropoff="Jita", local=False, origin="Jita",
                origin_jumps=0, seller=None, measured={}, manual_overrides={}, calibrated=None,
                values=selling.best_values(pi, s, bk, "Jita", False, "Jita"))


def _counting(monkeypatch):
    calls = []
    real = optimizer.plan

    def plan(*a, **kw):
        calls.append(a[5])
        return real(*a, **kw)
    monkeypatch.setattr(optimizer, "plan", plan)
    return calls


def test_plan_moves_off_a_market_that_cannot_take_the_batch(pi, monkeypatch):  # noqa: F811
    calls = _counting(monkeypatch)
    res = service.run_plan(_ctx(pi, [[2000.0, 500]]))       # 500 buyers for thousands of units a week
    assert len(calls) == 2 and calls[1][BIOFUELS] < calls[0][BIOFUELS]
    assert BIOFUELS not in {x["type_id"] for x in res["sold"]}
    assert res["demand"]["replanned"][0]["item"] == "Biofuels"
    assert any(w.startswith("Re-planned around thin markets: Biofuels") for w in res["warnings"])
    # the demand table describes the plan that was kept
    assert {r["type_id"] for r in res["demand"]["rows"]} == {x["type_id"] for x in res["sold"]}


def test_plan_solves_once_when_buyers_can_take_everything(pi, monkeypatch):  # noqa: F811
    calls = _counting(monkeypatch)
    res = service.run_plan(_ctx(pi, [[2000.0, 10_000_000]]))
    assert len(calls) == 1 and BIOFUELS in {x["type_id"] for x in res["sold"]}
    assert res["demand"]["replanned"] == [] and not any("Re-planned" in w for w in res["warnings"])


def test_plan_keeps_a_thin_product_that_still_pays_best(pi, monkeypatch):  # noqa: F811
    calls = _counting(monkeypatch)
    res = service.run_plan(_ctx(pi, [[2000.0, 500], [1700.0, 10_000_000]]))   # walking costs ~15%, still > 800
    assert len(calls) == 2
    assert BIOFUELS in {x["type_id"] for x in res["sold"]}
    assert res["demand"]["replanned"] == [] and not any("Re-planned" in w for w in res["warnings"])
    assert any(r["status"] == "thin" for r in res["demand"]["rows"])


def test_startup_warms_stale_trade_history_without_blocking(pi, monkeypatch):  # noqa: F811
    import asyncio
    from astracore.modules.pi.planner import prices
    from astracore.modules.pi.static_data import sde_loader
    fetched = []

    async def fake_refresh(esi, data):
        fetched.append(data)

    monkeypatch.setattr(service, "ESIClient", _NoNetwork)
    monkeypatch.setattr(prices, "refresh_history", fake_refresh)
    monkeypatch.setattr(sde_loader, "cached", lambda: pi)
    monkeypatch.setattr(prices, "history_stale", lambda: True)
    asyncio.run(_real_warm_history())
    assert fetched == [pi]
    monkeypatch.setattr(prices, "history_stale", lambda: False)
    asyncio.run(_real_warm_history())
    assert len(fetched) == 1                                 # fresh history: nothing to do


class _NoNetwork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_slow_sell_orders_are_valued_at_what_sells_within_a_cycle(pi):  # noqa: F811
    s = Settings(use_buyback=False, use_local=False, use_amarr=False, use_sell_orders=True, ship_every_days=7)
    bk = books(jita_buy_depth=[[10000.0, 1_000_000]])
    d = assess(pi, s, bk, history(avg_volume=100), "Jita", {BIOCELLS: 1000}, local=False)
    row = d["rows"][0]
    assert row["status"] == "slow" and row["alternative"]["channel"] == "jita_buy"
    frac = 7 / ((row["horizon_days"][0] + row["horizon_days"][1]) / 2)          # ~10% sells within a cycle
    expected = frac * row["value"] + (1 - frac) * row["alternative"]["value"]
    real = demand.realistic_values(d, {BIOCELLS: row["value"]})
    assert real[BIOCELLS] == pytest.approx(expected, rel=1e-3)
    assert row["alternative"]["value"] < real[BIOCELLS] < row["value"]
    fast = assess(pi, s, bk, history(avg_volume=1e6), "Jita", {BIOCELLS: 1000}, local=False)
    assert demand.realistic_values(fast, {BIOCELLS: fast["rows"][0]["value"]}) == {}


def test_output_far_above_daily_trades_is_only_partly_valued(pi):  # noqa: F811
    s = Settings(use_buyback=False, use_local=False, use_amarr=False)
    tax = 1 - s.sales_tax_pct / 100
    bk = books(jita_buy_depth=[[10000.0, 1_000_000]])
    d = assess(pi, s, bk, history(avg_volume=1000), "Jita", {BIOCELLS: 1000}, local=False)
    row = d["rows"][0]
    assert row["status"] == "thin" and row["volume_share"] == 1.0 and row["immediate"]["short"] == 0
    real = demand.realistic_values(d, {BIOCELLS: 10000 * tax})
    assert real[BIOCELLS] == pytest.approx(demand.BUY_VOLUME_CAPTURE * 10000 * tax, rel=1e-4)   # no alternative
    calm = assess(pi, s, bk, history(avg_volume=3000), "Jita", {BIOCELLS: 1000}, local=False)  # 33%: warned only
    assert calm["rows"][0]["status"] == "thin" and demand.realistic_values(calm, {BIOCELLS: 10000 * tax}) == {}
