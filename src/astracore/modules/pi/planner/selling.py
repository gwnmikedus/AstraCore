"""Turning PI products into liquid ISK: compare every channel per product.

Channels (value per unit, at your drop-off station, after all costs):
  buyback     VOC alliance buyback: % of Jita buy, sold where you are (no hauling).
  jita_buy    VOC courier to Jita, sell into buy orders (instant).
  jita_sell   VOC courier to Jita, list sell orders (more ISK, slower, needs relisting).
  amarr_buy / amarr_sell   same via Amarr.
  local_buy   sell into Delve buy orders.

Courier costs use VOC's rule: max(min fee, m3 x rate + collateral x col%). The minimum
fee is handled per shipment in `sell_plan`; per-unit values use the variable part.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..settings import Settings, hour_value
from ..static_data import voc
from ..static_data.sde_loader import PIData

LABELS = {
    "buyback": "VOC buyback",
    "jita_buy": "Courier → Jita, sell to buy orders",
    "jita_sell": "Courier → Jita, list sell orders",
    "amarr_buy": "Courier → Amarr, sell to buy orders",
    "amarr_sell": "Courier → Amarr, list sell orders",
    "local_buy": "Sell to Delve buy orders",
    "jita_self": "Haul it to Jita yourself, sell to buy orders",
    "amarr_self": "Haul it to Amarr yourself, sell to buy orders",
}
PLANNER_CHANNELS = list(LABELS)
SPEED = {"buyback": "instant", "jita_buy": "~3 days", "amarr_buy": "~3 days", "local_buy": "instant",
         "jita_sell": "3 days + listing", "amarr_sell": "3 days + listing",
         "jita_self": "your own trip", "amarr_self": "your own trip"}


def buyback_fraction(s: Settings, tier: int) -> float:
    if tier <= 1:
        return s.buyback_pct_p1 / 100.0
    return s.buyback_pct / 100.0


HUB_SYSTEMS = {"jita": "Jita", "amarr": "Amarr"}

# Hauling one hangar to a second hub yourself is a second trip. Splitting is only worth it when the
# better prices there beat that trip, valued at the pilot's hour (never less than a floor, so "max ISK"
# pilots with a 0 ISK hour don't get a separate trip for a fraction of a percent).
EXTRA_TRIP_MIN = 30
EXTRA_TRIP_FLOOR_ISK = 20e6


def extra_trip_isk(s: Settings) -> float:
    """What one extra self-haul trip to a trade hub costs you, in ISK."""
    return max(EXTRA_TRIP_FLOOR_ISK, hour_value(s) * EXTRA_TRIP_MIN / 60)


def _one_hub(choice: Dict[int, str], per_item: Dict[int, dict], trip_isk: float) -> None:
    """Self-hauled stock from one hangar goes to one hub, unless the price gain of splitting it beats
    an extra trip. Changes `choice` in place."""
    hauled = [t for t, c in choice.items() if c.endswith("_self")]
    if len({choice[t].split("_")[0] for t in hauled}) < 2:
        return

    def value(t: int, c: str) -> float:
        return per_item[t]["qty"] * per_item[t]["channels"][c]

    split = sum(value(t, choice[t]) for t in hauled)
    best = None
    for hub in HUB_SYSTEMS:
        key = f"{hub}_self"
        if all(key in per_item[t]["channels"] for t in hauled):
            total = sum(value(t, key) for t in hauled)
            if best is None or total > best[1]:
                best = (key, total)
    if best and split - best[1] <= trip_isk:
        for t in hauled:
            choice[t] = best[0]


def in_delve(system: str, area: Optional[dict]) -> bool:
    if system in voc.BUYBACK_LOCATIONS or system in voc.COURIER_ORIGINS:
        return True
    if area:
        for s in area["systems"].values():
            if s["name"] == system:
                return s.get("region") == "Delve"
    return False


def courier_origin(dropoff: str, area: Optional[dict]) -> Tuple[Optional[str], int]:
    """VOC pickup to start couriers from: the drop-off itself when VOC serves it, otherwise the
    nearest VOC pickup in your space (you move the goods there first). (None, 0) if none is known."""
    if dropoff in voc.COURIER_ORIGINS or dropoff in HUB_SYSTEMS.values():
        return dropoff, 0
    if not area:
        return None, 0
    from ..intel import area as area_mod
    start = area_mod.system_by_name(area, dropoff)
    if not start:
        return None, 0
    dist = area_mod.jumps_from(area, start["system_id"])
    best = None
    for name in voc.COURIER_ORIGINS:
        h = area_mod.system_by_name(area, name)
        if h and h["system_id"] in dist and (best is None or dist[h["system_id"]] < best[1]):
            best = (name, dist[h["system_id"]])
    return best or (None, 0)


def coverage(dropoff: str, area: Optional[dict]) -> dict:
    """Channels reachable from the resolved drop-off, without enabling any preferences."""
    origin, _ = courier_origin(dropoff, area)
    return {"local": in_delve(dropoff, area),
            "courier": any(voc.route(origin or dropoff, dest) for dest in (voc.JITA, voc.AMARR)),
            "trade_hub": dropoff in HUB_SYSTEMS.values()}


def channel_values(pi: PIData, s: Settings, books: Dict[int, dict], type_id: int, dropoff: str,
                   routes: Optional[List[dict]] = None, local: bool = True,
                   origin: Optional[str] = None, self_haul: bool = False) -> Dict[str, float]:
    """Net ISK per unit at the drop-off for every enabled channel.
    `local` = the drop-off is in Delve (buyback and Delve market are reachable).
    `origin` = VOC pickup the courier starts from (defaults to the drop-off).
    `self_haul` = when VOC can't take it from here, value it as hauled to Jita/Amarr yourself."""
    origin = origin or dropoff
    b = books.get(type_id, {})
    tier, vol = pi.tier(type_id), pi.volume(type_id)
    tax = s.sales_tax_pct / 100.0
    broker = s.broker_fee_pct / 100.0
    jita_buy = b.get("jita_buy", 0.0)
    out: Dict[str, float] = {}
    if s.use_buyback and jita_buy and local:
        frac = buyback_fraction(s, tier)
        if frac > 0:
            out["buyback"] = frac * jita_buy
    for hub_key, dest in (("jita", voc.JITA), ("amarr", voc.AMARR)):
        if not getattr(s, f"use_{hub_key}"):
            continue
        if dropoff == HUB_SYSTEMS[hub_key]:
            cost = 0.0  # already there
        elif s.use_self_haul:
            if b.get(f"{hub_key}_buy"):
                out[f"{hub_key}_self"] = b[f"{hub_key}_buy"] * (1 - tax)
            continue
        else:
            r = voc.route(origin, dest, routes)
            if not r:
                if self_haul and b.get(f"{hub_key}_buy"):
                    out[f"{hub_key}_self"] = b[f"{hub_key}_buy"] * (1 - tax)
                continue
            coll = jita_buy or b.get(f"{hub_key}_buy", 0.0)
            cost = voc.courier_variable_per_unit(r, vol, coll)
        if b.get(f"{hub_key}_buy"):
            out[f"{hub_key}_buy"] = b[f"{hub_key}_buy"] * (1 - tax) - cost
        if s.use_sell_orders and b.get(f"{hub_key}_sell"):
            out[f"{hub_key}_sell"] = b[f"{hub_key}_sell"] * (1 - tax - broker) - cost
    if s.use_local and local and b.get("delve_buy"):
        out["local_buy"] = b["delve_buy"] * (1 - tax)
    return {k: v for k, v in out.items() if v > 0}


def best_values(pi: PIData, s: Settings, books: Dict[int, dict], dropoff: str,
                local: bool = True, origin: Optional[str] = None) -> Dict[int, float]:
    """What the planner should value each product at (best channel per unit)."""
    routes = voc.routes_cached()
    vals = {}
    for t in pi.items:
        if pi.tier(t) < 1:
            continue
        ch = channel_values(pi, s, books, t, dropoff, routes, local, origin)
        vals[t] = max(ch.values()) if ch else 0.0
    return vals


def compare_table(pi: PIData, s: Settings, books: Dict[int, dict], dropoff: str, type_ids: List[int],
                  local: bool = True, origin: Optional[str] = None) -> List[dict]:
    routes = voc.routes_cached()
    rows = []
    for t in type_ids:
        ch = channel_values(pi, s, books, t, dropoff, routes, local, origin)
        best = max(ch, key=ch.get) if ch else None
        rows.append({"type_id": t, "item": pi.name(t), "tier": pi.tier(t), "volume": pi.volume(t),
                     "jita_buy": books.get(t, {}).get("jita_buy", 0.0),
                     "channels": {k: round(v, 2) for k, v in ch.items()}, "best": best})
    return rows


def sell_plan(pi: PIData, s: Settings, books: Dict[int, dict], dropoff: str,
              units_per_day: Dict[int, float], per_day: bool = True, local: bool = True,
              origin: Optional[str] = None, origin_jumps: int = 0, self_haul: bool = False) -> dict:
    """Per shipment cycle (every `ship_every_days`): which products go where, with exact
    VOC contract values. If a courier batch is too small to beat the minimum fee, those
    products fall back to their next-best channel."""
    routes = voc.routes_cached()
    origin = origin or dropoff
    days = max(1.0, float(s.ship_every_days)) if per_day else 1.0
    per_item = {}
    for t, q in units_per_day.items():
        if q <= 0:
            continue
        ch = channel_values(pi, s, books, t, dropoff, routes, local, origin, self_haul)
        if ch:
            per_item[t] = {"qty": q * days, "channels": ch}

    choice = {t: max(v["channels"], key=v["channels"].get) for t, v in per_item.items()}
    if self_haul or s.use_self_haul:
        _one_hub(choice, per_item, extra_trip_isk(s))
    for _ in range(3):  # re-check courier batches against the minimum fee
        changed = False
        for dest_key, dest in (("jita", voc.JITA), ("amarr", voc.AMARR)):
            r = voc.route(origin, dest, routes)
            members = [t for t, c in choice.items() if c.startswith(dest_key) and not c.endswith("_self")]
            if not r or not members or origin == HUB_SYSTEMS[dest_key]:
                continue
            m3 = sum(per_item[t]["qty"] * pi.volume(t) for t in members)
            coll = sum(per_item[t]["qty"] * books.get(t, {}).get("jita_buy", 0.0) for t in members)
            fee = voc.courier_fee(r, m3, coll)
            variable = m3 * r["per_m3"] + coll * r["collateral_pct"] / 100.0
            extra = fee - variable  # minimum-fee top-up spread over the batch
            if extra <= 0:
                continue
            courier_total = sum(per_item[t]["qty"] * per_item[t]["channels"][choice[t]] for t in members) - extra
            alt = {}
            for t in members:
                others = {k: v for k, v in per_item[t]["channels"].items() if not k.startswith(dest_key)}
                alt[t] = max(others, key=others.get) if others else None
            alt_total = sum(per_item[t]["qty"] * per_item[t]["channels"][alt[t]] for t in members if alt[t])
            if alt_total > courier_total:
                for t in members:
                    if alt[t]:
                        choice[t] = alt[t]
                        changed = True
        if not changed:
            break

    groups = defaultdict(list)
    for t, c in choice.items():
        groups[c].append(t)
    batches = []
    total = 0.0
    for c, members in sorted(groups.items()):
        qty = {pi.name(t): per_item[t]["qty"] for t in members}
        m3 = sum(per_item[t]["qty"] * pi.volume(t) for t in members)
        jita_value = sum(per_item[t]["qty"] * books.get(t, {}).get("jita_buy", 0.0) for t in members)
        net = sum(per_item[t]["qty"] * per_item[t]["channels"][c] for t in members)
        batch = {"channel": c, "label": LABELS[c], "speed": SPEED[c], "items": qty,
                 "m3": round(m3, 1), "jita_value": round(jita_value), "paste": voc.paste_list(qty)}
        if c.endswith("_self"):
            # Only point at a VOC pickup that courier_origin actually found within reach of this hangar.
            via = (f" (or move it to the VOC pickup in {origin}, {origin_jumps} jumps, and courier it from there)"
                   if origin != dropoff and origin in voc.COURIER_ORIGINS else "")
            batch.update(note=f"Haul it to {'Jita' if c.startswith('jita') else 'Amarr'} "
                              f"yourself{via}, then sell. Proceeds are before your own trip time, fuel and loss risk; "
                              "those costs are not priced.")
        elif c.startswith(("jita", "amarr")) and origin not in HUB_SYSTEMS.values():
            dest = voc.JITA if c.startswith("jita") else voc.AMARR
            r = voc.route(origin, dest, routes)
            fee = voc.courier_fee(r, m3, jita_value)
            variable = m3 * r["per_m3"] + jita_value * r["collateral_pct"] / 100.0
            net -= max(0.0, fee - variable)
            batch.update(contract={
                "type": "Courier", "availability": "Private", "assign_to": voc.CORP_NAME,
                "from": origin, "to": dest, "reward": round(fee), "collateral": round(jita_value),
                "volume": round(m3, 1), "expiration": "7 days", "completion": "3 days",
                "contracts_needed": max(1, int(-(-m3 // r["max_m3"]))),
            })
            if origin != dropoff:
                batch["contract"]["move_first"] = (f"VOC doesn't pick up in {dropoff}: move it to {origin} first "
                                                   f"({origin_jumps} jumps), then create the contract there.")
        elif c == "buyback":
            batch.update(contract={"type": "Item Exchange", "assign_to": voc.CORP_NAME, "location": dropoff,
                                   "how": f"Paste the list at {voc.BUYBACK_SITE}, then create the contract "
                                          f"with the reference it gives you."})
        batch["net"] = round(net)
        if c.endswith("_self"):
            total += net
        elif net <= 0 or (batch.get("contract", {}).get("reward") and
                        batch["contract"]["reward"] > 0.25 * max(1.0, jita_value)):
            # The minimum courier fee eats this batch: hold it and ship with a later one.
            r = voc.route(origin, voc.JITA if c.startswith("jita") else voc.AMARR, routes)
            per_m3_value = (jita_value / m3) if m3 else 0
            need_m3 = (r["min_fee"] / (r["per_m3"] + per_m3_value * r["collateral_pct"] / 100.0)) if r else 0
            batch["hold"] = True
            batch["note"] = (f"Too small for VOC's minimum fee - keep it in the hangar and ship it once you "
                             f"have about {need_m3:,.0f} m³ of it.")
        else:
            total += net
        batches.append(batch)
    batches.sort(key=lambda b: -b["net"])
    unsellable = [pi.name(t) for t in units_per_day if t not in per_item and units_per_day[t] > 0]
    return {"every_days": days, "batches": batches, "net_per_cycle": round(total),
            "net_per_day": round(total / days), "dropoff": dropoff, "origin": origin,
            "origin_jumps": origin_jumps, "unsellable": unsellable}
