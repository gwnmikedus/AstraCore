"""Order-book prices for PI items at every place you could sell them:
Jita 4-4, Amarr VIII and Delve (local), best buy and best sell for each, plus the visible
buy/sell depth (price levels) and each region's recent daily trade history."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Dict, List, Optional

from astracore import db
from astracore.esi import public
from astracore.esi.client import ESIClient
from ..static_data import voc
from ..static_data.sde_loader import PIData

BOOKS_KEY = "price_books_v1"
DELVE_REGION = 10000060
MAX_AGE = 3 * 3600
HISTORY_KEY = "market_history_v1"
HISTORY_MAX_AGE = 24 * 3600     # ESI publishes regional history once a day
HISTORY_DAYS = 30
DEPTH_LEVELS = 25               # price levels kept per side; plenty for a PI shipment

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
            buys = [o for o in rows if o.get("is_buy_order")]
            sells = [o for o in rows if not o.get("is_buy_order")]
            books[t][f"{market}_buy"] = max(o["price"] for o in buys) if buys else 0.0
            books[t][f"{market}_sell"] = min(o["price"] for o in sells) if sells else 0.0
            books[t][f"{market}_buy_depth"] = depth(buys, best_first=max)
            books[t][f"{market}_sell_depth"] = depth(sells, best_first=min)
    db.kv_set(BOOKS_KEY, {"at": time.time(), "books": {str(k): v for k, v in books.items()}})
    return books


def depth(orders: List[dict], best_first=max) -> List[List[float]]:
    """[[price, units], ...] from the best price outwards, orders at the same price merged.
    Buy orders with a minimum volume above 1 are left out: a shipment can't count on filling them."""
    levels: Dict[float, int] = {}
    for o in orders:
        if int(o.get("min_volume") or 1) > 1:
            continue
        levels[o["price"]] = levels.get(o["price"], 0) + int(o.get("volume_remain") or 0)
    ordered = sorted(levels, reverse=best_first is max)
    return [[p, levels[p]] for p in ordered[:DEPTH_LEVELS] if levels[p] > 0]


def summarise_history(rows: List[dict], today: Optional[date] = None) -> dict:
    """Daily trade history of one item in one region -> what a seller needs: average units traded
    per day over the last HISTORY_DAYS, how many of those days have data, the newest date, and how
    much the average price moved (coefficient of variation, as a fraction)."""
    today = today or date.today()
    start = today - timedelta(days=HISTORY_DAYS)
    recent = []
    for r in rows:
        try:
            d = date.fromisoformat(r["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= d < today:
            recent.append((d, float(r.get("volume") or 0), float(r.get("average") or 0)))
    if not recent:
        return {"avg_volume": 0.0, "days": 0, "window": HISTORY_DAYS, "last": None, "price_cv": None}
    vols = [v for _, v, _ in recent]
    avgs = [a for _, _, a in recent if a > 0]
    cv = None
    if len(avgs) >= 2:
        mean = sum(avgs) / len(avgs)
        cv = (sum((a - mean) ** 2 for a in avgs) / len(avgs)) ** 0.5 / mean if mean else None
    return {"avg_volume": sum(vols) / HISTORY_DAYS, "days": len(recent), "window": HISTORY_DAYS,
            "last": max(d for d, _, _ in recent).isoformat(), "price_cv": cv}


async def refresh_history(esi: ESIClient, pi: PIData) -> Dict[str, Dict[int, dict]]:
    """Recent trade history per market region (Jita = The Forge, Amarr = Domain, Delve)."""
    items = [t for t in pi.items if pi.tier(t) >= 1]
    out: Dict[str, Dict[int, dict]] = {}
    regions = {m: region_id for m, (region_id, _) in MARKETS.items()}
    for market, region_id in regions.items():
        rows = await public.many(public.region_history(esi, region_id, t) for t in items)
        out[market] = {t: summarise_history(r) for t, r in zip(items, rows)}
    db.kv_set(HISTORY_KEY, {"at": time.time(), "markets": {m: {str(k): v for k, v in h.items()}
                                                           for m, h in out.items()}})
    return out


def history_cached() -> dict:
    raw = db.kv_get(HISTORY_KEY) or {}
    return {"at": raw.get("at"), "markets": {m: {int(k): v for k, v in h.items()}
                                             for m, h in (raw.get("markets") or {}).items()}}


def history_stale() -> bool:
    c = history_cached()
    return not c["markets"] or time.time() - (c["at"] or 0) > HISTORY_MAX_AGE


def cached() -> dict:
    raw = db.kv_get(BOOKS_KEY) or {}
    return {"at": raw.get("at"), "books": {int(k): v for k, v in raw.get("books", {}).items()}}


def stale() -> bool:
    c = cached()
    return not c["books"] or time.time() - (c["at"] or 0) > MAX_AGE
