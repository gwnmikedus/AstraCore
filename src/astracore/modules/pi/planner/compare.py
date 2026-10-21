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
MIN_PER_PURCHASE = 5         # multibuy and a courier contract for bought inputs, once per restock round
MIN_SELL_ORDERS_WEEK = 20

# Uncertainty score, 0-100: how much of the income rests on things that can move after you plan.
# Market exposure counts by share of income, so options that sell differently get different scores.
# Estimated yield (and unsellable products) add a flat baseline: it affects every option alike.
LEVELS = ((0, "lower", "Lower"), (20, "medium", "Medium"), (50, "higher", "Higher"))
SELL_ORDER_WEIGHT = 1.0      # listed sell orders: price and time to sell both move
COURIER_WEIGHT = 0.5         # courier to buy orders: about 3 days of price movement only
HELD_WEIGHT = 1.0            # held batches: not paid until a later shipment
YIELD_BASELINE = 20
UNSELLABLE_BASELINE = 20
UNKNOWN_HELD_SHARE = 0.5     # held batches without values (old saved plans)


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
               + (cycles * MIN_PER_PURCHASE if float(totals.get("buy_isk_per_day") or 0) > 0 else 0)
               + (MIN_SELL_ORDERS_WEEK if _get(settings, "use_sell_orders", False) else 0))
    return round(minutes, 1)


def _pct(share: float) -> str:
    """A share as a plain percentage that never rounds a part up to 100% or down to 0%."""
    value = round(100 * share)
    return f"{min(99, max(1, value)) if 0 < share < 1 else value}%"


def uncertainty(yield_measured: Optional[bool], sell_orders: bool, courier: bool, held: int,
                unsellable: int, sell_share: Optional[float] = None, courier_share: Optional[float] = None,
                held_share: Optional[float] = None) -> Dict[str, Any]:
    """How far the income can drift from the estimate, with the reasons. Not a probability.

    Shares are fractions of the income (held: of all product value). `None` means unknown, for example
    an old saved plan without batch values: that factor then counts in full.
    `score` runs 0-100; `factors` gives each reason's key and share, in the same order as `reasons`.
    """
    sell = (sell_share if sell_share is not None else 1.0) if sell_orders else 0.0
    trip = (courier_share if courier_share is not None else 1.0) if courier else 0.0
    kept = (held_share if held_share is not None else UNKNOWN_HELD_SHARE) if held else 0.0
    market = min(1.0, SELL_ORDER_WEIGHT * sell + COURIER_WEIGHT * max(0.0, trip - sell) + HELD_WEIGHT * kept)
    factors: List[Dict[str, Any]] = []
    reasons: List[str] = []

    def add(key: str, text: str, share: Optional[float] = None) -> None:
        factors.append({"key": key, "share": None if share is None else round(share, 3)})
        reasons.append(text)

    if sell_orders:
        add("sell_orders", f"Sell orders: {_pct(sell)} of income; price and time to sell can change"
            if sell_share is not None else "Sell orders: price and time to sell can change", sell_share)
    if courier:
        add("courier", f"Courier: {_pct(trip)} of income; prices can move during about 3 days in transit"
            if courier_share is not None else "Courier: prices can move during about 3 days in transit",
            courier_share)
    if held:
        part = f" (about {_pct(kept)} of product value)" if held_share is not None else ""
        add("held", f"{held} batch{'es' if held != 1 else ''} held until the courier fee is worth paying{part}",
            held_share)
    if unsellable:
        add("unsellable", f"{unsellable} product{'s' if unsellable != 1 else ''} without an enabled way to sell")
    if yield_measured is False:
        add("yield_estimated", "Yield is an estimate until your extractors have run")
    elif yield_measured is None:
        add("yield_unknown", "This saved plan doesn't record whether yield was measured")
    score = min(100, round(100 * market) + (YIELD_BASELINE if yield_measured is not True else 0)
                + (UNSELLABLE_BASELINE if unsellable else 0))
    level, label = "lower", "Lower"
    for threshold, code, text in LEVELS:
        if score >= threshold:
            level, label = code, text
    return {"level": level, "label": label, "score": score, "factors": factors,
            "reasons": reasons or ["Measured yield and instant sales"]}


def income_shares(batches: List[dict]) -> Dict[str, Optional[float]]:
    """Share of the shipped income from sell orders and from couriers, and the held share of all
    product value. `None` where the batches carry no values (old saved plans)."""
    shipped = [b for b in batches if not b.get("hold")]
    held = [b for b in batches if b.get("hold")]
    if not all(isinstance(b.get("net"), (int, float)) for b in shipped):
        return {"sell": None, "courier": None, "held": None}
    total = sum(max(0.0, float(b["net"])) for b in shipped)

    def part(test) -> Optional[float]:
        if not total:
            return None
        return sum(max(0.0, float(b["net"])) for b in shipped if test(b.get("channel") or "")) / total

    held_value = sum(float(b.get("jita_value") or 0) for b in held)
    return {"sell": part(lambda c: c.endswith("_sell")),
            "courier": part(lambda c: c.startswith(("jita", "amarr"))),
            "held": held_value / (total + held_value) if held_value else None}


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
    shares = income_shares(batches)
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
        "uncertainty": uncertainty(yield_measured, sell_orders, courier, held, unsellable,
                                   sell_share=shares["sell"], courier_share=shares["courier"],
                                   held_share=shares["held"]),
    }
