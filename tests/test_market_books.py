"""Order books that didn't load (old cache shape, ESI errors) must never read as "no buyers", and the
re-plan around thin markets must describe the plan it kept. Offline: fake books and a fake ESI."""
from __future__ import annotations

import asyncio
import time

import pytest

from astracore.modules.pi import service
from astracore.modules.pi.planner import demand, prices
from astracore.modules.pi.settings import Settings
from test_demand import BIOCELLS, assess, books, history
from test_planner import pi  # noqa: F401 - shared SDE fixture

JITA_ONLY = dict(use_buyback=False, use_local=False, use_amarr=False)


# --- demand check ----------------------------------------------------------------------
def test_missing_order_book_is_unknown_not_short(pi):  # noqa: F811
    s = Settings(**JITA_ONLY)
    d = assess(pi, s, books(), history(), "Jita", {BIOCELLS: 1000}, local=False)   # best price, no depth
    row = d["rows"][0]
    assert row["status"] == "unknown" and row["book_missing"] and row["immediate"] is None
    assert "Order book not loaded" in row["advice"] and "no visible" not in row["advice"]
    assert not d["warnings"] and d["books_missing"] == ["Biocells"]
    # the planner keeps the quoted value: a missing book is no evidence of thin demand
    assert demand.realistic_values(d, {BIOCELLS: row["value"]}) == {}


def test_only_minimum_volume_buy_orders_are_named_as_such(pi):  # noqa: F811
    s = Settings(**JITA_ONLY)
    d = assess(pi, s, books(jita_buy_depth=[]), history(), "Jita", {BIOCELLS: 1000}, local=False)
    row = d["rows"][0]
    assert row["status"] == "short" and row["min_volume_only"] and not row["book_missing"]
    assert "minimum volume" in row["advice"] and row["reason"] == "Jita 4-4 only has minimum-volume buy orders"


def test_loaded_book_is_not_reported_missing(pi):  # noqa: F811
    s = Settings(**JITA_ONLY)
    d = assess(pi, s, books(jita_buy_depth=[[10000.0, 1_000_000]]), history(), "Jita", {BIOCELLS: 1000},
               local=False)
    assert d["rows"][0]["status"] == "ok" and d["books_missing"] == []


# --- price cache -----------------------------------------------------------------------
class _PI:
    items = [BIOCELLS]

    @staticmethod
    def tier(t):
        return 1


@pytest.fixture
def kv(monkeypatch):
    store = {}
    monkeypatch.setattr(prices.db, "kv_get", lambda k: store.get(k))
    monkeypatch.setattr(prices.db, "kv_set", lambda k, v: store.__setitem__(k, v))

    async def no_names(esi, locs):
        return None
    monkeypatch.setattr(prices, "name_locations", no_names)
    return store


def _orders(monkeypatch, answer):
    async def region_orders(esi, region_id, type_id, force=False):
        return answer(region_id, type_id)
    monkeypatch.setattr(prices.public, "region_orders", region_orders)


def test_cache_key_is_versioned_past_books_without_depth():
    assert prices.BOOKS_KEY != "price_books_v1"


def test_failed_fetch_keeps_the_last_good_book_or_leaves_it_out(kv, monkeypatch):
    jita = prices.MARKETS["jita"]
    good = {"jita_buy": 9.0, "jita_sell": 10.0, "jita_buy_depth": [[9.0, 50]], "jita_sell_depth": [[10.0, 5]]}
    kv[prices.BOOKS_KEY] = {"at": time.time() - 99_999, "books": {str(BIOCELLS): good}}
    # Jita fails, the other markets answer with an empty book
    _orders(monkeypatch, lambda region, t: None if region == jita[0] else [])
    books = asyncio.run(prices.refresh(None, _PI))
    b = books[BIOCELLS]
    assert b["jita_buy_depth"] == [[9.0, 50]] and b["jita_buy"] == 9.0      # last good copy, not "empty"
    assert prices.loaded(b, "amarr") and b["amarr_buy_depth"] == []          # really empty: loaded
    assert kv[prices.BOOKS_KEY]["failed"] > 0
    # an incomplete fetch is retried soon instead of being trusted for hours
    kv[prices.BOOKS_KEY]["at"] = time.time() - prices.INCOMPLETE_MAX_AGE - 1
    assert prices.stale()

    # no earlier copy: the failed market is left out and the demand check calls it "not loaded"
    kv.clear()
    books = asyncio.run(prices.refresh(None, _PI))
    assert not prices.loaded(books[BIOCELLS], "jita") and "jita_buy" not in books[BIOCELLS]


def test_total_failure_never_replaces_books_with_an_empty_market(kv, monkeypatch):
    old = {"at": 1.0, "books": {str(BIOCELLS): {"jita_buy": 9.0, "jita_buy_depth": [[9.0, 50]]}}}
    kv[prices.BOOKS_KEY] = dict(old)
    _orders(monkeypatch, lambda region, t: None)
    books = asyncio.run(prices.refresh(None, _PI))
    assert books[BIOCELLS]["jita_buy_depth"] == [[9.0, 50]]
    assert kv[prices.BOOKS_KEY] == old and prices.stale()                    # untouched, retried next plan


def test_fresh_complete_books_are_not_stale(kv, monkeypatch):
    _orders(monkeypatch, lambda region, t: [])
    asyncio.run(prices.refresh(None, _PI))
    assert kv[prices.BOOKS_KEY]["failed"] == 0 and not prices.stale()


# --- re-plan message and batch values ---------------------------------------------------
def test_replan_lists_kept_and_dropped_products_separately(pi):  # noqa: F811
    biofuels, bacteria = 2396, 2393
    first = {"demand": {"rows": [
        {"type_id": biofuels, "reason": "buyers in Jita 4-4 can't take a full batch"},
        {"type_id": bacteria, "reason": "a full batch pushes the Jita 4-4 price down too far"}]}}
    again = {"sold": [{"type_id": bacteria}], "demand": {"replanned": [], "dropped": []}}
    service._describe_replan(pi, first, again, {biofuels: 2000.0, bacteria: 800.0},
                             {biofuels: 0.0, bacteria: 700.0})
    d = again["demand"]
    assert [r["item"] for r in d["replanned"]] == [pi.name(bacteria)] and d["replanned"][0]["realistic"] == 700.0
    assert d["dropped"] == [{"type_id": biofuels, "item": "Biofuels",
                             "reason": "buyers in Jita 4-4 can't take a full batch"}]
    msg = service.replan_summary(d, 14_172_551.4)
    assert msg.startswith("We adjusted the plan to what buyers can really take: 1 product counted at a lower "
                          "price, Biofuels dropped.")
    assert "14.2M ISK/day" in msg and "0.00" not in msg


def test_sell_plan_counts_replanned_products_at_their_real_value():
    sp = {"every_days": 2, "batches": [
        {"channel": "jita_buy", "items": {"Bacteria": 100.0, "Water": 50.0}, "net": 100_000},
        {"channel": "jita_buy", "items": {"Bacteria": 10.0}, "net": 9_000, "hold": True}]}
    channels = [{"type_id": 1, "item": "Bacteria", "channels": {"jita_buy": 900.0}},
                {"type_id": 2, "item": "Water", "channels": {"jita_buy": 200.0}}]
    service.count_realistic(sp, channels, {1: 600.0})
    first = sp["batches"][0]
    assert first["quoted_net"] == 100_000 and first["net"] == 100_000 - 100 * 300
    assert sp["net_per_cycle"] == 70_000 and sp["net_per_day"] == 35_000     # held batch not counted
