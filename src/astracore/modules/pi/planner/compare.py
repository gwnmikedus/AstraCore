"""Side-by-side facts for comparing plans: income, effort and how uncertain the income is.

Used by the guided setup (one row per answer), the plan result (this plan vs the active one) and
Operate (saved plans). Pure functions over a plan result, so old saved plans with missing fields
still compare instead of failing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Minutes of your time per week. Rough, but the same yardstick for every plan; the guided setup
# shows the same breakdown in its time note.
MIN_PER_RESTART = 1.5
MIN_PER_LOGIN = 1
MIN_PER_PICKUP = 1
MIN_PER_SYSTEM_VISIT = 5
MIN_PER_60K_M3 = 20
MIN_PER_RESTOCK = 3
MIN_PER_TRANSFER = 2
MIN_PER_BATCH = 5
MIN_SELL_ORDERS_WEEK = 20

LEVELS = ((0, "lower", "Lower"), (1, "medium", "Medium"), (3, "higher", "Higher"))


def _get(settings: Any, name: str, default: Any) -> Any:
    if settings is None:
        return default
    if isinstance(settings, dict):
        value = settings.get(name, default)
    else:
        value = getattr(settings, name, default)
    return default if value is None or value == "" else value


def characters_used(res: dict) -> int:
    """Characters with at least one colony in the plan."""
    ids = {c.get("character_id") for c in res.get("colonies") or []}
    return len(ids) if ids else sum(1 for ch in res.get("characters") or [] if ch.get("used"))


def effort_minutes(totals: dict, settings: Any, characters: int) -> Optional[float]:
    """Estimated minutes of your time per week to run a plan with these totals."""
    if not totals or "colonies" not in totals:
        return None
    ship = max(1.0, float(_get(settings, "ship_every_days", 7)))
    cycle = max(1.0, float(_get(settings, "cycle_days", 3)))
    rounds, cycles = 7 / ship, 7 / cycle
    colonies = int(totals.get("colonies") or 0)
    chars = min(max(0, int(characters)), colonies)
    minutes = (float(totals.get("restarts_per_week") or 0) * MIN_PER_RESTART
               + cycles * chars * MIN_PER_LOGIN
               + rounds * (colonies * MIN_PER_PICKUP + int(totals.get("systems") or 0) * MIN_PER_SYSTEM_VISIT)
               + float(totals.get("m3_per_week") or 0) / 60000 * MIN_PER_60K_M3
               + int(totals.get("factories") or 0) * cycles * MIN_PER_RESTOCK
               + int(totals.get("transfers") or 0) * rounds * MIN_PER_TRANSFER
               + rounds * MIN_PER_BATCH
               + (MIN_SELL_ORDERS_WEEK if _get(settings, "use_sell_orders", False) else 0))
    return round(minutes, 1)


def uncertainty(yield_measured: Optional[bool], sell_orders: bool, courier: bool, held: int,
                unsellable: int) -> Dict[str, Any]:
    """How far the income can drift from the estimate, with the reasons. Not a probability."""
    reasons: List[str] = []
    score = 0
    if yield_measured is False:
        reasons.append("Yield is an estimate until your extractors have run")
        score += 2
    elif yield_measured is None:
        reasons.append("This saved plan doesn't record whether yield was measured")
        score += 1
    if sell_orders:
        reasons.append("Sell orders: price and time to sell can change")
        score += 1
    if courier:
        reasons.append("Courier: prices can move during about 3 days in transit")
        score += 1
    if held:
        reasons.append(f"{held} batch{'es' if held != 1 else ''} held until the courier fee is worth paying")
        score += 1
    if unsellable:
        reasons.append(f"{unsellable} product{'s' if unsellable != 1 else ''} without an enabled way to sell")
        score += 1
    level, label = "lower", "Lower"
    for threshold, code, text in LEVELS:
        if score >= threshold:
            level, label = code, text
    return {"level": level, "label": label, "reasons": reasons or ["Measured yield and instant sales"]}


def plan_facts(res: dict, settings: Any = None) -> Dict[str, Any]:
    """Everything a comparison row needs beyond `totals`."""
    if not res or "error" in res:
        return {}
    totals = res.get("totals") or {}
    selling = res.get("selling") or {}
    batches = selling.get("batches") or []
    shipped = [b for b in batches if not b.get("hold")]
    channels = {b.get("channel") or "" for b in shipped}
    y = res.get("yield")
    yield_measured = bool(y.get("calibrated")) if isinstance(y, dict) and "calibrated" in y else None
    sell_orders = any(c.endswith("_sell") for c in channels)
    courier = any(c.startswith(("jita", "amarr")) for c in channels)
    held = sum(1 for b in batches if b.get("hold"))
    unsellable = len(selling.get("unsellable") or [])
    used = characters_used(res)
    systems = sorted({c.get("system") for c in res.get("colonies") or [] if c.get("system")})
    return {
        "minutes_per_week": effort_minutes(totals, settings, used),
        "characters_used": used,
        "characters_total": len(res.get("characters") or []),
        "system_names": systems,
        "dropoff": res.get("hub") or res.get("dropoff") or "",
        "sell_net_per_day": selling.get("net_per_day"),
        "yield_measured": yield_measured,
        "sell_orders": sell_orders,
        "courier": courier,
        "held_batches": held,
        "uncertainty": uncertainty(yield_measured, sell_orders, courier, held, unsellable),
    }
