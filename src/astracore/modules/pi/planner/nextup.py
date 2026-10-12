"""Next up: the handful of things to do now, most urgent first (#90).

Operate shows the first few on top and Home the first three; both call `next_up` with what Operate
already works out (upkeep schedule, hangar stock, consolidate advice, pipeline, plan progress), so
there is one list, never two versions of it.

Each item is one line: verb · planet or system · character · deadline, with a link to the section
that has the details. The order:

  0  data:    ESI data older than 3 days, colonies not viewed in game for 3 days (everything below
              is projected from them)
  1  colony:  extractor restarts (stopped or ending within 24 h), factories running out of inputs
              (idle or within 48 h), storage filling up (within 24 h), soonest first
  2  market:  hangar stock to ship or sell, undercut sell orders
  3  plan:    colonies to build, rebuild or remove, a plan out of date, unrouted structures

Within a group the soonest deadline comes first, then the ISK at stake (planned output per day of
the colonies involved, or the ISK value for market items).
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Optional

from astracore.core import fmt

STALE_DATA_H = 72        # older than this, everything else on the list is a guess
RESTART_H = 24           # extractors ending within this
RESTOCK_H = 48           # factory inputs running out within this
COLLECT_H = 24           # storage full within this
STOCK_ISK = 500e6        # hangar stock worth this much is worth a trip even before the shipment is due
SHOWN = 6                # Operate shows at most this many; Home shows HOME_SHOWN
HOME_SHOWN = 3

DATA, COLONY, MARKET, PLAN = 0, 1, 2, 3
_RANK = {"refresh": 0, "view": 1, "restart": 2, "restock": 3, "collect": 4, "ship": 5, "undercut": 6,
         "recalculate": 7, "build": 8, "rebuild": 9, "remove": 10, "replan": 11, "routes": 12}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _item(kind: str, group: int, verb: str, href: str, *, where: str = "", system: str = "",
          character: str = "", hours: Optional[float] = None, when: str = "", isk: float = 0.0,
          level: str = "warn") -> dict:
    return {"kind": kind, "group": group, "verb": verb, "href": href, "where": where, "system": system,
            "character": character, "hours": hours, "when": when, "isk": isk, "level": level}


def _colony_items(kind: str, verb: str, href: str, rows: List[dict], when) -> List[dict]:
    """One line per character and system: '3 planets' when several colonies there need the same."""
    groups: Dict[tuple, List[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["character"], r.get("system") or "")].append(r)
    out = []
    for (who, system), rs in groups.items():
        planets = sorted({r["planet"] for r in rs})
        h = min(r["hours"] for r in rs)
        out.append(_item(kind, COLONY, verb, href,
                         where=planets[0] if len(planets) == 1 else _plural(len(planets), "planet", "planets"),
                         system=system, character=who, hours=h, when=when(h, rs),
                         isk=sum(r.get("value_per_day") or 0 for r in rs),
                         level="bad" if h <= 0 else "warn"))
    return out


def _restart_when(h: float, rs) -> str:
    return "stopped" if h <= 0 else f"ends in {fmt.hours(h)}"


def _restock_when(h: float, rs) -> str:
    return "idle now" if h <= 0 else f"runs out in {fmt.hours(h)}"


def _collect_when(h: float, rs) -> str:
    return "full now" if h <= 0 else f"full in {fmt.hours(h)}"


def _data_items(upkeep: dict, now: float) -> List[dict]:
    out = []
    for f in upkeep.get("freshness") or []:
        synced = f.get("synced_at") or 0
        if not synced or now - synced > STALE_DATA_H * 3600:
            out.append(_item("refresh", DATA, "Refresh ESI data", "#freshness", character=f["character"],
                             when=f"updated {fmt.ago(synced)}" if synced else "never read", level="bad"))
        elif f.get("colony_update") and now - f["colony_update"] > STALE_DATA_H * 3600:
            out.append(_item("view", DATA, "Open colonies in EVE so ESI updates them", "#upkeep",
                             character=f["character"], when=f"colony data {fmt.ago(f['colony_update'])}"))
    return out


def _market_items(upkeep: dict, stock: Optional[List[dict]], consolidated: Optional[dict],
                  pipe: Optional[dict]) -> List[dict]:
    out = []
    ship = (upkeep.get("tracks") or {}).get("ship") or {}
    value = (consolidated or {}).get("total_value") or sum(g.get("jita_value") or 0 for g in stock or [])
    if stock and value and (ship.get("due") or value >= STOCK_ISK):
        top = stock[0]          # hangar_stock sorts by value: the biggest stack first
        how = ((consolidated or {}).get("advice") or [{}])[0].get("label")
        whos = sorted({g["character"] for g in stock})
        where = top["location"] if len(stock) == 1 else f"{top['location']} + {len(stock) - 1} more"
        out.append(_item("ship", MARKET, f"Sell {fmt.isk(value)} in hangars" + (f" · {how}" if how else ""),
                         "#consolidate", where=where, system=top.get("system") or "",
                         character=whos[0] if len(whos) == 1 else _plural(len(whos), "character", "characters"),
                         hours=0.0 if ship.get("due") else None,
                         when="shipment due" if ship.get("due") else "", isk=value))
    under: Dict[tuple, List[dict]] = defaultdict(list)
    for o in (pipe or {}).get("orders") or []:
        if o.get("undercut"):
            under[(o["character"], o.get("location") or "")].append(o)
    for (who, loc), os_ in under.items():
        out.append(_item("undercut", MARKET, f"Update {_plural(len(os_), 'undercut sell order', 'undercut sell orders')}",
                         "#orders", where=loc, character=who, isk=sum(o.get("value") or 0 for o in os_)))
    return out


def _plan_items(upkeep: dict, plan: Optional[dict], progress: Optional[dict], drift: Optional[dict]) -> List[dict]:
    out = []
    if plan and (plan.get("totals") or {}).get("needs_recalculation"):
        out.append(_item("recalculate", PLAN, "Recalculate your plan", "/pi/plan",
                         when="a character was removed", level="bad"))
    if progress:
        if progress.get("new"):
            out.append(_item("build", PLAN, f"Build {_plural(progress['new'], 'new colony', 'new colonies')}",
                             "#first-build", when=f"{progress['done']} of {progress['total']} built", level="info"))
        if progress.get("rebuild"):
            out.append(_item("rebuild", PLAN, f"Rebuild {_plural(progress['rebuild'], 'colony', 'colonies')} "
                             "for the planned product", "#first-build", level="info"))
        if progress.get("removals"):
            out.append(_item("remove", PLAN, f"Remove {_plural(progress['removals'], 'colony', 'colonies')} "
                             "the plan doesn't use", "#first-build", level="info"))
    if drift and not (plan and (plan.get("totals") or {}).get("needs_recalculation")):
        out.append(_item("replan", PLAN, "Update your plan", "/pi/plan", when=drift.get("summary") or "",
                         level="info"))
    for r in upkeep.get("colonies") or []:
        if r.get("route_issues"):
            out.append(_item("routes", PLAN, "Fix routes", "#schedule", where=r["planet"], system=r.get("system") or "",
                             character=r["character"],
                             when=_plural(r["route_issues"], "structure issue", "structure issues"),
                             isk=r.get("value_per_day") or 0))
    return out


def next_up(upkeep: Optional[dict], *, stock: Optional[List[dict]] = None, consolidated: Optional[dict] = None,
            pipe: Optional[dict] = None, plan: Optional[dict] = None, progress: Optional[dict] = None,
            drift: Optional[dict] = None, now: Optional[float] = None) -> List[dict]:
    """Every action worth doing now, most urgent first (callers show the first few)."""
    now = time.time() if now is None else now
    upkeep = upkeep or {}
    rows = upkeep.get("colonies") or []
    restarts = [{**r, "hours": r["restart_hours"]} for r in rows
                if r.get("restart_hours") is not None and r["restart_hours"] < RESTART_H]
    restocks = [{**r, "hours": r["days_left"] * 24} for r in upkeep.get("shortages") or []
                if r["days_left"] * 24 < RESTOCK_H]
    collects = [{**r, "hours": r["collect_hours"]} for r in rows
                if r.get("collect_hours") is not None and r["collect_hours"] < COLLECT_H]
    items = (_data_items(upkeep, now)
             + _colony_items("restart", "Restart extractors", "#extractors", restarts, _restart_when)
             + _colony_items("restock", "Restock factory inputs", "#factories", restocks, _restock_when)
             + _colony_items("collect", "Collect products before storage fills", "#pickups", collects, _collect_when)
             + _market_items(upkeep, stock, consolidated, pipe)
             + _plan_items(upkeep, plan, progress, drift))
    items.sort(key=lambda i: (i["group"], max(0.0, i["hours"]) if i["hours"] is not None else 1e9,
                              _RANK[i["kind"]], -(i["isk"] or 0)))
    return items


def all_clear(upkeep: Optional[dict]) -> Optional[str]:
    """When nothing is urgent: the next thing that will be, so a calm list still says when to come back."""
    tracks = (upkeep or {}).get("tracks") or {}
    nxt = [(h, what) for h, what in (((tracks.get("restart") or {}).get("next_hours"), "extractor restart"),
                                      ((tracks.get("restock") or {}).get("next_hours"), "factory restock"),
                                      ((tracks.get("collect") or {}).get("next_hours"), "pickup before storage fills"))
           if h is not None and h > 0]
    if not nxt:
        return None
    h, what = min(nxt)
    return f"Next {what} in {fmt.hours(h)}."
