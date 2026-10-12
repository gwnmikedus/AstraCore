"""VOC Hauling (United East-Indian Compagnie, EVIL.) courier + buyback.

Courier tariff is read live from https://vochauling.com (falls back to the values
seen on 2026-10-10). Buyback terms come from a test appraisal on
https://buyback.vochauling.com on 2026-10-10: 90% of Jita buy (Janice) for P2-P4,
P1 is refused. Both are editable in Settings.
"""
from __future__ import annotations

import html
import re
import time
from typing import Dict, List, Optional

import httpx

from astracore import db
from astracore.core.releases import user_agent

SITE = "https://vochauling.com/"
BUYBACK_SITE = "https://buyback.vochauling.com/"
CORP_NAME = "United East-Indian Compagnie"
CORP_ID = 98527816
ROUTES_KEY = "voc_routes_v1"

JITA = "Jita 4-4"
AMARR = "Amarr VIII - Emperor Family Academy"
MARKET_HUBS = {
    JITA: {"region_id": 10000002, "station_id": 60003760, "label": "Jita"},
    AMARR: {"region_id": 10000043, "station_id": 60008494, "label": "Amarr"},
}

# Where VOC picks up courier contracts / accepts buyback contracts in (or near) Delve.
COURIER_ORIGINS = ["7G-QIG", "Q-02UL", "RF-K9W", "E3OI-U"]
BUYBACK_LOCATIONS = ["7G-QIG", "Q-02UL", "RF-K9W"]   # + "anywhere in Delve" (no fee)

DEFAULT_ROUTES = [
    # origin, destination, min_fee, per_m3, collateral_pct, max_m3
    ("7G-QIG", AMARR, 20_000_000, 650, 1.0, 165_000),
    ("7G-QIG", JITA, 10_000_000, 1000, 1.0, 165_000),
    ("E3OI-U", AMARR, 20_000_000, 650, 1.0, 165_000),
    ("E3OI-U", JITA, 10_000_000, 1000, 1.0, 165_000),
    ("Q-02UL", AMARR, 20_000_000, 650, 1.0, 165_000),
    ("Q-02UL", JITA, 10_000_000, 1000, 1.0, 165_000),
    ("RF-K9W", AMARR, 20_000_000, 650, 1.0, 165_000),
    ("RF-K9W", JITA, 10_000_000, 1000, 1.0, 165_000),
]

# Buyback payout as a fraction of Jita buy, by PI tier (0 = not accepted).
DEFAULT_BUYBACK = {1: 0.0, 2: 0.90, 3: 0.90, 4: 0.90}


def _num(s: str) -> float:
    s = s.replace(",", "").replace("%", "").strip()
    return float(s) if s else 0.0


def parse_routes(page: str) -> List[dict]:
    routes = []
    for m in re.finditer(r'<tr data-origin="([^"]+)" data-dest="([^"]+)" data-bidirectional="(\w+)"[^>]*>(.*?)</tr>',
                         page, re.S):
        origin, dest, bidi, body = html.unescape(m.group(1)), html.unescape(m.group(2)), m.group(3), m.group(4)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
        nums = [c for c in cells[1:] if re.fullmatch(r"[\d,\.]+%?", c.replace(" ", ""))]
        if len(nums) < 4:
            continue
        r = {"origin": origin, "dest": dest, "min_fee": _num(nums[0]), "per_m3": _num(nums[1]),
             "collateral_pct": _num(nums[2]), "max_m3": _num(nums[3])}
        routes.append(r)
        if bidi == "true":
            routes.append({**r, "origin": dest, "dest": origin})
    return routes


async def refresh_routes() -> List[dict]:
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": user_agent()}) as c:
            r = await c.get(SITE)
            r.raise_for_status()
        routes = parse_routes(r.text)
        if routes:
            db.kv_set(ROUTES_KEY, {"at": time.time(), "routes": routes, "source": SITE})
            return routes
    except httpx.HTTPError:
        pass
    return routes_cached()


def routes_cached() -> List[dict]:
    raw = db.kv_get(ROUTES_KEY)
    if raw and raw.get("routes"):
        return raw["routes"]
    return [{"origin": o, "dest": d, "min_fee": f, "per_m3": m, "collateral_pct": c, "max_m3": x}
            for o, d, f, m, c, x in DEFAULT_ROUTES]


def routes_info() -> dict:
    raw = db.kv_get(ROUTES_KEY) or {}
    return {"at": raw.get("at"), "live": bool(raw.get("routes"))}


def route(origin: str, dest: str, routes: Optional[List[dict]] = None) -> Optional[dict]:
    for r in routes or routes_cached():
        if r["origin"] == origin and r["dest"] == dest:
            return r
    return None


def courier_fee(r: dict, m3: float, collateral: float) -> float:
    """VOC rule: higher of the minimum fee or (m3 x rate) + (collateral x col%)."""
    return max(r["min_fee"], m3 * r["per_m3"] + collateral * r["collateral_pct"] / 100.0)


def courier_variable_per_unit(r: dict, volume: float, collateral_value: float) -> float:
    """Per-unit cost ignoring the minimum fee (used for valuing products)."""
    return volume * r["per_m3"] + collateral_value * r["collateral_pct"] / 100.0


def paste_list(items: Dict[str, float]) -> str:
    """EVE inventory paste format (name<TAB>qty) - works on the buyback and appraisal pages."""
    return "\n".join(f"{name}\t{int(q)}" for name, q in sorted(items.items()) if q >= 1)
