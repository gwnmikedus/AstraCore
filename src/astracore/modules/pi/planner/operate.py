"""After setup: what to do now, where your products are, and the ISK that came in.

Pipeline:  on planets → picked up (hangar) → sold (buyback / courier → market) → ISK in wallet
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..settings import Settings
from astracore.esi.character import locations
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


ACTIVE = ("outstanding", "in_progress")
DONE = ("finished", "finished_issuer", "finished_contractor")


def _recent_days(ts: Optional[str], days: int) -> bool:
    t = _ts(ts)
    return t is not None and t > time.time() - days * 86400


def colonies_status(pi: PIData, characters: List[dict], area: Optional[dict]) -> dict:
    names = planet_names(area)
    extractors, pickups, restock = [], [], []
    for ch in characters:
        for col in ch.get("colonies", []):
            pid = col["planet_id"]
            pn = names.get(pid, {"name": f"Planet {pid}", "system": "", "type": col.get("planet_type", "")})
            pins = col.get("pins", [])
            schem_inputs = defaultdict(float)   # type -> units/day consumed on this planet
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
            for t, per_day in schem_inputs.items():
                if pi.tier(t) < 1:
                    continue  # P0 is extracted on the planet itself
                days = stock.get(t, 0.0) / per_day if per_day else None
                if days is not None and days < 2:
                    restock.append({"character": ch["name"], "planet": pn["name"], "system": pn["system"],
                                    "item": pi.name(t), "have": int(stock.get(t, 0)),
                                    "need_per_day": round(per_day), "days_left": round(days, 1)})
    extractors.sort(key=lambda e: (e["hours_left"] if e["hours_left"] is not None else 1e9))
    return {"extractors": extractors, "pickups": pickups, "restock": restock}


def hangar_stock(pi: PIData, s: Settings, books: Dict[int, dict], characters: List[dict],
                 area: Optional[dict] = None) -> List[dict]:
    """PI products sitting in stations/structures, grouped by character + location,
    each with the best way to sell it from there."""
    locs = locations()
    by_name = {ch["name"]: ch for ch in characters}
    groups: Dict[tuple, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for ch in characters:
        for a in ch.get("assets", []):
            if pi.tier(a["type_id"]) < 1 or a.get("flag") in ("Deliveries",):
                continue
            groups[(ch["name"], a["location_id"])][a["type_id"]] += a["qty"]
    seller = skills.best_seller(characters) if s.taxes_from_skills else None
    out = []
    for (who, lid), stock in groups.items():
        loc = locs.get(lid, {"name": f"Location {lid}", "system": ""})
        here = loc.get("system", "")
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
                    "unknown_location": bool(loc.get("unknown")),
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
        for b in g["plan"]["batches"]:
            key = b["channel"]
            a = advice.setdefault(key, {"label": b["label"], "channel": key, "m3": 0.0, "net": 0.0, "where": [],
                                        "hold": False, "note": b.get("note") if key.endswith("_self") else None})
            a["m3"] += b["m3"]
            a["net"] += 0 if b.get("hold") else b["net"]
            a["hold"] = a["hold"] or bool(b.get("hold"))
            where = g["location"] + (f" ({g['system']})" if g["system"] else "")
            if where not in a["where"]:
                a["where"].append(where)
    unsellable = sorted({x for g in stock for x in g["plan"].get("unsellable", [])})
    reality = [_reality(g, b, area) for g in stock for b in g["plan"]["batches"]
               if b["channel"].endswith("_self") and b["m3"] >= BIG_STACK_M3]
    return {"total_m3": round(total_m3, 1), "total_value": round(total_value), "net": round(net),
            "seller": seller, "seller_gain": round(gain), "handover": handover,
            "advice": sorted(advice.values(), key=lambda a: -a["net"]), "unsellable": unsellable,
            "reality": reality, "locations": len(stock)}


def _reality(g: dict, b: dict, area: Optional[dict]) -> dict:
    """What hauling a big stack yourself really means, next to letting VOC take it from their nearest pickup."""
    import math
    m3 = b["m3"]
    dest = "Jita" if b["channel"].startswith("jita") else "Amarr"
    out = {"where": g["location"], "system": g["system"], "m3": m3, "value": b["jita_value"], "dest": dest,
           "trips": [{"ship": name, "trips": max(1, math.ceil(m3 / cap)), "capacity": cap} for name, cap in HAUL_SHIPS],
           "voc": None}
    origin, jumps = selling.courier_origin(g["system"], area)
    if origin:
        r = voc.route(origin, voc.JITA if dest == "Jita" else voc.AMARR)
        if r:
            out["voc"] = {"origin": origin, "jumps": jumps, "fee": round(voc.courier_fee(r, m3, b["jita_value"])),
                          "contracts": max(1, math.ceil(m3 / r["max_m3"]))}
    return out


def pipeline(pi: PIData, books: Dict[int, dict], characters: List[dict]) -> dict:
    locs = locations()
    courier, buyback, other, orders, done = [], [], [], [], []
    for ch in characters:
        for c in ch.get("contracts", []):
            start = locs.get(c.get("start_location_id"), {}).get("name", "")
            end = locs.get(c.get("end_location_id"), {}).get("name", "")
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
            loc = locs.get(o["location_id"], {})
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
    cutoff = time.time() - days * 86400
    sales = buyback = costs = 0.0
    taxes = 0.0
    voc_contracts = {c["contract_id"] for ch in characters for c in ch.get("contracts", []) if c.get("voc")}
    for ch in characters:
        w = ch.get("wallet") or {}
        for t in w.get("sales", []):
            if (_ts(t["date"]) or 0) >= cutoff:
                sales += t["qty"] * t["unit_price"]
        for j in w.get("journal", []):
            if (_ts(j["date"]) or 0) < cutoff:
                continue
            amt = j.get("amount") or 0.0
            if j["ref_type"] == "contract_price" and amt > 0 and j.get("context_id") in voc_contracts:
                buyback += amt
            elif j["ref_type"] == "contract_reward" and amt < 0 and j.get("context_id") in voc_contracts:
                costs += -amt
            elif j["ref_type"] in ("transaction_tax", "brokers_fee", "planetary_export_tax",
                                   "planetary_import_tax") and amt < 0:
                taxes += -amt
    net = sales + buyback - costs - taxes
    return {"days": days, "market_sales": round(sales), "buyback": round(buyback),
            "courier_costs": round(costs), "taxes": round(taxes), "net": round(net),
            "net_per_day": round(net / days),
            "balance": round(sum((ch.get("wallet") or {}).get("balance", 0) or 0 for ch in characters))}


def build_progress(plan: Optional[dict]) -> Optional[dict]:
    if not plan or "colonies" not in plan:
        return None
    acts = defaultdict(int)
    for c in plan["colonies"]:
        acts[c["action"]] += 1
    return {"done": acts["keep"], "todo": acts["new"] + acts["rebuild"], "total": len(plan["colonies"]),
            "removals": len(plan.get("removals", [])), "rebuild": acts["rebuild"], "new": acts["new"]}
