"""AstracorePI: everything a plan needs for one profile, solving through the fair-use gate,
and the dashboard tile."""
from __future__ import annotations

import asyncio
import copy
import logging
import math
import time
from typing import Dict, List, Optional

from astracore import db
from astracore.core import fmt
from astracore.core.solvegate import GATE, cache_key
from astracore.esi import errors as esi_errors
from astracore.esi.client import ESIClient

from . import store
from .intel import area as area_mod
from .intel import richness as rich
from .intel import space as space_mod
from .module import PI_REQUIRED
from .planner import checklist, compare, demand, nextup, notices, operate, optimizer, prices, selling, setups, upkeep
from .planner import skills as skills_mod
from .settings import Settings, auto_teamwork
from .static_data import dalshooth, sde_loader, voc

log = logging.getLogger("astracore")
REQUIRED_SCOPES = set(PI_REQUIRED.scopes)
REPLAN_MIN_GAIN = 0.001   # a re-plan around thin markets must earn at least 0.1% more to replace the first


def pi_ready(ch: dict) -> bool:
    """The character's token covers AstracorePI's required bundle."""
    return REQUIRED_SCOPES <= set(ch.get("scopes") or []) and ch.get("status") == "ok"


def characters(profile_id: int, enabled_only: bool = False) -> List[dict]:
    return db.list_characters(profile_id, enabled_only=enabled_only)


def planning_characters(profile_id: int) -> List[dict]:
    """Included in AstracorePI and readable (a character still needing a login keeps its last data)."""
    return [c for c in db.list_characters(profile_id, enabled_only=True) if c.get("has_token")]


# --------------------------------------------------------------------------- shared loading
async def load_static():
    async with ESIClient() as esi:
        pi = await sde_loader.load(esi)
        tpl = await dalshooth.load(esi, pi.by_name)
    return pi, tpl


LAST_AREA_KEY = "pi_last_area_query:"


def _area_owner(chars, s: Settings) -> str:
    return LAST_AREA_KEY + ",".join(str(c["character_id"]) for c in sorted(chars, key=lambda c: c["character_id"])) \
        + "|" + (s.extra_area or "").strip().lower()


async def load_space(chars, s: Settings, force: bool = False, outage: Optional[esi_errors.Outage] = None):
    """The characters' area. When ESI isn't answering, the area they last resolved (noted in `outage`)."""
    try:
        async with ESIClient() as esi:
            area = await space_mod.load(esi, chars, s.extra_area, force=force)
            if outage is not None and esi.stale:
                outage.note(esi_errors.ESIUnavailable("served expired public copies", "unreachable"))
    except Exception as e:  # noqa: BLE001 - falls back below, re-raised when there is nothing to show
        if not esi_errors.is_outage(e):
            raise
        query = db.kv_get(_area_owner(chars, s))
        area = area_mod.cached(query) if query else None
        if area is None:
            raise
        log.warning("area: ESI unavailable, showing the last resolved area (%s)", e)
        if outage is not None:
            outage.note(e)
        return area
    if area and area.get("query"):
        db.kv_set(_area_owner(chars, s), area["query"])
    return area


def calibrated_yield(chars, area) -> Optional[float]:
    sec = {}
    if area:
        sys_sec = {v["system_id"]: v["security"] for v in area["systems"].values()}
        for c in chars:
            for col in c.get("colonies", []):
                if col.get("solar_system_id") in sys_sec:
                    sec[col["planet_id"]] = sys_sec[col["solar_system_id"]]
    return rich.calibrate_head_yield({c["character_id"]: c["colonies"] for c in chars}, sec, 1.0)


_history_task: Optional[asyncio.Task] = None


def refresh_history_soon(pi) -> None:
    """Regional trade history changes once a day and takes a few hundred ESI calls, so it refreshes
    in the background; plans use the last copy (or the order books alone) meanwhile."""
    global _history_task
    if _history_task and not _history_task.done():
        return

    async def run():
        try:
            async with ESIClient() as esi:
                await prices.refresh_history(esi, pi)
        except Exception:  # noqa: BLE001 - plans still work on order books alone
            log.exception("market history")

    _history_task = asyncio.get_running_loop().create_task(run())


async def warm_history() -> None:
    """At startup: fetch trade history in the background if it's missing or a day old, so the first
    plan on a fresh install already has evidence of demand. Never blocks startup or fails it."""
    if not prices.history_stale():
        return
    try:
        pi = sde_loader.cached()
        if pi is None:
            async with ESIClient() as esi:
                pi = await sde_loader.load(esi)
        refresh_history_soon(pi)
        if _history_task:
            await _history_task
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - the first plan fetches it again on demand
        log.exception("market history warm-up")


async def refresh_prices(pi) -> bool:
    """Fetch the order books now. False when ESI returned none (the last books stay in use)."""
    async with ESIClient() as esi:
        await prices.refresh(esi, pi)
    return not prices.stale()


async def market_data(pi, outage: Optional[esi_errors.Outage] = None):
    if prices.stale():
        if not await refresh_prices(pi) and outage is not None:
            # no order book loaded: plans use the last ones (refresh keeps them)
            outage.note(None, prices.cached().get("at"))
    if prices.history_stale():
        refresh_history_soon(pi)
    info = voc.routes_info()
    if not info["at"] or time.time() - info["at"] > 86400:
        await voc.refresh_routes()
    return prices.cached()["books"]


async def planning_context(profile_id: int, s: Optional[Settings] = None, persist_default: bool = True) -> dict:
    """Everything a plan needs. `s` = settings to plan with (default: the profile's saved ones)."""
    s = s or store.load_settings(profile_id)
    chars = planning_characters(profile_id)
    outage = esi_errors.Outage()     # what couldn't be refreshed: pages show a banner, not an error
    pi, tpl = await load_static()
    area = await load_space(chars, s, outage=outage) if chars else None
    if area and not s.selected_constellations:
        s.selected_constellations = space_mod.default_selection(space_mod.grouped(area, chars))
        if persist_default:
            saved = store.load_settings(profile_id)
            saved.selected_constellations = s.selected_constellations
            store.save_settings(profile_id, saved)
    systems = space_mod.selected_systems(area, s.selected_constellations) if area else {}
    books = await market_data(pi, outage)
    cal = calibrated_yield(chars, area) if s.auto_calibrate else None
    head_yield = cal or s.head_yield_per_hour
    # planet richness: your manual overrides win, then what your own extractors measured
    measured = rich.measured_richness({c["character_id"]: c["colonies"] for c in chars}, head_yield) \
        if s.auto_calibrate else {}
    manual = store.planet_overrides(profile_id)
    overrides = {**measured, **manual}
    hub = optimizer.resolve_hub(area, s, systems, overrides) if area and systems else None
    dropoff = hub["name"] if hub else ""
    local = selling.in_delve(dropoff, area)
    origin, origin_jumps = selling.courier_origin(dropoff, area)
    seller = skills_mod.best_seller(chars)
    sell_s = skills_mod.apply(s, seller)   # taxes of the character who sells
    solve_s = copy.deepcopy(sell_s)
    solve_s.hub_system = dropoff  # values below are computed for this drop-off
    teamwork_auto = auto_teamwork(s, sum(1 for c in chars if setups.can_plan(c)))
    if teamwork_auto:
        solve_s.cross_character = True
    hist = prices.history_cached()
    # sell orders are only valued where recent trades show they sell (no history yet: instant-sale prices)
    values = selling.best_values(pi, sell_s, books, dropoff, local, origin, hist["markets"])
    buy = selling.buy_costs(pi, sell_s, books, dropoff, local, origin)
    buy_cap = demand.buy_limits(pi, sell_s, books, hist["markets"], local, optimizer.capital_days(s)) if buy else {}
    return dict(profile_id=profile_id, s=sell_s, solve_s=solve_s, chars=chars, pi=pi, tpl=tpl, area=area,
                systems=systems, books=books, books_at=prices.cached().get("at"), history=hist["markets"],
                history_at=hist["at"], values=values, buy=buy, buy_cap=buy_cap, dropoff=dropoff, local=local, overrides=overrides,
                manual_overrides=manual, origin=origin, origin_jumps=origin_jumps, seller=seller,
                measured=measured, head_yield=head_yield, calibrated=cal, outage=outage, teamwork_auto=teamwork_auto)


def outage_banner(ctx: dict) -> Optional[dict]:
    """The ESI banner for a page built from `planning_context` (None: everything was fresh)."""
    outage = ctx.get("outage")
    if not outage:
        return None
    return outage.banner(c.get("synced_at") for c in ctx.get("chars") or [])


def _sell_side(ctx, res: dict) -> None:
    """Selling plan, channel table and market-demand check for a solved plan (in place)."""
    units = {x["type_id"]: x["units_per_day"] for x in res["sold"]}
    history = ctx.get("history")
    res["selling"] = selling.sell_plan(ctx["pi"], ctx["s"], ctx["books"], ctx["dropoff"], units,
                                       local=ctx["local"], origin=ctx["origin"],
                                       origin_jumps=ctx["origin_jumps"], history=history)
    res["channels"] = selling.compare_table(ctx["pi"], ctx["s"], ctx["books"], ctx["dropoff"],
                                            list(units), ctx["local"], ctx["origin"], history)
    available = {k for row in res["channels"] for k in row["channels"]}
    res["channel_labels"] = {k: selling.LABELS[k] for k in selling.PLANNER_CHANNELS if k in available}
    res["selling_coverage"] = selling.coverage(ctx["dropoff"], ctx["area"])
    res["self_haul"] = any(b["channel"].endswith("_self") for b in res["selling"]["batches"])
    res["demand"] = demand.assess(ctx["pi"], ctx["s"], ctx["books"], history or {},
                                  res["selling"], res["channels"], units,
                                  ctx.get("books_at"), ctx.get("history_at"))
    demand.sell_order_days(res["selling"], res["demand"])


def _buy_side(ctx, res: dict) -> None:
    """Where each bought input comes from and how much to buy per restock round (in place)."""
    s = ctx["s"]
    cycle = max(1.0, float(s.cycle_days))
    for r in res.get("bought") or []:
        for src in r.get("sources") or []:
            src["label"] = selling.BUY_LABELS.get(src["channel"], src["channel"])
        r["where"] = "; ".join(src["label"] for src in r.get("sources") or [])
        r["per_restock"] = round(r["units_per_day"] * cycle)
    res["buying"] = {"enabled": bool(s.buy_inputs), "budget_isk": float(s.input_budget_isk or 0),
                     "capital_days": optimizer.capital_days(s), "restock_days": cycle,
                     "share": demand.BUY_INPUT_SHARE}


def realistic_isk(res: dict, used: Dict[int, float], base: Dict[int, float]) -> float:
    """ISK/day of a solved plan once its batches are really sold: products the demand check flags
    at what the visible buyers pay for the batch, every other product at its quoted best value.
    `used` = the values the plan was solved with."""
    real = demand.realistic_values(res["demand"], base)
    isk = float(res["totals"]["isk_per_day"])
    for x in res["sold"]:
        t = x["type_id"]
        isk += x["units_per_day"] * (real.get(t, base.get(t, 0.0)) - used.get(t, 0.0))
    return isk


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _describe_replan(pi, first: dict, again: dict, base: Dict[int, float], real: Dict[int, float]) -> None:
    """What the re-plan around thin markets changed, in `again["demand"]`: products it still sells at
    a lower value (`replanned`) and products it no longer sells (`dropped`), each with a plain reason
    from the first plan's demand check."""
    kept = {x["type_id"] for x in again["sold"]}
    why = {r["type_id"]: r.get("reason") or "" for r in first["demand"]["rows"] if r.get("reason")}
    order = sorted(real, key=pi.name)
    again["demand"]["replanned"] = [
        {"type_id": t, "item": pi.name(t), "quoted": round(base.get(t, 0.0), 2), "realistic": round(real[t], 2),
         "reason": why.get(t, "")} for t in order if t in kept]
    again["demand"]["dropped"] = [{"type_id": t, "item": pi.name(t), "reason": why.get(t, "")}
                                  for t in order if t not in kept]


def count_realistic(sp: dict, channels: List[dict], real: Dict[int, float]) -> None:
    """Value the sell plan's batches like the re-plan did: products the demand check re-valued count at
    what their batch really fetches, not the quoted price (in place). `channels` = compare_table rows,
    `real` = net ISK per unit."""
    if not sp or not real:
        return
    by_name = {r["item"]: r for r in channels}
    total = 0.0
    for b in sp.get("batches", []):
        cut = 0.0
        for item, qty in b["items"].items():
            r = by_name.get(item)
            if r and r["type_id"] in real:
                cut += qty * max(0.0, (r["channels"].get(b["channel"]) or 0.0) - real[r["type_id"]])
        if cut > 0:
            b["quoted_net"] = b["net"]
            b["net"] = round(b["net"] - cut)
        if not b.get("hold"):
            total += b["net"]
    sp["net_per_cycle"] = round(total)
    sp["net_per_day"] = round(total / max(1.0, float(sp.get("every_days") or 1.0)))


def replan_summary(d: dict, gain: float) -> str:
    """One friendly line about the re-plan around thin markets; the details are in Market demand."""
    adjusted, dropped = d.get("replanned") or [], d.get("dropped") or []
    parts = []
    if adjusted:
        parts.append(f"{_plural(len(adjusted), 'product', 'products')} counted at a lower price")
    if dropped:
        parts.append(f"{', '.join(r['item'] for r in dropped)} dropped")
    return (f"We adjusted the plan to what buyers can really take: {', '.join(parts)}. This mix earns about "
            f"{fmt.isk(gain)} ISK/day more once the batches are really sold. Details under Market demand.")


def richness_sources(colonies: List[dict], manual: dict, measured: dict) -> None:
    """Where each planned planet's richness comes from, for the plan rows' "Scanned in game" control:
    "scan" (the pilot's own override wins), "extractors" (measured) or "estimate" (from security)."""
    for c in colonies:
        pid = c.get("planet_id")
        c["richness_source"] = "scan" if pid in manual else "extractors" if pid in measured else "estimate"


def sell_order_fallback_note(rows: List[dict]) -> dict:
    """Products a sell order would pay best for, valued at the instant-sale price instead because nothing
    shows that the listing sells (selling.sell_order_gap)."""
    reasons = sorted({r["reason"] for r in rows})
    names = notices.names([r["item"] for r in rows])
    return notices.note(
        "sell_order_fallback", f"{names} {'is' if len(rows) == 1 else 'are'} valued at the instant-sale price, "
        f"not a sell order: {'; '.join(reasons)}, so there's no basis yet to say a listing sells. "
        "Refresh prices, or check back once the trade history has loaded.", steps=("sell",), level="info")


def run_plan(ctx, s=None) -> dict:
    """The optimiser solve (blocking; call through GATE). If the market-demand check finds products
    whose batch the visible buyers can't absorb at the quoted price, it solves once more with those
    products valued at what the batch really fetches, and keeps whichever plan earns more that way."""
    s = s or ctx["solve_s"]
    base = ctx["values"]

    def solve_with(values):
        r = optimizer.plan(ctx["pi"], s, ctx["area"], ctx["systems"], ctx["chars"], values,
                           ctx["tpl"], ctx["overrides"], ctx["head_yield"], ctx.get("buy"), ctx.get("buy_cap"))
        if "error" not in r:
            _sell_side(ctx, r)
            _buy_side(ctx, r)
        return r

    res = solve_with(base)
    if "error" in res:
        return {**res, "selling_coverage": selling.coverage(ctx["dropoff"], ctx["area"])}
    real = demand.realistic_values(res["demand"], base)
    if real:   # at most one extra solve: the GATE slot is held for both
        values = {**base, **real}
        again = solve_with(values)
        if "error" not in again:
            first, second = realistic_isk(res, base, base), realistic_isk(again, values, base)
            if second - first > max(1.0, REPLAN_MIN_GAIN * abs(first)):   # not just rounding
                again["solve_seconds"] = round(again["solve_seconds"] + res["solve_seconds"], 2)
                _describe_replan(ctx["pi"], res, again, base, real)
                count_realistic(again["selling"], again["channels"], real)
                again["warnings"].append(notices.note("replan", replan_summary(again["demand"], second - first),
                                                      level="info"))
                res = again
    if ctx.get("teamwork_auto"):
        res["teamwork_auto"] = True
        n = len(res.get("transfers") or [])
        if n:
            res["warnings"].append(notices.note(
                "teamwork_auto", f"Characters supply each other in this plan ({notices.plural(n, 'transfer')}): a P3/P4 "
                "chain rarely fits one character's slots, so AstraCore turned this on for your product tier. You move "
                "the goods with 0 ISK contracts between your own characters. Choose Teamwork yourself to turn it off.",
                guided=f"Your characters supply each other in this plan ({notices.plural(n, 'transfer')}): a P3/P4 "
                       "chain rarely fits one character's slots, so we turned this on for your product tier. You move "
                       "the goods with 0 ISK contracts between your own characters. Change Teamwork to turn it off.",
                steps=("chain", "tier"), level="info"))
    if res.get("self_haul"):
        res["warnings"].append(notices.note(
            "self_haul", "You haul to the trade hub yourself. Income includes sales tax, but excludes the "
            "time, fuel and loss risk of that journey; the pickup-round time estimate does not include it.",
            steps=("sell",), level="info"))
    n_risky = len(res["demand"]["warnings"])
    if n_risky:
        res["warnings"].append(notices.note(
            "demand", f"{_plural(n_risky, 'product', 'products')} may not sell as planned at the chosen market: "
            f"see Market demand under How you get paid.", steps=("sell", "batch")))
    fallback = res["selling"].get("sell_order_fallback") or []
    if fallback:
        res["warnings"].append(sell_order_fallback_note(fallback))
    missing = res["demand"].get("books_missing") or []
    if missing:
        res["warnings"].append(notices.note(
            "books_missing", f"The order books for {notices.names(missing)} didn't load, so their buyers weren't "
            f"checked. Refresh prices before you ship."))
    res["dropoff"] = ctx["dropoff"]
    res["seller"] = ctx["seller"] if ctx["s"].taxes_from_skills else None
    res["taxes"] = {"sales_tax_pct": ctx["s"].sales_tax_pct, "broker_fee_pct": ctx["s"].broker_fee_pct,
                    "from_skills": bool(ctx["s"].taxes_from_skills and ctx["seller"])}
    res["yield"] = {"head_yield": round(ctx["head_yield"]), "calibrated": bool(ctx["calibrated"])}
    if not ctx["s"].use_self_haul and ctx["origin"] is None and ctx["dropoff"]:
        res["warnings"].append(notices.note(
            "voc_unreachable", f"VOC doesn't pick up in {ctx['dropoff']} and no VOC pickup is reachable in your "
            f"area, so products that need a courier are valued at 0. Pick a drop-off from "
            f"{', '.join(voc.COURIER_ORIGINS)}.", steps=("area", "sell")))
    elif not ctx["s"].use_self_haul and ctx["origin"] != ctx["dropoff"]:
        res["warnings"].append(notices.note(
            "voc_origin", f"VOC doesn't pick up in {ctx['dropoff']}: courier values assume you move the goods to "
            f"{ctx['origin']} ({notices.plural(ctx['origin_jumps'], 'jump')}) first.", steps=("area",), level="info"))
    richness_sources(res["colonies"], ctx["manual_overrides"], ctx["measured"])
    n_measured = len([p for p in ctx["measured"] if p not in ctx["manual_overrides"]])
    if n_measured:
        res["warnings"].append(notices.note(
            "measured_richness", f"Richness of {notices.plural(n_measured, 'planet')} comes from your own "
            f"extractors.", level="info"))
    return res


def data_stamp(profile_id: int) -> tuple:
    """Changes whenever anything a plan depends on changes (characters, overrides, prices, admin values)."""
    chars = tuple((c["character_id"], c.get("synced_at"), c["enabled"], c["status"])
                  for c in db.list_characters(profile_id))
    return (profile_id, chars, tuple(sorted(store.planet_overrides(profile_id).items())),
            prices.cached().get("at"), prices.history_cached().get("at"), voc.routes_info().get("at"),
            tuple(sorted(store.admin_defaults().items())), sde_loader.stamp())


def plan_key(profile_id: int, s: Settings) -> str:
    """Cache key of a full plan: what it depends on now, and the settings it is solved with. The guided
    setup's comparison cards and the plan result share it, so picking an answer reuses its plan."""
    return cache_key(data_stamp(profile_id), s.solve_json(), "plan")


async def solve(profile_id: int, s: Optional[Settings] = None) -> dict:
    """Full plan for the profile with settings `s` (default: saved), cached and through the gate."""
    s = s or store.load_settings(profile_id)
    key = plan_key(profile_id, s)
    if key in GATE._cache:
        return await GATE.cached(key, run_plan, None)
    ctx = await planning_context(profile_id, copy.deepcopy(s), persist_default=False)
    # planning_context may have refreshed prices or trade history: file the plan under the data it used
    return await GATE.cached(plan_key(profile_id, s), run_plan, ctx)


def whatif_summary(res: dict, s: Optional[Settings] = None) -> dict:
    """One comparison row: totals plus effort (`minutes_per_week` for settings `s`) and uncertainty."""
    if "error" in res:
        return {"error": res["error"], "selling_coverage": res.get("selling_coverage")}
    sp = res.get("selling") or {}
    return {"totals": res["totals"], "selling_coverage": res.get("selling_coverage"), "mix": optimizer._mix(res["colonies"]), "hub": res["hub"],
            "sell_net_per_day": sp.get("net_per_day"), "sell_net_per_cycle": sp.get("net_per_cycle"),
            "holds": sum(1 for b in sp.get("batches", []) if b.get("hold")),
            "channels": sorted({b["label"] for b in sp.get("batches", []) if not b.get("hold")}),
            "warnings": len(res.get("warnings", [])), "facts": compare.plan_facts(res, s),
            "tier_need": res.get("tier_need"), "teamwork_auto": bool(res.get("teamwork_auto"))}


# --------------------------------------------------------------------------- module entry + dashboard
def entry_state(profile_id: int) -> str:
    """Where /pi lands: connect | excluded | plan | operate.

    Area, Plan and Operate work with `planning_characters`, so /pi only sends a pilot there when that set
    isn't empty: with every connected character excluded from the plan it lands on `excluded` instead."""
    chars = characters(profile_id)
    if not any(pi_ready(c) or c.get("has_token") and REQUIRED_SCOPES <= set(c["scopes"]) for c in chars):
        return "connect"
    if not planning_characters(profile_id):
        return "excluded"
    if not store.active_plan(profile_id):
        return "plan"
    return "operate"


def operate_overview(pi, s: Settings, books: Dict[int, dict], chars: List[dict], area: Optional[dict],
                     plan_result: Optional[dict]) -> dict:
    """What Operate works out from synced data and the active plan, and the Next up list from it.
    Operate and Home both use this, so Home's top three are Operate's top three."""
    stock = operate.hangar_stock(pi, s, books, chars, area)
    consolidated = operate.consolidate(stock, area)
    pipe = operate.pipeline(pi, books, chars)
    up = upkeep.schedule(pi, s, chars, plan_result, area)
    prog = progress(plan_result, chars, pi)
    drift = plan_drift(plan_result, chars, pi)
    items = nextup.next_up(up, stock=stock, consolidated=consolidated, pipe=pipe, plan=plan_result,
                           progress=prog, drift=drift)
    return {"stock": stock, "consolidated": consolidated, "pipe": pipe, "upkeep": up, "progress": prog,
            "drift": drift, "next_up": items, "all_clear": None if items else nextup.all_clear(up),
            "has_colonies": any(ch.get("colonies") for ch in chars)}


async def dashboard_tile(profile: dict) -> dict:
    """Home's launcher: Operate's top Next up items and one plan line. Never solves and never calls
    ESI: it reads the active plan, synced character data and cached prices."""
    pid = profile["id"]
    state = entry_state(pid)
    tile = {"state": state, "href": {"connect": "/pi", "excluded": "/pi", "area": "/pi/area", "plan": "/pi/plan",
                                     "operate": "/pi/operate"}[state],
            "cta": {"connect": "Connect characters", "excluded": "Include a character", "area": "Choose your area",
                    "plan": "Make a plan", "operate": "Open Operate"}[state]}
    plan = store.active_plan(pid)
    chars = planning_characters(pid)
    pi = sde_loader.cached()   # read once: progress and the colony status both need it
    if plan:
        res = plan["result"]
        tile["plan_isk_per_day"] = (res.get("totals") or {}).get("isk_per_day")
        tile["plan_label"] = plan["label"]
        prog = operate.build_progress(_progress_against(res, chars, pi))
        if prog:
            tile["built"], tile["planned"] = prog["done"], prog["total"]
    if chars:
        tile["has_colonies"] = any(ch.get("colonies") for ch in chars)
    if pi is None and chars:
        tile["static_missing"] = True     # game data isn't cached yet: Operate loads it on first visit
    if pi and chars and state == "operate":
        try:
            ov = operate_overview(pi, store.load_settings(pid), prices.cached()["books"], chars, None,
                                  plan["result"] if plan else None)
            tile["next_up"] = ov["next_up"][:nextup.HOME_SHOWN]
            tile["next_up_more"] = max(0, len(ov["next_up"]) - nextup.HOME_SHOWN)
            tile["all_clear"] = ov["all_clear"]
            tile["in_hangars"] = sum(g["jita_value"] for g in ov["stock"])
            tile["earned_7d"] = operate.earnings(pi, chars, 7)["net"]
        except Exception:  # noqa: BLE001 - a tile must never break the dashboard
            log.exception("PI tile")
    tile["synced_at"] = min((c.get("synced_at") or 0) for c in chars) if chars else None
    return tile


def _progress_against(plan_result: dict, chars: List[dict], pi=None, names: Optional[dict] = None) -> dict:
    """Compare a saved plan with the colonies the characters have right now: planet and product
    must match to count as built; rebuilds and removals follow the current colonies."""
    return operate.progress_against(pi or sde_loader.cached(), copy.deepcopy(plan_result), chars, names)


def progress(plan_result: Optional[dict], chars: List[dict], pi=None) -> Optional[dict]:
    return operate.build_progress(_progress_against(plan_result, chars, pi)) if plan_result else None


def plan_drift(plan_result: Optional[dict], chars: List[dict], pi=None) -> Optional[dict]:
    """What changed since the plan was saved that the plan didn't foresee (None: still current)."""
    return operate.plan_drift(pi or sde_loader.cached(), plan_result, chars) if plan_result else None


def restock_purchases(ctx: dict, active: Optional[dict]) -> Optional[dict]:
    """Operate's shopping list for the inputs the active plan buys: one restock round's worth, bought where
    it lands cheapest at the drop-off (same pricing as the first-build checklist). None: the plan buys none."""
    res = (active or {}).get("result") or {}
    bought = [r for r in res.get("bought") or [] if r.get("units_per_day", 0) > 0]
    if not bought:
        return None
    settings = active.get("settings") or {}
    cycle = max(1.0, float(settings.get("cycle_days") or checklist.DEFAULT_SUPPLY_DAYS))
    need = {r["item"]: math.ceil(r["units_per_day"] * cycle) for r in bought}
    hour = float(settings.get("hour_isk", -1) if settings.get("hour_isk") is not None else -1)
    dropoff = res.get("hub") or ""
    buy = checklist.purchases(ctx["pi"], {}, need, ctx["books"], selling.in_delve(dropoff, ctx["area"]), dropoff,
                              ctx["area"], hour_isk=hour if hour >= 0 else checklist.DEFAULT_HOUR_ISK)
    rows = buy["stock"]
    for r in rows:
        r["item"] = r["key"]
    return {"rows": rows, "cycle_days": cycle, "dropoff": dropoff,
            "isk": round(sum(r["isk"] for r in rows)), "hauling": round(sum(r["haul_isk"] for r in rows)),
            "landed": round(sum(r["landed_isk"] for r in rows)),
            "unpriced": [r["key"] for r in rows if not r["where"]],
            "multibuy": voc.paste_list(need), "contracts": buy["contracts"],
            "capital_isk": (res.get("totals") or {}).get("capital_isk"),
            "budget_isk": float(settings.get("input_budget_isk") or 0)}


def first_build(ctx: dict, active: Optional[dict]) -> Optional[dict]:
    """Shopping and construction checklist for what the active plan still needs built."""
    if not active or "colonies" not in (active.get("result") or {}):
        return None
    res = active["result"]
    names = operate.planet_names(ctx["area"])
    out = checklist.build(ctx["pi"], _progress_against(res, ctx["chars"], ctx["pi"], names), ctx["chars"],
                          ctx["books"], ctx["tpl"], active.get("settings"),
                          selling.in_delve(res.get("hub") or "", ctx["area"]), names, area=ctx["area"])
    if out:
        out["prices_at"] = prices.cached().get("at")
    return out


async def first_build_for(profile_id: int, result: dict, settings: Optional[dict]) -> Optional[dict]:
    """The same checklist for any plan, saved or not (the exports and the plan result use it)."""
    if "colonies" not in (result or {}):
        return None
    ctx = await planning_context(profile_id, persist_default=False)
    return first_build(ctx, {"result": result, "settings": settings})


async def refresh_profile(profile_id: int, only: Optional[int] = None,
                          waits: Optional[Dict[str, int]] = None, ids: Optional[set] = None) -> Dict[str, str]:
    """Read every (or one) character of the profile from ESI. Returns {name: problem} for failures.
    `ids` limits it to those characters (the stale ones, when refreshing on a visit).
    `waits` collects {label: seconds} for data ESI hadn't updated yet (see esi_char.esi_waits)."""
    from astracore.esi import character as esi_char
    from astracore.esi import sso
    problems: Dict[str, str] = {}
    async with ESIClient() as esi:
        for c in characters(profile_id):
            if only and c["character_id"] != only or ids is not None and c["character_id"] not in ids:
                continue
            if not c.get("has_token"):
                continue
            try:
                synced = await esi_char.sync_character(esi, c["character_id"])
                if waits is not None:
                    for label, seconds in synced.get("esi_waits", {}).items():
                        waits[label] = max(waits.get(label, 0), seconds)
            except Exception as e:  # noqa: BLE001 - report per character, in plain words
                if not isinstance(e, (sso.NeedsLogin, sso.Transferred)):
                    log.warning("ESI refresh of character %s failed: %r", c["character_id"], e)
                problems[c["name"]] = esi_errors.explain(e)
            await asyncio.sleep(0)
    return problems
