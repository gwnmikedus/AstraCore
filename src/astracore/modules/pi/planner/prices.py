"""Order-book prices for PI items at every place you could sell them (and command centers,
where you could buy them): Jita 4-4, Amarr VIII and the home market (the home regions together, see
static_data/markets.py), best buy and best sell for each,
plus the visible buy/sell depth (price levels) and each region's recent daily trade history."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from astracore import db
from astracore.esi import public
from astracore.esi.client import ESIClient, ESIError, ESIUnavailable
from ..static_data import carrier, markets as home
from ..static_data.pi_rules import COMMAND_CENTER_TYPES
from ..static_data.sde_loader import PIData

# v2: every market side carries its depth. v1 entries could have a best price but no depth, which the
# demand check read as "no visible buyers" while the plan still sold into those buy orders.
# v3: the local market is "home" (the configured home regions), no longer Delve.
BOOKS_KEY = "price_books_v3"
MAX_AGE = 3 * 3600
INCOMPLETE_MAX_AGE = 10 * 60    # some order books didn't load: try again soon
HISTORY_KEY = "market_history_v2"
HISTORY_MAX_AGE = 24 * 3600     # ESI publishes regional history once a day
HISTORY_DAYS = 30
DEPTH_LEVELS = 25               # price levels kept per side; plenty for a PI shipment

HUBS = {
    "jita": (carrier.MARKET_HUBS[carrier.JITA]["region_id"], carrier.MARKET_HUBS[carrier.JITA]["station_id"]),
    "amarr": (carrier.MARKET_HUBS[carrier.AMARR]["region_id"], carrier.MARKET_HUBS[carrier.AMARR]["station_id"]),
}


def markets() -> Dict[str, List[Tuple[int, int]]]:
    """Market key -> [(region id, station id or 0 for the whole region)]. "home" spans every home region."""
    return {**{k: [v] for k, v in HUBS.items()}, "home": [(rid, 0) for rid in home.home_region_ids()]}


def loaded(book: Optional[dict], market: str) -> bool:
    """Whether this item's buy book at `market` was actually fetched (an empty book is still loaded)."""
    return f"{market}_buy_depth" in (book or {})


async def refresh(esi: ESIClient, pi: PIData) -> Dict[int, dict]:
    """Fetch every order book. A book ESI didn't return keeps its last good copy, or is left out (and
    reported as not loaded), so a failed fetch never looks like a market without buyers."""
    # PI products plus the command centers on the first-build shopping list
    items = [t for t in pi.items if pi.tier(t) >= 1] + list(COMMAND_CENTER_TYPES.values())
    previous = cached()
    books: Dict[int, dict] = {t: {} for t in items}
    failed = 0
    places = markets()
    for market, regions in places.items():
        orders: List[Optional[list]] = [[] for _ in items]
        station_id = regions[0][1] if len(regions) == 1 else 0
        for region_id, _ in regions:
            got = await public.many(public.region_orders(esi, region_id, t, force=True) for t in items)
            for i, rows in enumerate(got):
                # one region that didn't answer makes the whole book unknown, never "fewer orders"
                orders[i] = None if rows is None or orders[i] is None else orders[i] + rows
        for t, rows in zip(items, orders):
            if rows is None:
                failed += 1
                old = previous["books"].get(t) or {}
                if loaded(old, market):
                    books[t].update({k: v for k, v in old.items() if k.startswith(f"{market}_")})
                continue
            if station_id:
                rows = [o for o in rows if o.get("location_id") == station_id]
            buys = [o for o in rows if o.get("is_buy_order")]
            sells = [o for o in rows if not o.get("is_buy_order")]
            books[t][f"{market}_buy"] = max(o["price"] for o in buys) if buys else 0.0
            books[t][f"{market}_sell"] = min(o["price"] for o in sells) if sells else 0.0
            books[t][f"{market}_buy_depth"] = depth(buys, best_first=max)
            books[t][f"{market}_sell_depth"] = depth(sells, best_first=min)
            if not station_id:
                # region-wide book: remember where its cheapest seller is (to buy from, e.g. command centers)
                books[t][f"{market}_sell_at"] = cheapest_at(sells)
    if failed == len(items) * len(places):
        # ESI didn't answer at all: keep the last books (still stale, so the next plan tries again)
        return previous["books"]
    await name_locations(esi, [b.get("home_sell_at") for b in books.values()])
    db.kv_set(BOOKS_KEY, {"at": time.time(), "failed": failed, "home": home.home_region_ids(),
                          "books": {str(k): v for k, v in books.items()}})
    return books


def cheapest_at(sells: List[dict]) -> Optional[dict]:
    """Location of the cheapest sell order in a region-wide book, and how many units sell at that
    price there. Names are filled in by name_locations."""
    if not sells:
        return None
    best = min(sells, key=lambda o: o["price"])
    lid = best.get("location_id")
    units = sum(int(o.get("volume_remain") or 0) for o in sells
                if o.get("location_id") == lid and o["price"] == best["price"])
    return {"location_id": lid, "system_id": best.get("system_id"), "price": best["price"], "units": units,
            "station": None, "system": None, "structure": bool(lid and lid > 1_000_000_000_000)}


async def name_locations(esi: ESIClient, locs: List[Optional[dict]]) -> None:
    """Name NPC stations and systems through public ESI. A player structure's name needs a docking
    character's token, so it keeps only its system's name."""
    locs = [x for x in locs if x]
    ids = {x["system_id"] for x in locs if x.get("system_id")}
    ids |= {x["location_id"] for x in locs if x.get("location_id") and 60_000_000 <= x["location_id"] < 64_000_000}
    try:
        names = await public.ids_to_names(esi, ids) if ids else {}
    except ESIError:
        names = {}
    for x in locs:
        x["system"] = names.get(x.get("system_id"))
        x["station"] = None if x.get("structure") else names.get(x.get("location_id"))


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
    return {"avg_volume": sum(vols) / HISTORY_DAYS, "days": len({d for d, _, _ in recent}), "window": HISTORY_DAYS,
            "last": max(d for d, _, _ in recent).isoformat(), "price_cv": cv}


async def refresh_history(esi: ESIClient, pi: PIData) -> Dict[str, Dict[int, dict]]:
    """Recent trade history per market (Jita = The Forge, Amarr = Domain, home = every home region together)."""
    items = [t for t in pi.items if pi.tier(t) >= 1]
    previous = history_cached()["markets"]
    out: Dict[str, Dict[int, dict]] = {}
    regions = {m: [rid for rid, _ in places] for m, places in markets().items()}
    failed = 0
    for market, region_ids in regions.items():
        rows: List[Optional[list]] = [[] for _ in items]
        for region_id in region_ids:
            got = await public.many(public.region_history(esi, region_id, t) for t in items)
            rows = [None if g is None or r is None else r + g for r, g in zip(rows, got)]
        out[market] = {}
        for t, r in zip(items, rows):
            if r is None:     # ESI didn't answer: keep the last summary rather than "nothing traded"
                failed += 1
                r_old = (previous.get(market) or {}).get(t)
                out[market][t] = r_old if r_old is not None else summarise_history([])
            else:
                out[market][t] = summarise_history(r)
    if items and failed == len(items) * len(regions):
        raise ESIUnavailable("no trade history loaded", "unreachable")   # keep the last copy, retry later
    db.kv_set(HISTORY_KEY, {"at": time.time(), "home": home.home_region_ids(),
                            "markets": {m: {str(k): v for k, v in h.items()}
                                                           for m, h in out.items()}})
    return out


def history_cached() -> dict:
    raw = db.kv_get(HISTORY_KEY) or {}
    return {"at": raw.get("at"), "markets": {m: {int(k): v for k, v in h.items()}
                                             for m, h in (raw.get("markets") or {}).items()}}


def history_stale() -> bool:
    c = history_cached()
    moved = (db.kv_get(HISTORY_KEY) or {}).get("home") != home.home_region_ids()   # the home regions changed
    return not c["markets"] or moved or time.time() - (c["at"] or 0) > HISTORY_MAX_AGE


def cached() -> dict:
    raw = db.kv_get(BOOKS_KEY) or {}
    return {"at": raw.get("at"), "failed": raw.get("failed") or 0,
            "books": {int(k): v for k, v in raw.get("books", {}).items()}}


def missing() -> bool:
    """No usable order books at all: none stored yet, or the home regions changed since they were read (the home
    market's books would be another region's). Merely old books are still usable."""
    return not cached()["books"] or (db.kv_get(BOOKS_KEY) or {}).get("home") != home.home_region_ids()


def stale() -> bool:
    c = cached()
    max_age = INCOMPLETE_MAX_AGE if c["failed"] else MAX_AGE
    moved = (db.kv_get(BOOKS_KEY) or {}).get("home") != home.home_region_ids()   # the home regions changed
    return not c["books"] or moved or time.time() - (c["at"] or 0) > max_age
