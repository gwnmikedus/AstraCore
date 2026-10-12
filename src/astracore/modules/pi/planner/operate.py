"""After setup: what to do now, where your products are, and the ISK that came in.

Pipeline:  on planets → picked up (hangar) → sold (buyback / courier → market) → ISK in wallet
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..settings import Settings
from astracore.esi.character import locations, unknown_location
from ..static_data import voc
from ..static_data.sde_loader import PIData
from . import selling, skills

FMT = "%Y-%m-%dT%H:%M:%SZ"


def _ts(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.strptime(s, FMT).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _hours_left(s: Optional[str]) -> Optional[float]:
    t = _ts(s)
    return None if t is None else (t - time.time()) / 3600


def planet_names(area: Optional[dict]) -> Dict[int, dict]:
    out = {}
    if area:
        for sys in area["systems"].values():
            for p in sys["planets"]:
                out[p["planet_id"]] = {"name": p["name"], "system": sys["name"], "type": p["type"]}
    return out


def colony_name(names: Dict[int, dict], col: dict) -> dict:
    """Name, system and type of a colony's planet: from the area when it's inside it, otherwise the
    names stored at the last ESI refresh, and only as a last resort "Planet <id>"."""
    pid = col["planet_id"]
    if pid in names:
        return names[pid]
    return {"name": col.get("planet_name") or f"Planet {pid}", "system": col.get("system_name") or "",
            "type": col.get("planet_type", "")}


ACTIVE = ("outstanding", "in_progress")
DONE = ("finished", "finished_issuer", "finished_contractor")


def _recent_days(ts: Optional[str], days: int) -> bool:
    t = _ts(ts)
    return t is not None and t > time.time() - days * 86400


def colonies_status(pi: PIData, characters: List[dict], area: Optional[dict]) -> dict:
    names = planet_names(area)
    extractors, pickups = [], []
    for ch in characters:
        for col in ch.get("colonies", []):
            pn = colony_name(names, col)
            pins = col.get("pins", [])
            schem_inputs = defaultdict(float)   # type -> units/day consumed on this planet (not a pickup)
            for p in pins:
                sid = p.get("schematic_id")
                if sid and sid in pi.schematics:
                    for t, q in pi.schematics[sid].per_hour_in().items():
                        schem_inputs[t] += q * 24
            stock = defaultdict(float)
            for p in pins:
                ex = p.get("extractor_details")
                if ex:
                    h = _hours_left(p.get("expiry_time"))
                    extractors.append({
                        "character": ch["name"], "planet": pn["name"], "system": pn["system"],
                        "product": pi.name(ex.get("product_type_id")) if ex.get("product_type_id") else "?",
                        "heads": len(ex.get("heads", [])), "hours_left": None if h is None else round(h, 1),
                        "state": "expired" if h is not None and h <= 0 else ("soon" if h is not None and h < 24 else "ok"),
                    })
                for c in p.get("contents", []) or []:
                    stock[c["type_id"]] += c["amount"]
            ready = {t: q for t, q in stock.items() if pi.tier(t) >= 1 and t not in schem_inputs and q >= 1}
            if ready:
                pickups.append({"character": ch["name"], "planet": pn["name"], "system": pn["system"],
                                "items": {pi.name(t): int(q) for t, q in ready.items()},
                                "m3": round(sum(q * pi.volume(t) for t, q in ready.items()), 1)})
    extractors.sort(key=lambda e: (e["hours_left"] if e["hours_left"] is not None else 1e9))
    # factory restocks come from upkeep.schedule (projected stock, routed factories only)
    return {"extractors": extractors, "pickups": pickups}


STRUCTURE_ID_MIN = 1_000_000_000_000   # player structures; lower ids are NPC stations and other locations
NO_ACCESS_NOTE = ("You can't dock in this structure any more, so nothing here can be hauled or sold. "
                  "Regain docking access, or use asset safety from the Assets window to move it to a station.")


def hangar_stock(pi: PIData, s: Settings, books: Dict[int, dict], characters: List[dict],
                 area: Optional[dict] = None) -> List[dict]:
    """PI products sitting in stations/structures, grouped by character + location,
    each with the best way to sell it from there."""
    locs = locations()
    by_name = {ch["name"]: ch for ch in characters}
    groups: Dict[tuple, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    private_locations = {}
    for ch in characters:
        for a in ch.get("assets", []):
            if pi.tier(a["type_id"]) < 1 or a.get("flag") in ("Deliveries",):
                continue
            groups[(ch["name"], a["location_id"])][a["type_id"]] += a["qty"]
            if a.get("location"):
                private_locations[(ch["name"], a["location_id"])] = a["location"]
    seller = skills.best_seller(characters) if s.taxes_from_skills else None
    out = []
    for (who, lid), stock in groups.items():
        loc = private_locations.get((who, lid)) or locs.get(lid) or unknown_location(lid)
        here = loc.get("system", "")
        no_access = bool(loc.get("unknown")) and lid > STRUCTURE_ID_MIN
        if no_access:
            # A structure you can't dock in: nothing can be hauled, contracted or sold from it.
            plan = {"batches": [], "net_per_cycle": 0, "unsellable": [], "no_access": True,
                    "note": NO_ACCESS_NOTE}
        else:
            origin, jumps = selling.courier_origin(here, area)
            plan = selling.sell_plan(pi, skills.for_character(s, by_name[who]), books, here,
                                     {t: q for t, q in stock.items()}, per_day=False,
                                     local=selling.in_delve(here, area), origin=origin or here,
                                     origin_jumps=jumps, self_haul=True)
        own = skills.character_rates(by_name[who]) if by_name[who].get("skills") else None
        market = sum(b["net"] for b in plan["batches"] if b["channel"] != "buyback" and not b.get("hold"))
        if seller and own and seller["name"] != who and own["sales_tax_pct"] > seller["sales_tax_pct"] and market > 0:
            gain = market / (1 - own["sales_tax_pct"] / 100) * (own["sales_tax_pct"] - seller["sales_tax_pct"]) / 100
            plan["seller_gain"] = round(gain)
            plan["own_tax_pct"] = own["sales_tax_pct"]
        out.append({"character": who, "location": loc["name"], "system": here, "location_id": lid,
                    "unknown_location": bool(loc.get("unknown")), "no_access": no_access,
                    "items": {pi.name(t): int(q) for t, q in stock.items()},
                    "m3": round(sum(q * pi.volume(t) for t, q in stock.items()), 1),
                    "jita_value": round(sum(q * books.get(t, {}).get("jita_buy", 0) for t, q in stock.items())),
                    "plan": plan})
    out.sort(key=lambda g: -g["jita_value"])
    for g in out:
        g["seller"] = seller
    return out


# Rough cargo capacities for the "can you actually haul this?" check (fitted, typical).
HAUL_SHIPS = (("Deep Space Transport", 60_000), ("Freighter (high-sec only)", 900_000))
BIG_STACK_M3 = 30_000


def consolidate(stock: List[dict], area: Optional[dict] = None) -> Optional[dict]:
    """One "Consolidate & sell" summary for everything in hangars: totals, the best seller once,
    each kind of advice once (with where it applies), and a size reality check for stacks you'd
    have to haul yourself."""
    if not stock:
        return None
    seller = next((g.get("seller") for g in stock if g.get("seller")), None)
    total_m3 = sum(g["m3"] for g in stock)
    total_value = sum(g["jita_value"] for g in stock)
    net = sum(b["net"] for g in stock for b in g["plan"]["batches"] if not b.get("hold"))
    gain = sum(g["plan"].get("seller_gain", 0) for g in stock)
    handover = sorted({g["character"] for g in stock if g["plan"].get("seller_gain")})
    advice: Dict[str, dict] = {}
    for g in stock:
        where = g["location"] + (f" ({g['system']})" if g["system"] else "")
        if g["plan"].get("no_access"):
            a = advice.setdefault("no_access", {"label": "Regain access or use asset safety", "channel": "no_access",
                                                "m3": 0.0, "net": 0.0, "where": [], "hold": True,
                                                "note": g["plan"].get("note")})
            a["m3"] += g["m3"]
            if where not in a["where"]:
                a["where"].append(where)
            continue
        for b in g["plan"]["batches"]:
            key = b["channel"]
            a = advice.setdefault(key, {"label": b["label"], "channel": key, "m3": 0.0, "net": 0.0, "where": [],
                                        "hold": False, "note": None})
            a["m3"] += b["m3"]
            a["net"] += 0 if b.get("hold") else b["net"]
            a["hold"] = a["hold"] or bool(b.get("hold"))
            if where not in a["where"]:
                a["where"].append(where)
            if key.endswith("_self") and b.get("note") and b["note"] not in (a["note"] or ""):
                a["note"] = f"{a['note']} {b['note']}" if a["note"] else b["note"]
    unsellable = sorted({x for g in stock for x in g["plan"].get("unsellable", [])})
    reality = []
    for g in stock:   # one size check per hangar, however many hubs its stock goes to
        hauled = [b for b in g["plan"]["batches"] if b["channel"].endswith("_self")]
        if sum(b["m3"] for b in hauled) >= BIG_STACK_M3:
            reality.append(_reality(g, hauled, area))
    self_haul = any(b["channel"].endswith("_self") and not b.get("hold") for g in stock for b in g["plan"]["batches"])
    return {"total_m3": round(total_m3, 1), "total_value": round(total_value), "net": round(net),
            "seller": seller, "seller_gain": round(gain), "handover": handover, "self_haul": self_haul,
            "advice": sorted(advice.values(), key=lambda a: -a["net"]), "unsellable": unsellable,
            "reality": reality, "locations": len(stock)}


def _reality(g: dict, batches: List[dict], area: Optional[dict]) -> dict:
    """What hauling a hangar's stack yourself really means, next to letting VOC take it from their nearest
    pickup. `batches` are that hangar's self-haul batches (normally one hub, see selling._one_hub)."""
    import math
    m3 = sum(b["m3"] for b in batches)
    value = sum(b["jita_value"] for b in batches)
    dests = []
    for b in sorted(batches, key=lambda b: -b["m3"]):
        d = "Jita" if b["channel"].startswith("jita") else "Amarr"
        if d not in dests:
            dests.append(d)
    trips = []
    for name, cap in HAUL_SHIPS:   # every hub is its own run
        n = sum(max(1, math.ceil(sum(b["m3"] for b in batches if b["channel"].startswith(d.lower())) / cap))
                for d in dests)
        trips.append({"ship": name, "trips": n, "capacity": cap})
    out = {"where": g["location"], "system": g["system"], "m3": m3, "value": value, "dest": " and ".join(dests),
           "trips": trips, "voc": None}
    origin, jumps = selling.courier_origin(g["system"], area)
    if origin:
        fee, contracts = 0.0, 0
        for b in batches:
            r = voc.route(origin, voc.JITA if b["channel"].startswith("jita") else voc.AMARR)
            if not r:
                return out
            fee += voc.courier_fee(r, b["m3"], b["jita_value"])
            contracts += max(1, math.ceil(b["m3"] / r["max_m3"]))
        out["voc"] = {"origin": origin, "jumps": jumps, "fee": round(fee), "contracts": contracts}
    return out


# Trade hub systems: a PI courier from one of these brings starter stock in, it isn't a shipment out.
TRADE_HUBS = ("Jita", "Perimeter", "Amarr", "Dodixie", "Rens", "Hek")


def pi_shipment(c: dict, locs: Dict[int, dict]) -> bool:
    """A VOC courier that takes PI products to market.

    Only contracts the ESI sync flagged `pi` (they carry PI products) count: a courier with command
    centers or other goods isn't PI. A PI courier that starts at a trade hub brings starter stock
    in; that is a purchase, like the goods themselves (which Operate doesn't book either), so it's
    neither a market shipment nor a selling cost. When the start location isn't known it counts."""
    if c.get("type") != "courier" or not c.get("voc") or not c.get("pi"):
        return False
    return locs.get(c.get("start_location_id"), {}).get("system") not in TRADE_HUBS


def pi_buyback(c: dict) -> bool:
    """A VOC buyback (item exchange) with PI products in it."""
    return c.get("type") == "item_exchange" and bool(c.get("voc")) and bool(c.get("pi"))


def pipeline(pi: PIData, books: Dict[int, dict], characters: List[dict]) -> dict:
    locs = locations()
    courier, buyback, other, orders, done = [], [], [], [], []
    for ch in characters:
        for c in ch.get("contracts", []):
            start_loc = c.get("start_location") or locs.get(c.get("start_location_id"), {})
            end_loc = c.get("end_location") or locs.get(c.get("end_location_id"), {})
            start = start_loc.get("name", "")
            end = end_loc.get("name", "")
            row = {"character": ch["name"], "status": c["status"], "issued": c.get("date_issued"),
                   "completed": c.get("date_completed"), "from": start, "to": end,
                   "reward": c.get("reward") or 0, "collateral": c.get("collateral") or 0,
                   "price": c.get("price") or 0, "volume": c.get("volume") or 0,
                   "items": {pi.name(i["type_id"]): i["qty"] for i in c.get("items", []) if i["type_id"] in pi.items},
                   "other_items": sum(1 for i in c.get("items", []) if i["type_id"] not in pi.items)}
            active = c["status"] in ACTIVE
            if not active and not (c["status"] in DONE and _recent_days(c.get("date_completed") or
                                                                       c.get("date_accepted") or c.get("date_issued"), 7)):
                continue  # expired, deleted, rejected or older than a week
            if c["type"] == "courier" and c.get("voc"):
                if not pi_shipment(c, locs):
                    continue  # command centers, starter stock coming in or other goods: not a PI shipment
                (courier if active else done).append({**row, "kind": "VOC courier"})
            elif c["type"] == "item_exchange" and c.get("voc"):
                if not row["items"]:
                    continue  # a VOC contract without PI products in it
                (buyback if active else done).append({**row, "kind": "VOC buyback"})
            elif c.get("pi") and active:
                other.append(row)
        for o in ch.get("orders", []):
            if o.get("is_buy_order"):
                continue
            best = books.get(o["type_id"], {})
            loc = o.get("location") or locs.get(o["location_id"]) or unknown_location(o["location_id"])
            hub = "jita" if loc.get("system") == "Jita" else ("amarr" if loc.get("system") == "Amarr" else None)
            best_sell = best.get(f"{hub}_sell") if hub else None
            orders.append({"character": ch["name"], "item": pi.name(o["type_id"]), "price": o["price"],
                           "remaining": o["volume_remain"], "total": o["volume_total"],
                           "value": o["price"] * o["volume_remain"], "location": loc.get("name", ""),
                           "undercut": bool(best_sell and best_sell < o["price"] - 0.01),
                           "best_sell": best_sell, "issued": o.get("issued")})
    order = {"outstanding": 0, "in_progress": 1, "finished": 2}
    for lst in (courier, buyback, other, done):
        lst.sort(key=lambda r: (order.get(r["status"], 3), -(_ts(r["issued"]) or 0)))
    return {"courier": courier, "buyback": buyback, "other": other, "orders": orders, "done": done,
            "in_transit_value": round(sum(r["collateral"] for r in courier if r["status"] in ("outstanding", "in_progress"))),
            "awaiting_buyback": round(sum(r["price"] for r in buyback if r["status"] == "outstanding")),
            "listed_value": round(sum(o["value"] for o in orders))}


def earnings(pi: PIData, characters: List[dict], days: int = 7) -> dict:
    """ISK that came in from PI over the last `days` days, net of PI selling costs.

    Only PI activity counts: market sales of PI products, VOC buybacks with PI products, rewards of
    VOC couriers taking PI products to market (`pi_shipment`), customs taxes, and the sales tax and
    broker fees of PI trades. The wallet journal doesn't name the item, so a `transaction_tax` counts
    when it belongs to a PI sale (its context is the sale's transaction id, or, for data synced
    before transaction ids were kept, it has the sale's timestamp) and a `brokers_fee` when it
    belongs to a PI sell order AstraCore still sees (its context is the order id, or it has the
    order's issue time). Fees of PI orders that already closed before the last refresh can be
    missed: Earned may under-count those fees, but never books a non-PI fee."""
    cutoff = time.time() - days * 86400
    sales = buyback = costs = 0.0
    taxes = 0.0
    locs = locations()
    shipments = {c["contract_id"] for ch in characters for c in ch.get("contracts", []) if pi_shipment(c, locs)}
    buybacks = {c["contract_id"] for ch in characters for c in ch.get("contracts", []) if pi_buyback(c)}
    for ch in characters:
        w = ch.get("wallet") or {}
        pi_sales = w.get("sales", [])
        sale_ids = {t["transaction_id"] for t in pi_sales if t.get("transaction_id")}
        sale_times = {t["date"] for t in pi_sales if t.get("date")}
        sell_orders = [o for o in ch.get("orders", []) if not o.get("is_buy_order")]
        order_ids = {o["order_id"] for o in sell_orders if o.get("order_id")}
        order_times = {o["issued"] for o in sell_orders if o.get("issued")}
        for t in pi_sales:
            if (_ts(t["date"]) or 0) >= cutoff:
                sales += t["qty"] * t["unit_price"]
        for j in w.get("journal", []):
            if (_ts(j["date"]) or 0) < cutoff:
                continue
            amt = j.get("amount") or 0.0
            ref, ctx = j["ref_type"], j.get("context_id")
            if ref == "contract_price" and amt > 0 and ctx in buybacks:
                buyback += amt
            elif ref == "contract_reward" and amt < 0 and ctx in shipments:
                costs += -amt
            elif amt >= 0:
                continue
            elif ref in ("planetary_export_tax", "planetary_import_tax"):
                taxes += -amt
            elif ref == "transaction_tax" and (ctx in sale_ids or j["date"] in sale_times):
                taxes += -amt
            elif ref == "brokers_fee" and (ctx in order_ids or j["date"] in order_times):
                taxes += -amt
    net = sales + buyback - costs - taxes
    return {"days": days, "market_sales": round(sales), "buyback": round(buyback),
            "courier_costs": round(costs), "taxes": round(taxes), "net": round(net),
            "net_per_day": round(net / days),
            "balance": round(sum((ch.get("wallet") or {}).get("balance", 0) or 0 for ch in characters))}


def _plan_product(pi: Optional[PIData], col: dict) -> Optional[int]:
    if col.get("product_id"):
        return col["product_id"]
    return pi.by_name.get(str(col.get("product") or "").lower()) if pi else None


def _eligible(ch: dict) -> bool:
    """Characters the planner plans for (no template fits below Command Center Upgrades 2)."""
    return int(ch.get("ccu_level", 0) or 0) >= 2


def _plan_characters(plan: dict) -> set:
    ids = {c.get("character_id") for c in plan.get("characters", []) if c.get("character_id") is not None}
    return ids or {c.get("character_id") for c in plan.get("colonies", [])}


def progress_against(pi: Optional[PIData], plan: dict, characters: List[dict],
                     names: Optional[Dict[int, dict]] = None) -> dict:
    """A copy of a saved plan with build actions and removals worked out again from the colonies the
    characters have right now (the saved ones are frozen at the moment the plan was made).

    A planned colony counts as built only when the character has a colony on that planet that makes
    the planned product; a colony there making something else still needs a rebuild (`current` says
    what it makes). Removals are the plan characters' current colonies the plan doesn't use. The
    action the plan was saved with stays in `saved_action`."""
    from .optimizer import existing_product   # optimizer imports this module
    names = names or {}
    out = {**plan, "colonies": [dict(c) for c in plan.get("colonies", [])]}
    have = {(ch["character_id"], col["planet_id"]): col for ch in characters for col in ch.get("colonies", [])}
    for c in out["colonies"]:
        c.setdefault("saved_action", c.get("action"))
        col = have.get((c.get("character_id"), c.get("planet_id")))
        if col is None:
            c["action"] = "new"
            continue
        want = _plan_product(pi, c)
        made = existing_product(pi, col) if pi else None
        if pi is None or want is None or made == want:
            c["action"] = "keep"            # (without static data the planet being taken is all we know)
        elif made is None and c.get("saved_action", "new") == "new":
            c["action"] = "new"             # command center placed, nothing set up yet: still being built
        else:
            c["action"] = "rebuild"
            c["current"] = pi.name(made) if made else "nothing yet"
    planned = {(c.get("character_id"), c.get("planet_id")) for c in out["colonies"]}
    in_plan = _plan_characters(plan)
    removals = []
    for ch in characters:
        if ch["character_id"] not in in_plan:
            continue                        # a character the plan doesn't know: see plan_drift
        for col in ch.get("colonies", []):
            if (ch["character_id"], col["planet_id"]) in planned:
                continue
            made = existing_product(pi, col) if pi else None
            pn = colony_name(names, col)
            removals.append({"character": ch["name"], "character_id": ch["character_id"],
                             "planet_id": col["planet_id"], "planet": pn["name"], "system": pn["system"],
                             "current": pi.name(made) if pi and made else "?"})
    out["removals"] = removals
    return out


def plan_drift(pi: Optional[PIData], plan: Optional[dict], characters: List[dict]) -> Optional[dict]:
    """How the colonies and the characters changed in ways the saved plan didn't foresee. Building
    what the plan asks for and abandoning what it removes is progress, not drift. None when the plan
    still describes reality.

      colonies    a colony on a planet the plan neither uses nor removes (built off-plan), or a colony
                  the plan kept as it was that is gone or now makes something else
      characters  planning characters added since (Command Center Upgrades 2+) or no longer planned"""
    if not plan or "colonies" not in plan:
        return None
    from .optimizer import existing_product   # optimizer imports this module
    plan_chars = _plan_characters(plan)
    now_chars = {ch["character_id"] for ch in characters if _eligible(ch)}
    added = sorted(ch["name"] for ch in characters if _eligible(ch) and ch["character_id"] not in plan_chars)
    removed = sorted(c.get("name") or "?" for c in plan.get("characters", [])
                     if c.get("character_id") not in now_chars)
    by_name = {c.get("name"): c.get("character_id") for c in plan.get("characters", [])}
    planned = {(c.get("character_id"), c.get("planet_id")): c for c in plan.get("colonies", [])}
    removals = {(r.get("character_id") or by_name.get(r.get("character")), r.get("planet_id"))
                for r in plan.get("removals", [])}
    have = {(ch["character_id"], col["planet_id"]): col for ch in characters if ch["character_id"] in plan_chars
            for col in ch.get("colonies", [])}
    differ = [key for key in have if key not in planned and key not in removals]
    for key, c in planned.items():
        if c.get("character_id") not in now_chars or (c.get("saved_action") or c.get("action")) != "keep":
            continue                        # character changes count once; new and rebuild are progress
        col = have.get(key)
        if col is None:
            differ.append(key)
        elif pi is not None:
            want, made = _plan_product(pi, c), existing_product(pi, col)
            if want is not None and made is not None and made != want:
                differ.append(key)
    changed = len(added) + len(removed)
    if not differ and not changed:
        return None
    parts = []
    if differ:
        parts.append(f"{len(differ)} colon{'y differs' if len(differ) == 1 else 'ies differ'}")
    if changed:
        parts.append(f"{changed} character{' changed' if changed == 1 else 's changed'}")
    return {"colonies": len(differ), "characters": changed, "added": added, "removed": removed,
            "summary": ", ".join(parts)}


def build_progress(plan: Optional[dict]) -> Optional[dict]:
    """Counts for the plan-status bar; `plan` should come from `progress_against` (live actions)."""
    if not plan or "colonies" not in plan:
        return None
    acts = defaultdict(int)
    for c in plan["colonies"]:
        acts[c["action"]] += 1
    return {"done": acts["keep"], "todo": acts["new"] + acts["rebuild"], "total": len(plan["colonies"]),
            "removals": len(plan.get("removals", [])), "rebuild": acts["rebuild"], "new": acts["new"]}
