"""Can the plan's output actually be sold where the plan says? A quoted top price is not demand.

For every product in the sell plan this compares one shipment (and the daily output) with the
buy orders you can see right now and the region's recent daily trade volume:

  buy orders   walk the visible buy-order book level by level: real proceeds after sales tax and
               the same per-unit hauling cost the planner used, and how much of the batch is left over.
  sell orders  an estimate only: how long the batch takes to sell if you capture a modest share of
               the daily traded volume, and how much the price moved over the history window.
  buyback      VOC pays a share of the Jita buy price; its capacity is not published.

When a market is too thin for the plan it says so and names a practical alternative."""
from __future__ import annotations

from typing import Dict, List, Optional

from ..settings import Settings
from ..static_data.sde_loader import PIData
from . import selling

MARKET_LABELS = {"jita": "Jita 4-4", "amarr": "Amarr VIII", "delve": "Delve (region-wide)"}
# Share of a region's daily traded units a new seller can expect to take with sell orders.
SELL_CAPTURE = (0.10, 0.30)
THIN_PRICE_DROP = 0.05     # walking the book costs more than 5% below the top buy price
THIN_VOLUME_SHARE = 0.25   # daily output is more than a quarter of what the region trades per day


def market_of(channel: str) -> str:
    if channel == "local_buy":
        return "delve"
    if channel.startswith("amarr"):
        return "amarr"
    return "jita"   # jita_*, buyback (priced off Jita buy)


def side_of(channel: str) -> str:
    if channel == "buyback":
        return "buyback"
    return "sell" if channel.endswith("_sell") else "buy"


def fill(levels: List[List[float]], qty: float) -> dict:
    """Sell `qty` units into buy orders from the best price down."""
    left, gross, used, worst = float(qty), 0.0, 0, None
    for price, units in levels or []:
        if left <= 0:
            break
        take = min(left, float(units))
        gross += take * price
        left -= take
        used += 1
        worst = price
    filled = float(qty) - left
    return {"filled": filled, "short": max(0.0, left), "gross": gross, "levels": used, "worst_price": worst,
            "avg_price": gross / filled if filled else 0.0}


def _alternative(row: dict, channels: Dict[str, float], books: dict, history: dict) -> Optional[dict]:
    """Best other channel that can take the whole batch."""
    for c in sorted(channels, key=channels.get, reverse=True):
        if c == row["channel"]:
            continue
        m, side = market_of(c), side_of(c)
        if side == "buy":
            if sum(u for _, u in books.get(f"{m}_buy_depth") or []) < row["qty"]:
                continue
        elif side == "sell":
            vol = (history.get(m) or {}).get("avg_volume") or 0
            if not vol or row["qty"] / (SELL_CAPTURE[0] * vol) > 30:
                continue
        return {"channel": c, "label": selling.LABELS[c], "value": round(channels[c], 2)}
    return None


def assess(pi: PIData, s: Settings, books: Dict[int, dict], history: Dict[str, Dict[int, dict]],
           sell_plan: dict, channels: List[dict], units_per_day: Dict[int, float],
           books_at: Optional[float] = None, history_at: Optional[float] = None) -> dict:
    """Demand check for every product the sell plan ships. `channels` = selling.compare_table rows."""
    tax = s.sales_tax_pct / 100.0
    by_type = {r["type_id"]: r for r in channels}
    by_name = {pi.name(t): t for t in units_per_day}
    rows, warnings = [], []
    for batch in sell_plan.get("batches", []):
        c = batch["channel"]
        for name, qty in batch["items"].items():
            t = by_name.get(name)
            if t is None:
                continue
            m, side = market_of(c), side_of(c)
            b = books.get(t, {})
            hist = (history.get(m) or {}).get(t)
            ch = (by_type.get(t) or {}).get("channels") or {}
            value = ch.get(c) or 0.0
            depth = b.get(f"{m}_buy_depth") or []
            per_day = units_per_day.get(t, 0.0)
            row = {"type_id": t, "item": name, "tier": pi.tier(t), "channel": c, "label": selling.LABELS[c],
                   "side": side, "market": m, "market_label": MARKET_LABELS[m], "qty": round(qty),
                   "per_day": round(per_day, 1), "hold": bool(batch.get("hold")),
                   "visible_units": round(sum(u for _, u in depth)), "visible_levels": len(depth),
                   "history": hist, "volume_share": None, "immediate": None, "horizon_days": None,
                   "price_uncertainty_pct": None, "status": "ok", "advice": "", "alternative": None}
            vol = (hist or {}).get("avg_volume") or 0
            if vol:
                row["volume_share"] = round(per_day / vol, 3)
            if hist and hist.get("price_cv") is not None:
                row["price_uncertainty_pct"] = round(100 * hist["price_cv"], 1)

            if side == "buy":
                top = b.get(f"{m}_buy", 0.0)
                cost = max(0.0, top * (1 - tax) - value)       # per-unit hauling the planner deducted
                f = fill(depth, qty)
                avg_net = f["avg_price"] * (1 - tax) - cost if f["filled"] else 0.0
                row["immediate"] = {"filled": round(f["filled"]), "short": round(f["short"]),
                                    "levels": f["levels"], "worst_price": f["worst_price"],
                                    "avg_net": round(avg_net, 2), "quoted_net": round(value, 2),
                                    "proceeds": round(f["filled"] * avg_net),
                                    "quoted": round(qty * value)}
                if f["short"] > 0:
                    row["status"] = "short"
                    row["advice"] = (f"{row['market_label']} buy orders take only {f['filled']:,.0f} of the "
                                     f"{qty:,.0f} units in one batch right now.")
                elif top and f["worst_price"] is not None and f["avg_price"] < top * (1 - THIN_PRICE_DROP):
                    row["status"] = "thin"
                    row["advice"] = (f"Selling the whole batch walks {f['levels']} price levels down to "
                                     f"{f['worst_price']:,.2f} ISK: ≈ {avg_net:,.2f} instead of {value:,.2f} net per unit.")
                elif row["volume_share"] is not None and row["volume_share"] > THIN_VOLUME_SHARE:
                    row["status"] = "thin"
                    row["advice"] = (f"The plan makes {per_day:,.0f}/day; {MARKET_LABELS[m]} traded about "
                                     f"{vol:,.0f}/day over the last {hist['window']} days, so buyers may not refill fast enough.")
            elif side == "sell":
                if vol:
                    lo, hi = (qty / (SELL_CAPTURE[1] * vol), qty / (SELL_CAPTURE[0] * vol))
                    row["horizon_days"] = [round(lo, 1), round(hi, 1)]
                    if hi > max(1.0, float(s.ship_every_days)):
                        row["status"] = "slow"
                        row["advice"] = (f"Estimate: a batch may take {lo:,.1f}–{hi:,.1f} days to sell, longer "
                                         f"than your {s.ship_every_days}-day shipping cycle, so stock would pile up.")
                else:
                    row["status"] = "unknown"
                    row["advice"] = "No recent trades in this region, so there is no basis to estimate how fast it sells."
            else:
                row["advice"] = ("VOC pays a share of the Jita buy price; it doesn't publish how much it can take, "
                                 "so ask before shipping unusually large volumes.")

            if not hist or not hist.get("days"):
                if row["status"] == "ok" and side != "buyback":
                    row["status"] = "unknown"
                    row["advice"] = (row["advice"] + " " if row["advice"] else "") + \
                        "No trade history yet: the visible orders are the only evidence of demand."

            if row["status"] in ("short", "thin", "slow") and not row["hold"]:
                alt = _alternative(row, ch, b, {mk: (h or {}).get(t) or {} for mk, h in history.items()})
                row["alternative"] = alt
                if alt:
                    row["advice"] += f" Alternative: {alt['label']} (≈ {alt['value']:,.2f} ISK net per unit)."
                else:
                    row["advice"] += (" Alternatives: ship smaller batches more often, split the batch "
                                      "between hubs, or list sell orders and accept a slower sale.")
                warnings.append(f"{name}: {row['advice']}")
            rows.append(row)
    rows.sort(key=lambda r: ("ok", "unknown", "slow", "thin", "short").index(r["status"]), reverse=True)
    covered = [r["history"]["days"] for r in rows if r.get("history")]
    return {"rows": rows, "warnings": warnings, "books_at": books_at, "history_at": history_at,
            "history_window": next((r["history"]["window"] for r in rows if r.get("history")), None),
            "history_days_min": min(covered) if covered else 0,
            "capture": list(SELL_CAPTURE)}
