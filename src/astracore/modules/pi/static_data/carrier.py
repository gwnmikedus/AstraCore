"""Courier (and buyback) providers AstraCore prices hauling with.

Every provider is one ``Provider`` in ``PROVIDERS``: who it is (name, corporation, site), where its
tariff comes from (an optional live source with its own parser, read at most once a day, and
fallback routes recorded by hand), whether it runs a buyback, and whether it is active by default.
The planner uses every *active* provider and, per route, the cheapest one. ``ASTRACORE_COURIERS``
(comma-separated ids) overrides which providers are active without a code change, for example
``humpback,voc`` when VOC runs again.

Contracts are recognised for every known provider, active or not, so older shipments keep counting.

Fee rule (all providers so far): the higher of the minimum fee or m³ × rate + collateral × col%.
Add a provider only with its consent and credit it (docs/third-party.md).
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import httpx

from astracore import config, db
from astracore.core.releases import user_agent

JITA = "Jita 4-4"
AMARR = "Amarr VIII - Emperor Family Academy"
MARKET_HUBS = {
    JITA: {"region_id": 10000002, "station_id": 60003760, "label": "Jita"},
    AMARR: {"region_id": 10000043, "station_id": 60008494, "label": "Amarr"},
}
HUB_STATIONS = (JITA, AMARR)

# A typical shipment, used to pick the cheaper provider when two serve the same route.
REFERENCE_M3, REFERENCE_COLLATERAL = 10_000.0, 1_000_000_000.0

Route = Tuple[str, str, float, float, float, float, str]   # origin, dest, min_fee, per_m3, col%, max_m3, frequency


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").replace("%", "").replace(" ", "").strip() or 0)
    except ValueError:
        return 0.0


@dataclass(frozen=True)
class Provider:
    id: str
    name: str                      # short name in running text ("Humpback")
    full_name: str                 # credited name
    corp_name: str                 # the corporation contracts are assigned to
    corp_id: int
    site: str                      # where pilots check prices and terms
    about: str                     # one line for the reference page
    recorded: str                  # when the fallback routes were taken from the site
    fallback: Tuple[Route, ...]
    active_default: bool = True
    status: str = ""               # shown when inactive ("stopped in 2026")
    local_region: str = ""         # region its pickups are in, when that region's market counts as local
    source_url: str = ""           # live tariff (read at most once a day); empty = fallback only
    parse: Optional[Callable[[str], List[dict]]] = None
    buyback_site: str = ""
    buyback_locations: Tuple[str, ...] = ()
    buyback_note: str = ""
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def routes_key(self) -> str:
        return f"courier_routes_{self.id}"

    @property
    def active(self) -> bool:
        return self.id in config.COURIERS if config.COURIERS else self.active_default


# --------------------------------------------------------------------------- tariff parsers
_HUB_ALIASES = {"jita": JITA, "jita 4-4": JITA, "jita iv - moon 4 - caldari navy assembly plant": JITA,
                "amarr": AMARR, "amarr viii - emperor family academy": AMARR}


def _station(name) -> str:
    name = str(name or "").strip()
    return _HUB_ALIASES.get(name.lower(), name)


def parse_humpback(text: str) -> List[dict]:
    """The JSON behind the Dracarys courier calculator: one row per direction."""
    import json
    try:
        rows = json.loads(text)
    except ValueError:
        return []
    routes = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or str(row.get("is_enabled", "1")) != "1":
            continue
        origin, dest = _station(row.get("star_system")), _station(row.get("end_system"))
        per_m3, max_m3 = _num(row.get("price_per_cubic_meter")), _num(row.get("max_value"))
        if not origin or not dest or per_m3 <= 0 or max_m3 <= 0:
            continue
        # The frequency key carries an invisible character on the source; match on its start.
        freq = next((str(v) for k, v in row.items() if str(k).startswith("freight_frequency")), "")
        routes.append({"origin": origin, "dest": dest, "min_fee": _num(row.get("minimum_reward")),
                       "per_m3": per_m3, "collateral_pct": _num(row.get("additional_collateral_rate")),
                       "max_m3": max_m3, "frequency": freq})
    return routes


def parse_voc(page: str) -> List[dict]:
    """The tariff table on vochauling.com (bidirectional rows are listed once)."""
    routes = []
    for m in re.finditer(r'<tr data-origin="([^"]+)" data-dest="([^"]+)" data-bidirectional="(\w+)"[^>]*>(.*?)</tr>',
                         page, re.S):
        origin, dest, bidi, body = html.unescape(m.group(1)), html.unescape(m.group(2)), m.group(3), m.group(4)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
        nums = [c for c in cells[1:] if re.fullmatch(r"[\d,\.]+%?", c.replace(" ", ""))]
        if len(nums) < 4:
            continue
        r = {"origin": _station(origin), "dest": _station(dest), "min_fee": _num(nums[0]), "per_m3": _num(nums[1]),
             "collateral_pct": _num(nums[2]), "max_m3": _num(nums[3]), "frequency": ""}
        routes.append(r)
        if bidi == "true":
            routes.append({**r, "origin": r["dest"], "dest": r["origin"]})
    return routes


# --------------------------------------------------------------------------- providers
HUMPBACK = Provider(
    id="humpback", name="Humpback", full_name="Humpback Whale Logistic",
    corp_name="Humpback Whale Logistic", corp_id=98593679,
    site="https://dc.eve-hs.top/#/tool/tools_kuaidi",
    about="Dracarys.' courier service between its home systems and Jita (daily) or Amarr (weekly).",
    recorded="27 November 2026",
    source_url="https://api.eve-hs.top:13002/getRoute", parse=parse_humpback,
    fallback=(
        ("O4T-Z5", JITA, 5_000_000, 1250, 1.0, 60_000, "Daily"),
        ("R-ARKN", JITA, 5_000_000, 1250, 1.0, 60_000, "Daily"),
        ("O4T-Z5", AMARR, 5_000_000, 1250, 1.0, 60_000, "Weekly"),
        ("R-ARKN", AMARR, 5_000_000, 1250, 1.0, 60_000, "Weekly"),
        (JITA, "O4T-Z5", 5_000_000, 1250, 1.0, 340_000, "Daily"),
        (JITA, "R-ARKN", 5_000_000, 1250, 1.0, 340_000, "Daily"),
        (AMARR, "O4T-Z5", 5_000_000, 1250, 1.0, 340_000, "Weekly"),
        (AMARR, "R-ARKN", 5_000_000, 1250, 1.0, 340_000, "Weekly"),
    ),
)

VOC = Provider(
    id="voc", name="VOC", full_name="VOC Hauling", corp_name="United East-Indian Compagnie", corp_id=98527816,
    site="https://vochauling.com/",
    about="Courier and buyback service in Delve.",
    recorded="10 October 2026", active_default=False, local_region="Delve", status="Stopped in November 2026.",
    source_url="https://vochauling.com/", parse=parse_voc,
    buyback_site="https://buyback.vochauling.com/", buyback_locations=("7G-QIG", "Q-02UL", "RF-K9W"),
    buyback_note="90% of Jita buy for P2–P4, P1 refused (appraisal at 7G-QIG on 10 October 2026).",
    fallback=tuple((o, d, f, m, 1.0, 165_000, "") for o in ("7G-QIG", "E3OI-U", "Q-02UL", "RF-K9W")
                   for d, f, m in ((AMARR, 20_000_000, 650), (JITA, 10_000_000, 1000))),
)

PROVIDERS: List[Provider] = [HUMPBACK, VOC]


def provider(pid: str) -> Optional[Provider]:
    return next((p for p in PROVIDERS if p.id == pid), None)


def active_providers() -> List[Provider]:
    return [p for p in PROVIDERS if p.active]


def by_corp(corp_id) -> Optional[Provider]:
    """The provider (active or not) a contract's assignee or acceptor belongs to."""
    return next((p for p in PROVIDERS if corp_id and p.corp_id == corp_id), None)


# --------------------------------------------------------------------------- buyback
def buyback_provider() -> Optional[Provider]:
    return next((p for p in active_providers() if p.buyback_site), None)


def has_buyback() -> bool:
    return buyback_provider() is not None


def buyback_site() -> str:
    p = buyback_provider()
    return p.buyback_site if p else ""


def buyback_locations() -> List[str]:
    return [loc for p in active_providers() for loc in p.buyback_locations]


def local_pickups(region: str) -> List[str]:
    """Pickups of active providers based in `region` (used before universe data is loaded)."""
    out = [loc for p in active_providers() if p.local_region == region for loc in p.buyback_locations]
    out += [r["origin"] for p in active_providers() if p.local_region == region for r in provider_routes(p)
            if r["dest"] in HUB_STATIONS]
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------- tariffs
def _fallback(p: Provider) -> List[dict]:
    return [{"origin": o, "dest": d, "min_fee": f, "per_m3": m, "collateral_pct": c, "max_m3": x, "frequency": q}
            for o, d, f, m, c, x, q in p.fallback]


def provider_routes(p: Provider) -> List[dict]:
    raw = db.kv_get(p.routes_key)
    routes = raw["routes"] if raw and raw.get("routes") else _fallback(p)
    return [{**r, "provider": p.id} for r in routes]


def routes_cached() -> List[dict]:
    """Every active provider's routes, each tagged with its provider id."""
    return [r for p in active_providers() for r in provider_routes(p)]


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20, headers={"User-Agent": user_agent()})


async def refresh_provider(p: Provider) -> List[dict]:
    if not p.source_url or not p.parse:
        return provider_routes(p)
    try:
        async with _client() as c:
            r = await c.get(p.source_url)
            r.raise_for_status()
        routes = p.parse(r.text)
        if routes:
            db.kv_set(p.routes_key, {"at": time.time(), "routes": routes, "source": p.source_url})
    except (httpx.HTTPError, ValueError):
        pass
    return provider_routes(p)


async def refresh_routes() -> List[dict]:
    for p in active_providers():
        await refresh_provider(p)
    return routes_cached()


def provider_info(p: Provider) -> dict:
    raw = db.kv_get(p.routes_key) or {}
    return {"at": raw.get("at"), "live": bool(raw.get("routes"))}


def routes_info() -> dict:
    """When the active providers' live tariffs were last read: ``at`` is the oldest (None when one with a
    live source was never read), ``live`` = every one of them has a cached live tariff."""
    infos = [provider_info(p) for p in active_providers() if p.source_url]
    if not infos:
        return {"at": None, "live": False}
    ats = [i["at"] for i in infos]
    return {"at": None if None in ats else min(ats), "live": all(i["live"] for i in infos)}


def courier_origins() -> List[str]:
    """Systems an active provider picks up from for Jita or Amarr, in provider order."""
    out: List[str] = []
    for r in routes_cached():
        if r["dest"] in HUB_STATIONS and r["origin"] not in HUB_STATIONS and r["origin"] not in out:
            out.append(r["origin"])
    return out


def courier_fee(r: dict, m3: float, collateral: float) -> float:
    """Higher of the minimum fee or (m3 x rate) + (collateral x col%)."""
    return max(r["min_fee"], m3 * r["per_m3"] + collateral * r["collateral_pct"] / 100.0)


def route(origin: str, dest: str, routes: Optional[List[dict]] = None) -> Optional[dict]:
    """The cheapest route from `origin` to `dest` among the given (default: active providers') routes."""
    found = [r for r in (routes or routes_cached())
             if r["origin"] == origin and r["dest"] == dest]
    if not found:
        return None
    return min(found, key=lambda r: courier_fee(r, REFERENCE_M3, REFERENCE_COLLATERAL))


def pickup_name(origin: str) -> str:
    """Name of the provider whose cheapest route takes goods from `origin` to a trade hub ("courier" if unknown)."""
    best = [r for r in (route(origin, hub) for hub in HUB_STATIONS) if r]
    p = route_provider(min(best, key=lambda r: courier_fee(r, REFERENCE_M3, REFERENCE_COLLATERAL))) if best else None
    return p.name if p else "courier"


def route_provider(r: Optional[dict]) -> Optional[Provider]:
    return provider(r.get("provider", "")) if r else None


def assignee(r: Optional[dict]) -> str:
    """Who a courier contract on this route is assigned to."""
    p = route_provider(r)
    return p.corp_name if p else "the courier"


def courier_variable_per_unit(r: dict, volume: float, collateral_value: float) -> float:
    """Per-unit cost ignoring the minimum fee (used for valuing products)."""
    return volume * r["per_m3"] + collateral_value * r["collateral_pct"] / 100.0


def paste_list(items: Dict[str, float]) -> str:
    """EVE inventory paste format (name<TAB>qty) - works in multibuy, appraisal and buyback tools."""
    return "\n".join(f"{name}\t{int(q)}" for name, q in sorted(items.items()) if q >= 1)
