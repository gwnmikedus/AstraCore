"""Sell-order valuation: with "Also list sell orders", a product is valued at the lowest sell order at the
hub (after sales tax and broker fee) only where recent trades show a listing sells; otherwise it keeps its
instant-sale value and the plan says why.

Offline: the planner's hand-built SDE subset (P1/P2 stand in for P3/P4: the rules don't depend on tier)."""
from __future__ import annotations

import pytest

from astracore.modules.pi import service
from astracore.modules.pi.planner import demand, selling
from astracore.modules.pi.settings import Settings
from test_planner import CHARS, TEMPLATES, _area, pi  # noqa: F401 - shared SDE fixture

BIOCELLS, BIOFUELS, OTHER_P1 = 2329, 2396, (2399, 2390, 3645)
ORDERS = dict(use_buyback=False, use_local=False, use_amarr=False, use_sell_orders=True)


def book(**extra):
    b = {"jita_buy": 10000.0, "jita_sell": 11000.0, "jita_buy_depth": [[10000.0, 1_000_000]],
         "jita_sell_depth": [[11000.0, 40], [11500.0, 100]]}
    b.update(extra)
    return b


def traded(avg_volume=5000.0, days=30, market="jita", type_id=BIOCELLS):
    return {market: {type_id: {"avg_volume": avg_volume, "days": days, "window": 30, "last": "2026-10-20",
                               "price_cv": 0.03}}}


def test_sell_order_is_valued_at_the_lowest_ask_after_tax_and_broker_fee_when_it_trades(pi):  # noqa: F811
    s = Settings(**ORDERS)
    ch = selling.channel_values(pi, s, {BIOCELLS: book()}, BIOCELLS, "Jita", local=False, history=traded())
    assert ch["jita_sell"] == pytest.approx(11000 * (1 - s.sales_tax_pct / 100 - s.broker_fee_pct / 100))
    assert ch["jita_buy"] == pytest.approx(10000 * (1 - s.sales_tax_pct / 100))
    vals = selling.best_values(pi, s, {BIOCELLS: book()}, "Jita", False, "Jita", traded())
    assert vals[BIOCELLS] == pytest.approx(ch["jita_sell"])


@pytest.mark.parametrize("bk,hist,reason", [
    (book(), {}, "trade history hasn't loaded yet"),
    (book(), traded(avg_volume=0, days=0), "nobody traded it in Jita 4-4's region recently"),
    (book(), traded(type_id=BIOFUELS), "nobody traded it in Jita 4-4's region recently"),
    ({k: v for k, v in book().items() if k != "jita_sell_depth"}, traded(), "its sell orders didn't load"),
])
def test_without_evidence_it_sells_the_product_keeps_its_instant_sale_value(pi, bk, hist, reason):  # noqa: F811
    s = Settings(**ORDERS)
    assert selling.sell_order_gap(bk, hist, BIOCELLS, "jita") == reason
    ch = selling.channel_values(pi, s, {BIOCELLS: bk}, BIOCELLS, "Jita", local=False, history=hist)
    assert set(ch) == {"jita_buy"}
    assert selling.best_values(pi, s, {BIOCELLS: bk}, "Jita", False, "Jita", hist)[BIOCELLS] == ch["jita_buy"]
    # not checked (stock already in a hangar): the listed price as before
    assert "jita_sell" in selling.channel_values(pi, s, {BIOCELLS: bk}, BIOCELLS, "Jita", local=False)


def test_sell_orders_off_never_value_a_listing(pi):  # noqa: F811
    s = Settings(**{**ORDERS, "use_sell_orders": False})
    assert set(selling.channel_values(pi, s, {BIOCELLS: book()}, BIOCELLS, "Jita", local=False,
                                      history=traded())) == {"jita_buy"}


def test_sell_plan_batch_shows_the_sell_order_price_and_turnaround(pi):  # noqa: F811
    s = Settings(**ORDERS, ship_every_days=7)
    bk = {BIOCELLS: book()}
    sp = selling.sell_plan(pi, s, bk, "Jita", {BIOCELLS: 100}, local=False, history=traded())
    (b,) = sp["batches"]
    assert b["channel"] == "jita_sell" and sp["sell_order_fallback"] == []
    so = b["sell_orders"]
    assert so["market"] == "Jita 4-4" and so["days"] is None
    assert so["sales_tax_pct"] == s.sales_tax_pct and so["broker_fee_pct"] == s.broker_fee_pct
    assert so["items"] == [{"item": "Biocells", "list_price": 11000.0,
                            "net": round(11000 * (1 - (s.sales_tax_pct + s.broker_fee_pct) / 100), 2),
                            "instant": round(10000 * (1 - s.sales_tax_pct / 100), 2)}]
    rows = selling.compare_table(pi, s, bk, "Jita", [BIOCELLS], False, "Jita", traded())
    d = demand.assess(pi, s, bk, traded(), sp, rows, {BIOCELLS: 100})
    demand.sell_order_days(sp, d)
    assert so["days"] == d["rows"][0]["horizon_days"] and so["days"][0] < so["days"][1]


def test_sell_plan_lists_products_that_fell_back_to_instant_sale(pi):  # noqa: F811
    s = Settings(**ORDERS)
    sp = selling.sell_plan(pi, s, {BIOCELLS: book()}, "Jita", {BIOCELLS: 100}, local=False, history={})
    assert [b["channel"] for b in sp["batches"]] == ["jita_buy"] and "sell_orders" not in sp["batches"][0]
    assert sp["sell_order_fallback"] == [{"item": "Biocells", "market": "Jita 4-4",
                                          "reason": "trade history hasn't loaded yet"}]
    # a product whose buy orders pay more anyway didn't lose anything: nothing to report
    cheap = {BIOCELLS: book(jita_sell=10050.0)}
    assert selling.sell_plan(pi, s, cheap, "Jita", {BIOCELLS: 100}, local=False,
                             history={})["sell_order_fallback"] == []


def _ctx(pi, history, s):  # noqa: F811
    """A miners-only plan sold in Jita; Biofuels' sell orders pay more than its buy orders."""
    bk = {t: {"jita_buy": 800.0, "jita_buy_depth": [[800.0, 10_000_000]]} for t in OTHER_P1}
    bk[BIOFUELS] = book(jita_buy=1000.0, jita_sell=2000.0, jita_buy_depth=[[1000.0, 10_000_000]],
                        jita_sell_depth=[[2000.0, 100]])
    area = _area()
    return dict(pi=pi, s=s, solve_s=s, area=area, systems={int(k): v for k, v in area["systems"].items()},
                chars=CHARS, tpl=TEMPLATES, overrides={}, head_yield=s.head_yield_per_hour, books=bk,
                books_at=1.0, history=history, history_at=None, dropoff="Jita", local=False, origin="Jita",
                origin_jumps=0, seller=None, measured={}, manual_overrides={}, calibrated=None,
                values=selling.best_values(pi, s, bk, "Jita", False, "Jita", history))


def _settings():
    return Settings(hub_system="HUB", max_jumps=1, max_systems=0, effort=100, max_tier=1, **ORDERS)


def test_plan_without_trade_history_values_instant_sale_and_says_so(pi):  # noqa: F811
    s = _settings()
    res = service.run_plan(_ctx(pi, {}, s))
    assert BIOFUELS in {x["type_id"] for x in res["sold"]}
    assert not any(b["channel"].endswith("_sell") for b in res["selling"]["batches"])
    note = next(w for w in res["warnings"] if w["code"] == "sell_order_fallback")
    assert note["level"] == "info" and note["steps"] == ["sell"]
    assert note["text"].startswith("Biofuels is valued at the instant-sale price, not a sell order")
    assert "trade history hasn't loaded yet" in note["text"]


def test_plan_with_trades_sells_by_sell_order_with_its_turnaround(pi):  # noqa: F811
    s = _settings()
    hist = traded(avg_volume=1e6, type_id=BIOFUELS)
    res = service.run_plan(_ctx(pi, hist, s))
    (b,) = [b for b in res["selling"]["batches"] if b["channel"] == "jita_sell"]
    assert list(b["items"]) == ["Biofuels"]
    assert b["sell_orders"]["items"][0]["list_price"] == 2000.0 and b["sell_orders"]["days"]
    assert not any(w["code"] == "sell_order_fallback" for w in res["warnings"])
    sold = next(x for x in res["sold"] if x["type_id"] == BIOFUELS)
    net = 2000 * (1 - (s.sales_tax_pct + s.broker_fee_pct) / 100)
    assert sold["isk_per_day"] == pytest.approx(sold["units_per_day"] * net, rel=1e-3)
