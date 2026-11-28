"""Plans don't wait on ESI for old prices: old order books are served and refreshed in the background."""
from __future__ import annotations

import asyncio
import time

import pytest

from astracore.modules.pi import service
from astracore.modules.pi.planner import prices
from astracore.modules.pi.static_data import carrier
from astracore.modules.pi.static_data import markets as home

BOOK = {"jita_buy": 9.0, "jita_sell": 10.0, "jita_buy_depth": [[9.0, 50]], "jita_sell_depth": [[10.0, 5]]}


@pytest.fixture
def market(monkeypatch):
    """Stored books and tariffs in memory, and refreshes that only count (and can be held back)."""
    kv = {}
    monkeypatch.setattr(prices.db, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(prices.db, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(service, "_market_task", None)
    monkeypatch.setattr(service, "_routes_task", None)
    monkeypatch.setattr(service, "refresh_history_soon", lambda pi: None)
    monkeypatch.setattr(prices, "history_stale", lambda: False)
    calls = {"prices": 0, "routes": 0}
    gate = {"release": None}

    async def refresh_prices(pi):
        calls["prices"] += 1
        if gate["release"]:
            await gate["release"].wait()
        kv[prices.BOOKS_KEY] = {"at": time.time(), "failed": 0, "books": {"1": BOOK},
                                "home": home.home_region_ids()}
        return True

    async def refresh_routes():
        calls["routes"] += 1
        return []

    monkeypatch.setattr(service, "refresh_prices", refresh_prices)
    monkeypatch.setattr(carrier, "refresh_routes", refresh_routes)
    monkeypatch.setattr(carrier, "routes_info", lambda: {"at": time.time(), "live": True})
    return kv, calls, gate


def _books(kv, age):
    kv[prices.BOOKS_KEY] = {"at": time.time() - age, "failed": 0, "books": {"1": {**BOOK, "jita_buy": 1.0}},
                            "home": home.home_region_ids()}


def test_old_books_are_served_at_once_and_refreshed_in_the_background(market):
    kv, calls, gate = market

    async def scenario():
        gate["release"] = asyncio.Event()
        _books(kv, prices.MAX_AGE + 60)
        books = await asyncio.wait_for(service.market_data(None), 1)    # never waits on the refresh
        assert books[1]["jita_buy"] == 1.0                                 # the stored copy
        assert service.market_refreshing()
        await service.market_data(None)                                    # a second page joins the same refresh
        gate["release"].set()
        await service._market_task
        assert calls["prices"] == 1 and not service.market_refreshing()
        assert (await service.market_data(None))[1]["jita_buy"] == 9.0    # the next page has the new books
        assert calls["prices"] == 1                                        # fresh: nothing more to fetch

    asyncio.run(scenario())


def test_without_usable_books_the_page_waits_for_them(market):
    kv, calls, _ = market

    async def scenario():
        books = await service.market_data(None)                            # nothing stored yet
        assert books[1]["jita_buy"] == 9.0 and calls["prices"] == 1
        kv[prices.BOOKS_KEY]["home"] = [1]                                 # another home market: its books are wrong
        assert prices.missing()
        await service.market_data(None)
        assert calls["prices"] == 2

    asyncio.run(scenario())


def test_courier_tariffs_refresh_in_the_background(market, monkeypatch):
    kv, calls, _ = market
    _books(kv, 0)
    monkeypatch.setattr(carrier, "routes_info", lambda: {"at": time.time() - 2 * 86400, "live": True})

    async def scenario():
        await service.market_data(None)
        await service._routes_task
        assert calls["routes"] == 1

    asyncio.run(scenario())
