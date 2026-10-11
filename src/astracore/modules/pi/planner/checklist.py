"""First-build checklist for a saved plan: what to buy, where to buy it, and what to build on each planet.

Three kinds of things go into a new colony, and the checklist keeps them apart:
  * bought on the market  - one command center per planet (of that planet's type), plus an optional
                            starter stock of factory inputs. AstraCore only produces a list to paste
                            into EVE's Multibuy window; it never buys anything or places market orders.
  * upgraded in game      - the command center level, paid from the wallet in the planetary interface
                            and capped by the Command Center Upgrades skill.
  * built in game         - the template's structures, also paid from the wallet when you submit.

Only DalShooth templates are referred to (never generated); "compatibility" says whether the template
the plan picked fits that planet type and the character's command center level.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..static_data import pi_rules as R
from ..static_data import voc
from ..static_data.sde_loader import PIData

HUBS = (("jita", "Jita 4-4"), ("amarr", "Amarr VIII"))
LOCAL_MARKET = "Delve regional market"
DEFAULT_SUPPLY_DAYS = 3.0


def buy_source(book: Optional[dict], local: bool) -> Optional[Tuple[str, float]]:
    """Where to buy an item and the lowest sell price there. With colonies in Delve a local seller
    saves hauling, so it wins whenever it lists the item; otherwise the cheaper trade hub."""
    book = book or {}
    if local and book.get("delve_sell"):
        return LOCAL_MARKET, float(book["delve_sell"])
    offers = [(float(book.get(f"{k}_sell") or 0), label) for k, label in HUBS]
    offers = [o for o in offers if o[0] > 0]
    if not offers:
        return None
    price, label = min(offers)
    return label, price


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
          planet_names: Optional[Dict[int, dict]] = None) -> Optional[dict]:
    """The checklist for the colonies a saved plan still needs (action new or rebuild).
    `plan` should already reflect what was built since it was saved (service.progress_against)."""
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

    # command centers: what to buy and where
    command_centers, cc_isk, estimated = [], 0.0, False
    for ptype, qty in sorted(cc_count.items()):
        tid = R.COMMAND_CENTER_TYPES.get(ptype)
        src = buy_source(books.get(tid) if tid else None, local)
        if src:
            where, unit = src
        else:
            where, unit, estimated = "Jita 4-4", float(R.COMMAND_CENTER_ISK_ESTIMATE), True
        name = f"{ptype} Command Center"
        command_centers.append({"name": name, "type_id": tid, "planet_type": ptype, "qty": qty,
                                "where": where, "unit_isk": round(unit), "isk": round(unit * qty),
                                "estimated": not src})
        cc_isk += unit * qty

    supplies, supply_isk, unpriced = [], 0.0, []
    for item, qty in sorted(supply_need.items()):
        src = buy_source(books.get(pi.by_name.get(item.lower())), local)
        unit = src[1] if src else 0.0
        if not src:
            unpriced.append(item)
        supplies.append({"item": item, "qty": int(qty), "where": src[0] if src else None,
                         "unit_isk": round(unit), "isk": round(unit * qty),
                         "for": sorted(set(supply_for[item]))})
        supply_isk += unit * qty

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
                  "total": round(cc_isk + upgrades_isk + structures_isk)},   # starter stock is optional
        "characters": sorted(per_char.values(), key=lambda e: e["name"]),
    }
