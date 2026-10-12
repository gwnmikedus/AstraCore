"""Upkeep schedule: when each colony really needs a visit, and why.

Four separate rhythms, never one general cadence:
  * extractor restarts  - when an extractor program ends (ESI expiry time)
  * factory restocks    - when imported inputs run out, and how much one launchpad load covers
  * collection visits   - when launchpad/storage space fills with products
  * market shipments    - the selling plan's shipment cycle (`ship_every_days`)

Colony contents in ESI are a snapshot from the last time the colony was viewed in game
(`last_update`), so stock and storage levels are projected forward from that moment at the
measured rates. Planned colonies are checked the same way from their template layout.

Synced colonies are also checked for routes: a factory without a route for one of its inputs, or
without a route taking its product away, and an extractor whose product goes nowhere, are flagged
and left out of the measured output. Colonies stored before routes were synced are "routes unknown"
until the next ESI refresh, never an error.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Optional

from ..settings import Settings
from ..static_data import extraction
from ..static_data import pi_rules as R
from ..static_data.sde_loader import PIData
from astracore.esi.character import locations

from .operate import _ts, colony_name, pi_buyback, pi_shipment, planet_names

SYNC_STALE_H = 24        # an ESI refresh older than this is flagged
COLONY_STALE_H = 72      # colony not viewed in game for this long: contents are a projection
SOON_H = 24
ON_PLAN = 0.9            # actual output at or above 90% of the plan counts as on plan


def _m3(pi: PIData, per_type: Dict[int, float]) -> float:
    return sum(q * pi.volume(t) for t, q in per_type.items())


def _by_name(pi: PIData, per_name: Dict[str, float]) -> Dict[int, float]:
    return {pi.by_name[n.lower()]: q for n, q in (per_name or {}).items() if n.lower() in pi.by_name}


def _due(hours: Optional[float]) -> str:
    if hours is None:
        return "ok"
    return "expired" if hours <= 0 else ("soon" if hours < SOON_H else "ok")


def plan_capacity(layout: Optional[dict]) -> float:
    """Launchpad + storage space of a planned colony's template (plus its command center)."""
    layout = layout or {}
    return (layout.get("launchpads", 0) * R.STORAGE_M3["launchpad"]
            + layout.get("storage", 0) * R.STORAGE_M3["storage"] + R.STORAGE_M3["cc"])


def plan_buffer(pi: PIData, col: dict, cycle_days: float) -> dict:
    """Check a planned colony's imports and exports against its launchpad/storage space.

    A restock visit drops off N days of inputs and takes the products made since the last
    visit, so space must hold max(inputs, outputs) for the whole interval."""
    cap = plan_capacity(col.get("layout"))
    in_m3 = _m3(pi, _by_name(pi, col.get("in_per_day")))
    out_m3 = _m3(pi, _by_name(pi, col.get("out_per_day")))
    flow = max(in_m3, out_m3)
    fill = cap / flow if flow > 0 else None
    has_space = bool((col.get("layout") or {}).get("launchpads") or (col.get("layout") or {}).get("storage"))
    issues = []
    if col.get("kind") == "miner":
        visit = min(cycle_days, fill) if fill else cycle_days
        reason = "extractor restart" if not fill or fill >= cycle_days else "collection"
        if fill is not None and fill < cycle_days:
            issues.append(f"Products fill its {cap:,.0f} m³ in {fill:.1f} days, before the {cycle_days:g}-day "
                          f"extractor program ends: collect in between or add storage.")
    else:
        visit = fill
        reason = "factory restock"
        if fill is not None and fill < cycle_days:
            issues.append(f"Holds {fill:.1f} days of inputs ({in_m3:,.0f} m³/day) in {cap:,.0f} m³: a restock "
                          f"visit every {fill:.1f} days, more often than your {cycle_days:g}-day extractor rhythm.")
    if not has_space and flow > 0:
        issues.insert(0, "No launchpad or storage facility in the template: only the command center's 500 m³ buffers it.")
    return {"capacity_m3": round(cap), "in_m3_day": round(in_m3, 1), "out_m3_day": round(out_m3, 1),
            "fill_days": None if fill is None else round(fill, 1),
            "visit_every_days": None if visit is None else round(visit, 1), "reason": reason,
            "restock": {n: round(q * visit) for n, q in (col.get("in_per_day") or {}).items()} if visit else {},
            "issues": issues}


def _extractors(pins: List[dict], now: float, idle: frozenset = frozenset()) -> List[dict]:
    """Extractor programs; `idle` pins (output not routed) still need restarts but deliver nothing."""
    out = []
    for p in pins:
        ex = p.get("extractor_details")
        if not ex:
            continue
        start, end = _ts(p.get("install_time")), _ts(p.get("expiry_time"))
        cycle = extraction.normalise_cycle_time(ex.get("cycle_time") or 0)
        per_day = 0.0
        if start and end and end > now and cycle and ex.get("qty_per_cycle") and p.get("pin_id") not in idle:
            per_day = extraction.avg_per_hour(ex["qty_per_cycle"], cycle, end - start) * 24
        out.append({"product": ex.get("product_type_id"), "per_day": per_day,
                    "hours_left": None if end is None else (end - now) / 3600,
                    "program_days": (end - start) / 86400 if start and end and end > start else None})
    return out


def _factory_name(pi: PIData, sch, n: int = 1) -> str:
    tier = pi.tier(sch.output)
    key = "basic" if tier <= 1 else ("hightech" if tier >= 4 else "advanced")
    name = R.STRUCTURE_NAMES[key]
    if n == 1:
        return name
    return name[:-1] + "ies" if name.endswith("y") else name + "s"


def route_check(pi: PIData, col: dict) -> Optional[dict]:
    """Are the colony's factories and extractors actually routed? None when the stored colony has
    no routes yet (synced before routes were kept): unknown until the next ESI refresh.

    Returns the issues plus which factory and extractor pins really run, so the measured output
    leaves out structures that can't receive their inputs or send their products anywhere."""
    routes = col.get("routes")
    if routes is None:
        return None
    pins = col.get("pins", []) or []
    ids = {p["pin_id"] for p in pins if p.get("pin_id") is not None}
    into, out_of = set(), set()     # (pin, content type) with a route arriving / leaving
    for r in routes:
        src, dst, t = r.get("source_pin_id"), r.get("destination_pin_id"), r.get("content_type_id")
        if src in ids and dst in ids and (r.get("quantity") or 0) > 0:
            into.add((dst, t))
            out_of.add((src, t))

    idle_pins, issues = set(), []
    # group identical factories so 12 unrouted ones make one issue, not twelve
    groups: Dict[int, List[dict]] = defaultdict(list)
    for p in pins:
        if p.get("schematic_id") in pi.schematics and p.get("pin_id") is not None:
            groups[p["schematic_id"]].append(p)
    for sid, group in groups.items():
        sch = pi.schematics[sid]
        product = pi.name(sch.output)
        missing_in, missing_out = defaultdict(int), 0
        for p in group:
            pid, ok = p["pin_id"], True
            for t in sch.inputs:
                if (pid, t) not in into:
                    missing_in[t] += 1
                    ok = False
            if (pid, sch.output) not in out_of:
                missing_out += 1
                ok = False
            if not ok:
                idle_pins.add(pid)
        n = len(group)

        def which(k):
            return (f"the {_factory_name(pi, sch)}" if n == 1 else
                    f"{'all ' if k == n else f'{k} of '}{n} {_factory_name(pi, sch, n)}") + f" making {product}"
        for t, k in missing_in.items():
            issues.append(f"{pi.name(t)} isn't routed into {which(k)}.")
        if missing_out:
            issues.append(f"{product} isn't routed out of {which(missing_out)} to storage, a launchpad or "
                          "another factory.")

    unrouted = defaultdict(int)
    for p in pins:
        ex = p.get("extractor_details")
        if ex and p.get("pin_id") is not None and ex.get("product_type_id") \
                and (p["pin_id"], ex["product_type_id"]) not in out_of:
            unrouted[ex["product_type_id"]] += 1
            idle_pins.add(p["pin_id"])
    for t, k in unrouted.items():
        what = "an extractor" if k == 1 else f"{k} extractors"
        issues.append(f"{pi.name(t)} from {what} isn't routed anywhere: the extracted product is lost.")
    return {"issues": issues, "idle_pins": idle_pins}


def colony_upkeep(pi: PIData, col: dict, plan_col: Optional[dict], now: float) -> dict:
    """Measured flows, projected stock and the next visit for one synced colony."""
    pins = col.get("pins", [])
    updated = _ts(col.get("last_update"))
    age_days = max(0.0, (now - updated) / 86400) if updated else 0.0

    # storage space and what's in it (launchpads, storage facilities, command center)
    cap, used, recognised = 0.0, 0.0, False
    stock = defaultdict(float)
    for p in pins:
        kind = R.storage_kind(p.get("type_id"))
        contents = p.get("contents", []) or []
        for c in contents:
            stock[c["type_id"]] += c["amount"]
        if kind:
            recognised = True
            cap += R.STORAGE_M3[kind]
        if kind or (not p.get("type_id") and not p.get("schematic_id") and not p.get("extractor_details")):
            used += sum(c["amount"] * pi.volume(c["type_id"]) for c in contents)

    # what the routed structures consume and make at full speed
    routing = route_check(pi, col)
    idle = frozenset(routing["idle_pins"]) if routing else frozenset()
    extractors = _extractors(pins, now, idle)
    schems = defaultdict(int)
    for p in pins:
        if p.get("schematic_id") in pi.schematics and p.get("pin_id") not in idle:
            schems[p["schematic_id"]] += 1
    need = defaultdict(float)
    for sid, n in schems.items():
        for t, q in pi.schematics[sid].per_hour_in().items():
            need[t] += q * 24 * n
    produced = defaultdict(float)
    for e in extractors:
        if e["product"]:
            produced[e["product"]] += e["per_day"]
    local = set(produced) | {pi.schematics[sid].output for sid in schems}
    imports = {t: q for t, q in need.items() if t not in local}
    stock_now = {t: max(0.0, stock.get(t, 0.0) - q * age_days) for t, q in imports.items()}

    # run the chain from low to high tier: local inputs are shared, imported ones need stock
    consumed = defaultdict(float)
    for sid in sorted(schems, key=lambda s: pi.tier(pi.schematics[s].output)):
        sch, n = pi.schematics[sid], schems[sid]
        f = 1.0
        for t in sch.inputs:
            if t in imports:
                f = min(f, 1.0 if stock_now[t] > 0 else 0.0)
            elif need[t]:
                f = min(f, produced[t] / need[t])
        f = max(0.0, min(1.0, f))
        for t, q in sch.per_hour_in().items():
            consumed[t] += q * 24 * n * f
        produced[sch.output] += sch.per_hour_out() * 24 * n * f
    exports = {t: produced[t] - consumed[t] for t in produced if produced[t] - consumed[t] > 0.01}

    in_m3, out_m3 = _m3(pi, imports), _m3(pi, exports)
    if updated:   # products kept arriving and inputs kept leaving since the snapshot
        used += out_m3 * age_days - sum(min(stock.get(t, 0.0), q * age_days) * pi.volume(t) for t, q in imports.items())
    used = max(0.0, min(cap, used) if recognised else used)
    flow = max(in_m3, out_m3)
    fill = cap / flow if recognised and flow > 0 else None
    programs = [e["program_days"] for e in extractors if e["program_days"]]
    rhythm = [x for x in (min(programs) if programs else None, fill) if x]
    every = min(rhythm) if rhythm else None

    events = []
    hours_left = [e["hours_left"] for e in extractors if e["hours_left"] is not None]
    if hours_left:
        events.append(("restart", min(hours_left)))
    days_left = {t: stock_now[t] / q for t, q in imports.items() if q}
    if days_left:
        events.append(("restock", min(days_left.values()) * 24))
    collect_h = max(0.0, cap - used) / out_m3 * 24 if recognised and out_m3 > 0 else None
    if collect_h is not None:
        events.append(("collect", collect_h))
    reason, next_h = min(events, key=lambda e: e[1]) if events else (None, None)

    issues = []
    if not recognised and (in_m3 or out_m3):
        issues.append("Launchpad or storage not recognised in the synced structures: capacity can't be checked.")
    elif recognised and cap <= R.STORAGE_M3["cc"] and (in_m3 or out_m3):
        issues.append("No launchpad or storage facility: only the command center's 500 m³ buffers this colony.")
    if fill is not None and fill < 1:
        issues.append(f"Space holds only {fill * 24:.0f} h of {'inputs' if in_m3 >= out_m3 else 'products'}: "
                      "add a launchpad or storage facility.")
    elif fill is not None and programs and not imports and fill < min(programs):
        issues.append(f"Fills in {fill:.1f} days, before the {min(programs):.1f}-day extractor program ends: "
                      "collect in between or add storage.")

    if routing:
        issues += routing["issues"]

    shortages = [{"item": pi.name(t), "type_id": t, "have": int(stock_now[t]), "need_per_day": round(q),
                  "days_left": round(days_left[t], 1)} for t, q in imports.items() if days_left.get(t, 0) < 2]

    # actual versus planned: the plan's product, or the colony's highest-tier export. A colony set up
    # for another product than the plan expects says so, rather than "0% of planned X".
    product = pi.by_name.get(plan_col["product"].lower()) if plan_col and plan_col.get("product") else None
    makes = colony_product(pi, col)
    expects = None
    if product is not None and makes is not None and makes != product and exports.get(product, 0.0) <= 0:
        expects, product = product, makes
    if product is None and exports:
        product = max(exports, key=lambda t: (pi.tier(t), exports[t]))
    planned = None
    if plan_col and product is not None and expects is None:
        planned = (plan_col.get("out_per_day") or {}).get(pi.name(product))
    actual = exports.get(product, 0.0) if product is not None else None
    pct = round(actual / planned * 100) if planned and actual is not None else None
    output = None if product is None else {
        "product": pi.name(product), "actual": round(actual or 0, 1), "planned": planned, "pct": pct,
        "expects": pi.name(expects) if expects is not None else None,
        "state": "soon" if expects is not None else (
            "ok" if pct is None or pct >= ON_PLAN * 100 else ("soon" if pct >= 50 else "expired"))}

    return {"capacity_m3": round(cap) if recognised else None, "used_m3": round(used, 1),
            "fill_pct": round(used / cap * 100) if recognised and cap else None,
            "in_m3_day": round(in_m3, 1), "out_m3_day": round(out_m3, 1),
            "fill_days": None if fill is None else round(fill, 1),
            "visit_every_days": None if every is None else round(every, 1),
            "restock": {pi.name(t): round(q * every) for t, q in imports.items()} if every else {},
            "next": reason, "next_hours": None if next_h is None else round(next_h, 1), "state": _due(next_h),
            "restart_hours": round(min(hours_left), 1) if hours_left else None,
            "restock_hours": round(min(days_left.values()) * 24, 1) if days_left else None,
            "collect_hours": None if collect_h is None else round(collect_h, 1),
            "program_days": round(min(programs), 1) if programs else None,
            "has_extractors": bool(extractors), "has_imports": bool(imports),
            "idle": bool(imports) and not exports,
            "routes_known": routing is not None,
            "output": output, "shortages": shortages, "issues": issues,
            "last_update": updated, "stale": bool(updated and age_days * 24 > COLONY_STALE_H)}


def colony_product(pi: PIData, col: dict) -> Optional[int]:
    """What a synced colony is set up to make: its highest-tier factory output, else what its
    extractors pull (the same rule the planner uses to decide keep or rebuild)."""
    from .optimizer import existing_product   # optimizer imports this module
    return existing_product(pi, col)


def _last_shipment(characters: List[dict]) -> Optional[float]:
    """When PI products last left for the market: a VOC courier or buyback with PI products, a PI
    sell order or a PI sale. Non-PI contracts (command centers, other goods) and starter stock
    coming in don't count."""
    locs = locations()
    seen = []
    for ch in characters:
        for c in ch.get("contracts", []):
            if pi_shipment(c, locs) or pi_buyback(c):
                seen.append(_ts(c.get("date_issued")))
        seen += [_ts(o.get("issued")) for o in ch.get("orders", []) if not o.get("is_buy_order")]
        seen += [_ts(t.get("date")) for t in (ch.get("wallet") or {}).get("sales", [])]
    seen = [t for t in seen if t]
    return max(seen) if seen else None


def _has_stock_to_ship(pi: PIData, characters: List[dict]) -> bool:
    """PI products sitting in station hangars (what a market shipment would take)."""
    return any(pi.tier(a["type_id"]) >= 1 and a.get("flag") != "Deliveries" and (a.get("qty") or 0) > 0
               for ch in characters for a in ch.get("assets", []))


def schedule(pi: PIData, s: Settings, characters: List[dict], plan: Optional[dict],
             area: Optional[dict] = None, now: Optional[float] = None) -> dict:
    """The Operate page's upkeep schedule across every character's colonies."""
    now = time.time() if now is None else now
    names = planet_names(area)
    planned = {(c.get("character_id"), c.get("planet_id")): c for c in (plan or {}).get("colonies", [])}
    rows, shortages, freshness = [], [], []
    for ch in characters:
        updates = []
        for col in ch.get("colonies", []):
            pid = col["planet_id"]
            pn = colony_name(names, col)
            u = colony_upkeep(pi, col, planned.get((ch.get("character_id"), pid)), now)
            u.update(character=ch["name"], planet=pn["name"], system=pn["system"])
            rows.append(u)
            shortages += [{**x, "character": ch["name"], "planet": pn["name"], "system": pn["system"]}
                          for x in u["shortages"]]
            if u["last_update"]:
                updates.append(u["last_update"])
        synced = ch.get("synced_at") or 0
        freshness.append({"character": ch["name"], "synced_at": synced,
                          "sync_stale": not synced or now - synced > SYNC_STALE_H * 3600,
                          "colony_update": min(updates) if updates else None,
                          "colony_stale": bool(updates and now - min(updates) > COLONY_STALE_H * 3600)})
    rows.sort(key=lambda r: (r["next_hours"] if r["next_hours"] is not None else 1e9))
    shortages.sort(key=lambda r: r["days_left"])

    def track(key: str, rows_in: List[dict], every_default: Optional[float] = None) -> dict:
        hrs = [r[key] for r in rows_in if r[key] is not None]
        # a factory standing idle (no inputs left) has no rhythm yet: it needs a restock, not a schedule
        every = [r["visit_every_days"] for r in rows_in if r["visit_every_days"] and not r.get("idle")]
        return {"colonies": len(rows_in), "next_hours": min(hrs) if hrs else None,
                "due": sum(1 for h in hrs if h < SOON_H), "every_days": min(every) if every else every_default}

    restarts = track("restart_hours", [r for r in rows if r["has_extractors"]])
    programs = [r["program_days"] for r in rows if r["program_days"]]
    restarts["every_days"] = min(programs) if programs else s.cycle_days
    restarts["expired"] = sum(1 for r in rows if r["restart_hours"] is not None and r["restart_hours"] <= 0)
    every_ship = float(((plan or {}).get("selling") or {}).get("every_days") or s.ship_every_days or 7)
    last = _last_shipment(characters)
    ship = {"every_days": every_ship, "last": last, "has_stock": _has_stock_to_ship(pi, characters),
            "next_days": None if last is None else round(every_ship - (now - last) / 86400, 1)}
    ship["due"] = ship["has_stock"] and (last is None or ship["next_days"] <= 0)

    plan_checks = []
    for c in (plan or {}).get("colonies", []):
        b = c.get("upkeep") or plan_buffer(pi, c, s.cycle_days)
        if b["issues"]:
            plan_checks.append({"character": c.get("character"), "planet": c.get("planet"),
                                "product": c.get("product"), "issues": b["issues"]})
    return {"colonies": rows, "shortages": shortages, "freshness": freshness, "plan_checks": plan_checks,
            "tracks": {"restart": restarts,
                       "restock": track("restock_hours", [r for r in rows if r["has_imports"]]),
                       "collect": track("collect_hours", [r for r in rows if r["out_m3_day"] > 0]),
                       "ship": ship},
            "stale": any(f["sync_stale"] or f["colony_stale"] for f in freshness)}
