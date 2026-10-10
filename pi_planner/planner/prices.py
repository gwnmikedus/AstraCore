"""Order-book prices for PI items at every place you could sell them:
Jita 4-4, Amarr VIII and Delve (local), best buy and best sell for each."""
from __future__ import annotations

import time
from typing import Dict

from .. import db
from ..esi import public
from ..esi.client import ESIClient
from ..static_data import voc
from ..static_data.sde_loader import PIData

BOOKS_KEY = "price_books_v1"
DELVE_REGION = 10000060
MAX_AGE = 3 * 3600

MARKETS = {
    "jita": (voc.MARKET_HUBS[voc.JITA]["region_id"], voc.MARKET_HUBS[voc.JITA]["station_id"]),
    "amarr": (voc.MARKET_HUBS[voc.AMARR]["region_id"], voc.MARKET_HUBS[voc.AMARR]["station_id"]),
    "delve": (DELVE_REGION, 0),   # whole region
}


async def refresh(esi: ESIClient, pi: PIData) -> Dict[int, dict]:
    items = [t for t in pi.items if pi.tier(t) >= 1]
    books: Dict[int, dict] = {t: {} for t in items}
    for market, (region_id, station_id) in MARKETS.items():
        orders = await public.many(public.region_orders(esi, region_id, t, force=True) for t in items)
        for t, rows in zip(items, orders):
            if station_id:
                rows = [o for o in rows if o.get("location_id") == station_id]
            buys = [o["price"] for o in rows if o.get("is_buy_order")]
            sells = [o["price"] for o in rows if not o.get("is_buy_order")]
            books[t][f"{market}_buy"] = max(buys) if buys else 0.0
            books[t][f"{market}_sell"] = min(sells) if sells else 0.0
    db.kv_set(BOOKS_KEY, {"at": time.time(), "books": {str(k): v for k, v in books.items()}})
    return books


def cached() -> dict:
    raw = db.kv_get(BOOKS_KEY) or {}
    return {"at": raw.get("at"), "books": {int(k): v for k, v in raw.get("books", {}).items()}}


def stale() -> bool:
    c = cached()
    return not c["books"] or time.time() - (c["at"] or 0) > MAX_AGE
