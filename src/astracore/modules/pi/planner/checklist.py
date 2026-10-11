"""First-build checklist for a saved plan: what to buy, where to buy it, and what to build on each planet.

Three kinds of things go into a new colony, and the checklist keeps them apart:
  * bought on the market  - one command center per planet (of that planet's type), plus an optional
                            starter stock of factory inputs. AstraCore only produces a list to paste
                            into EVE's Multibuy window; it never buys anything or places market orders.
                            Each item is bought where its landed cost (price + VOC courier to the drop-off)
                            is lowest; the courier fee is shown separately, and Delve offers name the seller.
  * upgraded in game      - the command center level, paid from the wallet in the planetary interface
                            and capped by the Command Center Upgrades skill.
  * built in game         - the template's structures, also paid from the wallet when you submit.

Only DalShooth templates are referred to (never generated); "compatibility" says whether the template
the plan picked fits that planet type and the character's command center level.
"""
from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Optional, Tuple

from . import compare, demand, selling
from ..static_data import pi_rules as R
from ..static_data import voc
from ..static_data.sde_loader import PIData

HUBS = (("jita", "Jita 4-4"), ("amarr", "Amarr VIII"))
LOCAL_MARKET = "Delve regional market"
DEFAULT_SUPPLY_DAYS = 3.0


def buy_source(book: Optional[dict], local: bool) -> Optional[Tuple[str, float]]:
    """Where to buy an item and the lowest sell price there, when hauling can't be priced. With
    colonies in Delve a local seller saves hauling, so it wins whenever it lists the item; otherwise
    the cheaper trade hub. (With a known courier route, `allocate` compares landed cost instead.)"""
    book = book or {}
    if local and book.get("delve_sell"):
        return LOCAL_MARKET, float(book["delve_sell"])
    offers = [(float(book.get(f"{k}_sell") or 0), label) for k, label in HUBS]
    offers = [o for o in offers if o[0] > 0]
    if not offers:
        return None
    price, label = min(offers)
    return label, price


# --------------------------------------------------------------------------- landed cost (price + hauling)
LABELS = {**dict(HUBS), "delve": LOCAL_MARKET}
# Your own trips: valued at the plan's "an hour of my time is worth" (goal default when unset) so a far
# Delve seller doesn't win only because AstraCore can't charge you for the flight.
MIN_PER_JUMP = 1.5                 # align, warp and gate in a hauler
DEFAULT_HOUR_ISK = 90e6            # the Balanced goal's default
DST_M3 = 60_000                    # a Deep Space Transport's cargo, for the fly-it-yourself hint
COURIER_HUBS = {"jita": voc.JITA, "amarr": voc.AMARR}


def hauling_routes(dropoff: str, area: Optional[dict], routes: Optional[List[dict]] = None) -> Dict[str, dict]:
    """How a purchase gets from each trade hub to the drop-off, per hub key:
      free      the drop-off is that hub;
      courier   a VOC courier from the hub's station to VOC's pickup nearest the drop-off. VOC's tariff
                lists Delve -> hub; when the reverse isn't listed, the same tariff is assumed (`approx`);
      unpriced  no courier route is known: you haul it yourself and AstraCore doesn't price that."""
    origin, origin_jumps = selling.courier_origin(dropoff, area) if dropoff else (None, 0)
    out: Dict[str, dict] = {}
    for key, label in HUBS:
        if dropoff and dropoff == selling.HUB_SYSTEMS[key]:
            out[key] = {"status": "free"}
            continue
        r = voc.route(COURIER_HUBS[key], origin, routes) if origin else None
        approx = False
        if origin and not r:
            r = voc.route(origin, COURIER_HUBS[key], routes)
            approx = bool(r)
        if not r or origin in selling.HUB_SYSTEMS.values():
            out[key] = {"status": "unpriced"}
            continue
        out[key] = {"status": "courier", "route": r, "approx": approx, "to": origin,
                    "carry_jumps": origin_jumps if origin != dropoff else 0}
    return out


def courier_cost(h: dict, m3: float, collateral: float) -> Tuple[float, int]:
    """VOC fee for one hub's purchases (split into several contracts above VOC's size limit)."""
    if m3 <= 0 and collateral <= 0:
        return 0.0, 0
    r = h["route"]
    n = max(1, math.ceil(m3 / r["max_m3"])) if r.get("max_m3") else 1
    return n * voc.courier_fee(r, m3 / n, collateral / n), n


def _variable(h: dict, m3: float, collateral: float) -> float:
    r = h["route"]
    return m3 * r["per_m3"] + collateral * r["collateral_pct"] / 100.0


def offers(book: Optional[dict], qty: float, local: bool, estimate: Optional[float] = None) -> Dict[str, dict]:
    """Price per unit to buy `qty` at each market, walking the sell depth when it's cached.
    `short` = units the cached price levels don't cover (priced at the last level)."""
    book = book or {}
    out: Dict[str, dict] = {}
    for m in ("jita", "amarr") + (("delve",) if local else ()):
        best = float(book.get(f"{m}_sell") or 0)
        if best <= 0:
            continue
        unit, short = best, 0
        levels = book.get(f"{m}_sell_depth")
        if levels and qty > 0:
            f = demand.fill(levels, qty)
            if f["filled"]:
                unit = (f["gross"] + f["short"] * (f["worst_price"] or best)) / qty
                short = int(f["short"])
        out[m] = {"unit": unit, "short": short, "estimated": False}
    if not out and estimate:
        out["jita"] = {"unit": float(estimate), "short": 0, "estimated": True}
    return out


def allocate(lines: List[dict], hauls: Dict[str, dict], base: Optional[Dict[str, Tuple[float, float]]] = None):
    """Pick a market per line for the lowest landed cost: goods + courier fees, minimum fee included.
    Every combination of courier hubs is tried (two hubs: four cases), so a handful of command centers
    doesn't pay a 10M minimum fee to save a few ISK each. `base` = (m3, collateral) per hub already in a
    contract (the command centers, when pricing the optional starter stock): only the extra fee counts.
    Returns ({line key: market or None}, {hub: contract})."""
    base = base or {}
    couriers = [k for k, h in hauls.items() if h["status"] == "courier"]
    best = None
    for n in range(len(couriers) + 1):
        for used in combinations(couriers, n):
            choice, ok = {}, True
            for ln in lines:
                cands = {}
                for m, o in ln["offers"].items():
                    status = "delve" if m == "delve" else hauls.get(m, {}).get("status", "unpriced")
                    if status == "courier":
                        if m not in used:
                            continue
                        cands[m] = o["unit"] + _variable(hauls[m], ln["vol"], o["unit"])
                    elif status == "unpriced" and "delve" in ln["offers"]:
                        continue          # a Delve seller saves a haul we can't price
                    elif status == "delve":
                        trip = ln.get("trip")
                        cands[m] = o["unit"] + (trip["isk"] / ln["qty"] if trip and ln["qty"] else 0.0)
                    else:
                        cands[m] = o["unit"]
                priced = any(m != "delve" and hauls.get(m, {}).get("status") in ("courier", "free")
                             for m in ln["offers"])
                outside = not ln.get("trip") and bool((ln.get("pickup") or {}).get("system"))
                if "delve" in cands and outside and priced:
                    del cands["delve"]    # a seller known to be outside your area doesn't beat a priced option
                if not cands and ln["offers"]:
                    ok = False
                    break
                choice[ln["key"]] = min(cands, key=lambda m: (cands[m], m != "delve")) if cands else None
            if not ok:
                continue
            contracts = _contracts(lines, choice, hauls, base)
            total = sum(ln["qty"] * ln["offers"][choice[ln["key"]]]["unit"] for ln in lines if choice[ln["key"]])
            total += sum((ln.get("trip") or {}).get("isk", 0) for ln in lines if choice[ln["key"]] == "delve")
            total += sum(c["fee"] for c in contracts.values())
            if best is None or total < best[0] - 0.5:
                best = (total, choice, contracts)
    return (best[1], best[2]) if best else ({ln["key"]: None for ln in lines}, {})


def _contracts(lines: List[dict], choice: Dict[str, Optional[str]], hauls: Dict[str, dict],
               base: Dict[str, Tuple[float, float]]) -> Dict[str, dict]:
    agg: Dict[str, dict] = {}
    for ln in lines:
        m = choice.get(ln["key"])
        if m in hauls and hauls[m]["status"] == "courier":
            a = agg.setdefault(m, {"m3": 0.0, "collateral": 0.0, "lines": []})
            a["m3"] += ln["qty"] * ln["vol"]
            a["collateral"] += ln["qty"] * ln["offers"][m]["unit"]
            a["lines"].append(ln["key"])
    for m, a in agg.items():
        b_m3, b_coll = base.get(m, (0.0, 0.0))
        fee, n = courier_cost(hauls[m], b_m3 + a["m3"], b_coll + a["collateral"])
        a["fee"] = fee - courier_cost(hauls[m], b_m3, b_coll)[0]
        a["contracts"] = n
        a["shared"] = bool(b_m3 or b_coll)
    return agg


def _pickup(book: Optional[dict], area: Optional[dict], dropoff: str, qty: float, dist: dict) -> dict:
    """Where the cheapest Delve seller is: NPC station by name, a player structure by its system,
    and jumps from the drop-off when that system is in your area."""
    at = (book or {}).get("delve_sell_at") or {}
    if not at:
        return {"text": "location not cached yet: refresh prices", "jumps": None}
    sid = at.get("system_id")
    system = at.get("system") or ((area or {}).get("systems", {}).get(str(sid)) or {}).get("name")
    if "start" not in dist and area and dropoff:
        from ..intel import area as area_mod
        start = area_mod.system_by_name(area, dropoff)
        dist["start"] = area_mod.jumps_from(area, start["system_id"]) if start else {}
    jumps = dist.get("start", {}).get(sid)
    place = at.get("station") or (f"a player structure in {system}" if at.get("structure") and system
                                  else system or "an unnamed location")
    text = place
    if jumps is not None:
        text += f" ({jumps} jump{'s' if jumps != 1 else ''} from {dropoff})" if jumps else f" (in {dropoff})"
    elif system:
        text += " (outside your area: check the route)"
    units = int(at.get("units") or 0)
    partial = bool(units and units < qty)
    if partial:
        text += f"; only {units:,} at that price there, the rest is elsewhere in Delve"
    return {"text": text, "station": at.get("station"), "system": system, "jumps": jumps,
            "units": units, "partial": partial}


def own_trip(jumps: Optional[int], m3: float, hour_isk: float) -> Optional[dict]:
    """Your own round trip to a seller `jumps` away and back, in minutes and in ISK at your hour value."""
    if jumps is None:
        return None
    minutes = 2 * jumps * MIN_PER_JUMP + m3 / 60_000 * compare.MIN_PER_60K_M3
    return {"jumps": jumps, "minutes": round(minutes, 1), "isk": round(minutes / 60 * max(0.0, hour_isk))}


def purchases(pi: PIData, cc_count: Dict[str, int], supply_need: Dict[str, float],
              books: Dict[int, dict], local: bool, dropoff: str, area: Optional[dict],
              routes: Optional[List[dict]] = None, hour_isk: float = DEFAULT_HOUR_ISK) -> dict:
    """What to buy where, at the lowest landed cost. The command centers are priced first; the
    optional starter stock then only adds what it costs on top of the same courier contracts.
    A Delve seller is compared including your own trip there, valued at `hour_isk`."""
    hauls = hauling_routes(dropoff, area, routes)
    dist: dict = {}
    cc_lines = []
    for ptype, qty in sorted(cc_count.items()):
        tid = R.COMMAND_CENTER_TYPES.get(ptype)
        cc_lines.append({"key": f"{ptype} Command Center", "qty": qty, "vol": R.COMMAND_CENTER_M3,
                         "type_id": tid, "planet_type": ptype, "book": books.get(tid) if tid else None,
                         "offers": offers(books.get(tid) if tid else None, qty, local,
                                          estimate=R.COMMAND_CENTER_ISK_ESTIMATE)})
    st_lines = []
    for item, qty in sorted(supply_need.items()):
        tid = pi.by_name.get(item.lower())
        st_lines.append({"key": item, "qty": int(qty), "vol": pi.volume(tid) if tid else 0.0, "type_id": tid,
                         "book": books.get(tid), "offers": offers(books.get(tid), qty, local)})
    for ln in cc_lines + st_lines:
        if "delve" in ln["offers"]:
            ln["pickup"] = _pickup(ln["book"], area, dropoff, ln["qty"], dist)
            ln["trip"] = own_trip(ln["pickup"].get("jumps"), ln["qty"] * ln["vol"], hour_isk)
    cc_choice, cc_contracts = allocate(cc_lines, hauls)
    base = {m: (c["m3"], c["collateral"]) for m, c in cc_contracts.items()}
    st_choice, st_contracts = allocate(st_lines, hauls, base)

    def rows(lines, choice, contracts):
        out = []
        for ln in lines:
            m = choice.get(ln["key"])
            o = ln["offers"].get(m) if m else None
            unit = o["unit"] if o else 0.0
            isk = unit * ln["qty"]
            haul, haul_note = 0.0, None
            h = hauls.get(m) if m else None
            if h and h["status"] == "courier":
                c = contracts[m]
                # the contract's fee, shared by each line's part of the variable cost
                weights = {x["key"]: _variable(h, x["qty"] * x["vol"], x["qty"] * x["offers"][m]["unit"])
                           for x in lines if x["key"] in c["lines"]}
                haul = c["fee"] * weights[ln["key"]] / (sum(weights.values()) or 1.0)
                haul_note = "courier" + (", tariff assumed from the reverse route" if h["approx"] else "")
            elif h and h["status"] == "unpriced":
                haul_note = "haul it yourself (not priced)"
            elif h and h["status"] == "free":
                haul_note = "no hauling: your drop-off is here"
            pickup = ln.get("pickup") if m == "delve" else None
            trip = ln.get("trip") if m == "delve" else None
            if m == "delve":
                haul_note = (f"your trip: {trip['jumps']} jump{'s' if trip['jumps'] != 1 else ''} each way, "
                             f"≈ {trip['minutes']:g} min" if trip and trip["jumps"]
                             else "pick it up yourself in Delve")
            out.append({"key": ln["key"], "qty": ln["qty"], "where": LABELS[m] if m else None, "market": m,
                        "unit_isk": round(unit), "isk": round(isk), "haul_isk": round(haul),
                        "landed_isk": round(isk + haul), "haul_note": haul_note, "pickup": pickup, "trip": trip,
                        "estimated": bool(o and o["estimated"]), "short": o["short"] if o else 0,
                        "m3": ln["qty"] * ln["vol"]})
        return out

    def summary(contracts, section):
        out = []
        for m, c in sorted(contracts.items()):
            h = hauls[m]
            r = h["route"]
            out.append({"section": section, "from": LABELS[m], "to": h["to"], "m3": round(c["m3"]),
                        "collateral": round(c["collateral"]), "fee": round(c["fee"]), "contracts": c["contracts"],
                        "shared": c["shared"], "approx": h["approx"], "carry_jumps": h["carry_jumps"],
                        # a minimum fee above the goods' value: worth knowing you could fly it yourself
                        "self_haul_trips": math.ceil(c["m3"] / DST_M3) if c["fee"] > c["collateral"] else 0,
                        "tariff": f"max({r['min_fee']:,.0f}, m³ × {r['per_m3']:,.0f} + {r['collateral_pct']:g}% "
                                  f"of collateral)", "items": c["lines"]})
        return out

    return {"hauls": hauls, "cc": rows(cc_lines, cc_choice, cc_contracts),
            "stock": rows(st_lines, st_choice, st_contracts),
            "contracts": summary(cc_contracts, "command_centers") + summary(st_contracts, "starter_stock")}


def _compat(col: dict, tpl: Optional[dict], skill: int) -> dict:
    """Does the plan's DalShooth template fit this planet and this character?"""
    min_ccu = int(col.get("min_ccu") or 0)
    tpl_lvl = int((tpl or {}).get("ccu_level") or 0)
    target = max(min_ccu, min(tpl_lvl, skill))   # the level the template was saved at, if trained
    tpl_type = R.PLANET_TYPES.get((tpl or {}).get("planet_type_id"))
    if tpl is None:
        return {"status": "bad", "target": min_ccu, "label": "Template missing",
                "text": "This template is no longer in DalShooth/EVE_PI_Templates. Make a new plan."}
    if col.get("tier") == 4 and col.get("planet_type") not in R.HIGH_TECH_PLANETS:
        return {"status": "bad", "target": target, "label": "Wrong planet type",
                "text": "High-Tech Production Plants only exist on Barren and Temperate planets."}
    if skill < min_ccu:
        return {"status": "bad", "target": min_ccu, "label": "Train first",
                "text": f"Needs Command Center Upgrades {min_ccu}; {col['character']} has {skill}."}
    notes = []
    if tpl_type and col.get("planet_type") and tpl_type != col["planet_type"]:
        notes.append(f"Saved on a {tpl_type} planet: apply it here and check that every structure lands.")
    if tpl_lvl > skill:
        notes.append(f"Saved with a level {tpl_lvl} command center; the structures fit level {min_ccu} on paper.")
    if notes:
        return {"status": "warn", "target": target, "label": "Check in game", "text": " ".join(notes)}
    return {"status": "ok", "target": target, "label": "Fits",
            "text": f"Fits a {col.get('planet_type') or 'this'} planet at command center level {target}."}


def _structures(layout: dict) -> List[dict]:
    rows = []
    for key, name in R.STRUCTURE_NAMES.items():
        n = int(layout.get(key) or 0)
        if n:
            rows.append({"name": name, "count": n, "isk": n * R.STRUCTURE_ISK[key]})
    return rows


def _steps(col: dict, compat: dict, upgrade: dict, structures: List[dict], supplies: Dict[str, int],
           cycle_days: float) -> List[str]:
    steps = []
    if col["action"] == "rebuild":
        steps.append(f"Empty the launchpad and storage on {col['planet']}, then decommission the old structures "
                     f"(keep the command center).")
    else:
        steps.append(f"Fly to {col['system']} with a {col['planet_type']} Command Center in your cargo and "
                     f"place it on {col['planet']}.")
    if upgrade["isk"]:
        steps.append(f"Upgrade the command center from level {upgrade['from']} to {upgrade['to']} in the "
                     f"planetary interface.")
    built = ", ".join(f"{s['count']}× {s['name']}" for s in structures)
    steps.append(f"Apply the template “{col['template']}”" + (f" ({built})" if built else "")
                 + " and check that every structure lands before you submit.")
    if col["kind"] == "miner":
        what = ", ".join(col.get("p0") or []) or "the resource"
        steps.append(f"Put the extractor heads on the best {what} hotspot and start a "
                     f"{cycle_days:g}-day program.")
    else:
        steps.append(f"Check that every factory is set to {col['product']} and routed from the launchpad.")
        if supplies:
            items = ", ".join(f"{q:,} {k}" for k, q in sorted(supplies.items()))
            steps.append(f"Import the starter stock ({items}) through the customs office to the launchpad.")
    steps.append("Submit, then refresh AstraCore so Operate can see the colony.")
    return steps


def build(pi: PIData, plan: dict, characters: List[dict], books: Dict[int, dict], templates: List[dict],
          settings: Optional[dict] = None, local: bool = False,
          planet_names: Optional[Dict[int, dict]] = None, area: Optional[dict] = None,
          voc_routes: Optional[List[dict]] = None) -> Optional[dict]:
    """The checklist for the colonies a saved plan still needs (action new or rebuild).
    `plan` should already reflect what was built since it was saved (service.progress_against).
    `area` (systems and gates) finds VOC's pickup and the jumps to a Delve seller; `voc_routes` = VOC tariff."""
    if not plan or "colonies" not in plan:
        return None
    settings = settings or {}
    cycle_days = float(settings.get("cycle_days") or DEFAULT_SUPPLY_DAYS)
    tpl_by_file = {t.get("file"): t for t in templates or []}
    chars = {c["character_id"]: c for c in characters}
    names = planet_names or {}

    cc_count: Dict[str, int] = defaultdict(int)
    supply_need: Dict[str, float] = defaultdict(float)
    supply_for: Dict[str, List[str]] = defaultdict(list)
    per_char: Dict[int, dict] = {}
    upgrades_isk = structures_isk = 0
    blocked = warned = 0

    todo = [c for c in plan["colonies"] if c.get("action") in ("new", "rebuild")]
    for col in todo:
        ch = chars.get(col["character_id"], {})
        skill = int(ch.get("ccu_level", 0) or 0)
        tpl = tpl_by_file.get(col.get("template_file"))
        compat = _compat(col, tpl, skill)
        blocked += compat["status"] == "bad"
        warned += compat["status"] == "warn"
        current = 0
        if col["action"] == "rebuild":
            current = next((int(x.get("upgrade_level") or 0) for x in ch.get("colonies", [])
                            if x.get("planet_id") == col["planet_id"]), 0)
        else:
            cc_count[col["planet_type"]] += 1
        upgrade = {"from": current, "to": max(current, compat["target"]),
                   "isk": R.upgrade_isk(current, compat["target"])}
        structures = _structures(col.get("layout") or {})
        supplies = {k: int(math.ceil(v * cycle_days)) for k, v in (col.get("in_per_day") or {}).items() if v > 0}
        for k, q in supplies.items():
            supply_need[k] += q
            supply_for[k].append(col["planet"])
        build_isk = upgrade["isk"] + sum(s["isk"] for s in structures)
        upgrades_isk += upgrade["isk"]
        structures_isk += sum(s["isk"] for s in structures)
        entry = per_char.setdefault(col["character_id"], {
            "character_id": col["character_id"], "name": col["character"], "ccu_skill": skill,
            "planets": [], "removals": [], "command_centers": defaultdict(int), "isk": 0})
        if col["action"] == "new":
            entry["command_centers"][col["planet_type"]] += 1
        entry["isk"] += build_isk
        entry["planets"].append({
            "planet": col["planet"], "planet_type": col["planet_type"], "system": col["system"],
            "action": col["action"], "kind": col["kind"], "product": col["product"], "tier": col.get("tier"),
            "template": col["template"], "template_url": col.get("template_url"),
            "compat": compat, "upgrade": upgrade, "structures": structures, "supplies": supplies,
            "build_isk": build_isk,
            "steps": _steps(col, compat, upgrade, structures, supplies, cycle_days)})

    if not todo:
        return {"todo": 0}

    # visit planets in each character's pickup-route order, systems first
    routes = {c["character_id"]: (c.get("route") or {}).get("order") or [] for c in plan.get("characters", [])}
    for cid, entry in per_char.items():
        order = {s: i for i, s in enumerate(routes.get(cid, []))}
        entry["planets"].sort(key=lambda p: (order.get(p["system"], len(order)), p["system"], p["planet"]))
        entry["command_centers"] = dict(sorted(entry["command_centers"].items()))
    for r in plan.get("removals", []):
        cid = next((c for c, e in per_char.items() if e["name"] == r.get("character")), None)
        if cid is not None:
            pn = names.get(r.get("planet_id"), {})
            per_char[cid]["removals"].append({"planet": pn.get("name") or f"planet {r.get('planet_id')}",
                                              "system": pn.get("system", ""), "current": r.get("current")})

    # what to buy and where: lowest landed cost (price + courier to the drop-off)
    dropoff = plan.get("hub") or ""
    hour = float(settings.get("hour_isk", -1) if settings.get("hour_isk") is not None else -1)
    buy = purchases(pi, cc_count, supply_need, books, local, dropoff, area, voc_routes,
                    hour if hour >= 0 else DEFAULT_HOUR_ISK)
    command_centers, estimated = [], False
    for r in buy["cc"]:
        ptype = r["key"][:-len(" Command Center")]
        estimated |= r["estimated"]
        command_centers.append({"name": r["key"], "type_id": R.COMMAND_CENTER_TYPES.get(ptype), "planet_type": ptype,
                                **{k: v for k, v in r.items() if k != "key"}})
    supplies, unpriced = [], []
    for r in buy["stock"]:
        if not r["where"]:
            unpriced.append(r["key"])
        supplies.append({"item": r["key"], **{k: v for k, v in r.items() if k != "key"},
                         "for": sorted(set(supply_for[r["key"]]))})
    cc_isk = sum(c["isk"] for c in command_centers)
    supply_isk = sum(x["isk"] for x in supplies)
    cc_haul = sum(c["fee"] for c in buy["contracts"] if c["section"] == "command_centers")
    st_haul = sum(c["fee"] for c in buy["contracts"] if c["section"] == "starter_stock")
    used = {x["market"] for x in command_centers + supplies if x["market"]}
    self_haul = sorted(LABELS[m] for m in used if buy["hauls"].get(m, {}).get("status") == "unpriced")

    cc_qty = sum(cc_count.values())
    return {
        "todo": len(todo), "new": sum(1 for c in todo if c["action"] == "new"),
        "rebuild": sum(1 for c in todo if c["action"] == "rebuild"),
        "blocked": blocked, "warned": warned, "local": local, "cycle_days": cycle_days,
        "command_centers": command_centers, "cc_qty": cc_qty, "cc_m3": cc_qty * R.COMMAND_CENTER_M3,
        "cc_local": any(c["where"] == LOCAL_MARKET for c in command_centers),
        "multibuy": voc.paste_list({c["name"]: c["qty"] for c in command_centers}),
        "supplies": supplies, "supply_days": cycle_days,
        "supplies_multibuy": voc.paste_list({s["item"]: s["qty"] for s in supplies}),
        "unpriced": unpriced,
        "costs": {"command_centers": round(cc_isk), "upgrades": upgrades_isk, "structures": structures_isk,
                  "supplies": round(supply_isk), "estimated_cc": estimated,
                  "hauling": round(cc_haul), "supplies_hauling": round(st_haul),
                  "total": round(cc_isk + cc_haul + upgrades_isk + structures_isk)},   # starter stock is optional
        "hauling": {"contracts": buy["contracts"], "self_haul": self_haul, "dropoff": dropoff,
                    "approx": any(c["approx"] for c in buy["contracts"])},
        "characters": sorted(per_char.values(), key=lambda e: e["name"]),
    }
