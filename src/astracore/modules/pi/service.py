"""AstracorePI: everything a plan needs for one profile, solving through the fair-use gate,
and the dashboard tile."""
from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Dict, List, Optional

from astracore import db
from astracore.core import fmt
from astracore.core.solvegate import GATE, cache_key
from astracore.esi.client import ESIClient

from . import store
from .intel import richness as rich
from .intel import space as space_mod
from .module import PI_REQUIRED
from .planner import checklist, compare, demand, operate, optimizer, prices, selling
from .planner import skills as skills_mod
from .settings import Settings
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


async def load_space(chars, s: Settings, force: bool = False):
    async with ESIClient() as esi:
        return await space_mod.load(esi, chars, s.extra_area, force=force)


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


async def market_data(pi):
    if prices.stale():
        async with ESIClient() as esi:
            await prices.refresh(esi, pi)
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
    pi, tpl = await load_static()
    area = await load_space(chars, s) if chars else None
    if area and not s.selected_constellations:
        s.selected_constellations = space_mod.default_selection(space_mod.grouped(area, chars))
        if persist_default:
            saved = store.load_settings(profile_id)
            saved.selected_constellations = s.selected_constellations
            store.save_settings(profile_id, saved)
    systems = space_mod.selected_systems(area, s.selected_constellations) if area else {}
    books = await market_data(pi)
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
    values = selling.best_values(pi, sell_s, books, dropoff, local, origin)
    hist = prices.history_cached()
    return dict(profile_id=profile_id, s=sell_s, solve_s=solve_s, chars=chars, pi=pi, tpl=tpl, area=area,
                systems=systems, books=books, books_at=prices.cached().get("at"), history=hist["markets"],
                history_at=hist["at"], values=values, dropoff=dropoff, local=local, overrides=overrides,
                manual_overrides=manual, origin=origin, origin_jumps=origin_jumps, seller=seller,
                measured=measured, head_yield=head_yield, calibrated=cal)


def _sell_side(ctx, res: dict) -> None:
    """Selling plan, channel table and market-demand check for a solved plan (in place)."""
    units = {x["type_id"]: x["units_per_day"] for x in res["sold"]}
    res["selling"] = selling.sell_plan(ctx["pi"], ctx["s"], ctx["books"], ctx["dropoff"], units,
                                       local=ctx["local"], origin=ctx["origin"],
                                       origin_jumps=ctx["origin_jumps"])
    res["channels"] = selling.compare_table(ctx["pi"], ctx["s"], ctx["books"], ctx["dropoff"],
                                            list(units), ctx["local"], ctx["origin"])
    res["channel_labels"] = {k: selling.LABELS[k] for k in selling.PLANNER_CHANNELS}
    res["demand"] = demand.assess(ctx["pi"], ctx["s"], ctx["books"], ctx.get("history") or {},
                                  res["selling"], res["channels"], units,
                                  ctx.get("books_at"), ctx.get("history_at"))


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


def run_plan(ctx, s=None) -> dict:
    """The optimiser solve (blocking; call through GATE). If the market-demand check finds products
    whose batch the visible buyers can't absorb at the quoted price, it solves once more with those
    products valued at what the batch really fetches, and keeps whichever plan earns more that way."""
    s = s or ctx["solve_s"]
    base = ctx["values"]

    def solve_with(values):
        r = optimizer.plan(ctx["pi"], s, ctx["area"], ctx["systems"], ctx["chars"], values,
                           ctx["tpl"], ctx["overrides"], ctx["head_yield"])
        if "error" not in r:
            _sell_side(ctx, r)
        return r

    res = solve_with(base)
    if "error" in res:
        return res
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
                again["warnings"].append(replan_summary(again["demand"], second - first))
                res = again
    n_risky = len(res["demand"]["warnings"])
    if n_risky:
        res["warnings"].append(f"{_plural(n_risky, 'product', 'products')} may not sell as planned at the chosen "
                               f"market: see Market demand under How you get paid.")
    missing = res["demand"].get("books_missing") or []
    if missing:
        res["warnings"].append(f"The order books for {', '.join(missing)} didn't load, so their buyers weren't "
                               f"checked. Refresh prices before you ship.")
    res["dropoff"] = ctx["dropoff"]
    res["seller"] = ctx["seller"] if ctx["s"].taxes_from_skills else None
    res["taxes"] = {"sales_tax_pct": ctx["s"].sales_tax_pct, "broker_fee_pct": ctx["s"].broker_fee_pct,
                    "from_skills": bool(ctx["s"].taxes_from_skills and ctx["seller"])}
    res["yield"] = {"head_yield": round(ctx["head_yield"]), "calibrated": bool(ctx["calibrated"])}
    if ctx["origin"] is None and ctx["dropoff"]:
        res["warnings"].append(f"VOC doesn't pick up in {ctx['dropoff']} and no VOC pickup is reachable in your "
                               f"area, so products that need a courier are valued at 0. Pick a drop-off "
                               f"from {', '.join(voc.COURIER_ORIGINS)}.")
    elif ctx["origin"] != ctx["dropoff"]:
        res["warnings"].append(f"VOC doesn't pick up in {ctx['dropoff']}: courier values assume you move the "
                               f"goods to {ctx['origin']} ({ctx['origin_jumps']} jumps) first.")
    n_measured = len([p for p in ctx["measured"] if p not in ctx["manual_overrides"]])
    if n_measured:
        res["warnings"].append(f"Richness of {n_measured} planet(s) comes from your own extractors.")
    return res


def data_stamp(profile_id: int) -> tuple:
    """Changes whenever anything a plan depends on changes (characters, overrides, prices, admin values)."""
    chars = tuple((c["character_id"], c.get("synced_at"), c["enabled"], c["status"])
                  for c in db.list_characters(profile_id))
    return (profile_id, chars, tuple(sorted(store.planet_overrides(profile_id).items())),
            prices.cached().get("at"), prices.history_cached().get("at"), voc.routes_info().get("at"),
            tuple(sorted(store.admin_defaults().items())))


async def solve(profile_id: int, s: Optional[Settings] = None) -> dict:
    """Full plan for the profile with settings `s` (default: saved), cached and through the gate."""
    s = s or store.load_settings(profile_id)
    key = cache_key(data_stamp(profile_id), s.to_json(), "plan")
    ctx = await planning_context(profile_id, copy.deepcopy(s), persist_default=False) \
        if key not in GATE._cache else None
    return await GATE.cached(key, run_plan, ctx) if ctx else GATE._cache[key]


def whatif_summary(res: dict, s: Optional[Settings] = None) -> dict:
    """One comparison row: totals plus effort (`minutes_per_week` for settings `s`) and uncertainty."""
    if "error" in res:
        return {"error": res["error"]}
    sp = res.get("selling") or {}
    return {"totals": res["totals"], "mix": optimizer._mix(res["colonies"]), "hub": res["hub"],
            "sell_net_per_day": sp.get("net_per_day"), "sell_net_per_cycle": sp.get("net_per_cycle"),
            "holds": sum(1 for b in sp.get("batches", []) if b.get("hold")),
            "channels": sorted({b["label"] for b in sp.get("batches", []) if not b.get("hold")}),
            "warnings": len(res.get("warnings", [])), "facts": compare.plan_facts(res, s)}


# --------------------------------------------------------------------------- module entry + dashboard
def entry_state(profile_id: int) -> str:
    """Where /pi lands: connect | area | plan | operate."""
    chars = characters(profile_id)
    if not any(pi_ready(c) or c.get("has_token") and REQUIRED_SCOPES <= set(c["scopes"]) for c in chars):
        return "connect"
    if not store.load_settings(profile_id).selected_constellations:
        return "area"
    if not store.active_plan(profile_id):
        return "plan"
    return "operate"


async def dashboard_tile(profile: dict) -> dict:
    """Live status for the dashboard. Never solves: it reads the active plan and synced ESI data."""
    pid = profile["id"]
    state = entry_state(pid)
    tile = {"state": state, "href": {"connect": "/pi", "area": "/pi/area", "plan": "/pi/plan",
                                     "operate": "/pi/operate"}[state],
            "cta": {"connect": "Connect characters", "area": "Choose your area", "plan": "Make a plan",
                    "operate": "Open Operate"}[state]}
    plan = store.active_plan(pid)
    chars = planning_characters(pid)
    if plan:
        res = plan["result"]
        tile["plan_isk_per_day"] = (res.get("totals") or {}).get("isk_per_day")
        tile["plan_label"] = plan["label"]
        prog = operate.build_progress(_progress_against(res, chars))
        if prog:
            tile["built"], tile["planned"] = prog["done"], prog["total"]
    pi = sde_loader.cached()
    if pi and chars:
        try:
            st = operate.colonies_status(pi, chars, None)
            tile["extractors_24h"] = sum(1 for e in st["extractors"] if e["state"] in ("soon", "expired"))
            tile["expired"] = sum(1 for e in st["extractors"] if e["state"] == "expired")
            tile["pickup_m3"] = round(sum(p["m3"] for p in st["pickups"]))
            tile["earned_7d"] = operate.earnings(pi, chars, 7)["net"]
        except Exception:  # noqa: BLE001 - a tile must never break the dashboard
            log.exception("PI tile")
    tile["synced_at"] = min((c.get("synced_at") or 0) for c in chars) if chars else None
    return tile


def _progress_against(plan_result: dict, chars: List[dict]) -> dict:
    """Compare a saved plan with the colonies the characters have right now."""
    have = {(c["character_id"], col["planet_id"]) for c in chars for col in c.get("colonies", [])}
    out = copy.deepcopy(plan_result)
    for col in out.get("colonies", []):
        if col.get("action") == "new" and (col.get("character_id"), col.get("planet_id")) in have:
            col["action"] = "keep"
    return out


def progress(plan_result: Optional[dict], chars: List[dict]) -> Optional[dict]:
    return operate.build_progress(_progress_against(plan_result, chars)) if plan_result else None


def first_build(ctx: dict, active: Optional[dict]) -> Optional[dict]:
    """Shopping and construction checklist for what the active plan still needs built."""
    if not active or "colonies" not in (active.get("result") or {}):
        return None
    res = active["result"]
    out = checklist.build(ctx["pi"], _progress_against(res, ctx["chars"]), ctx["chars"], ctx["books"],
                          ctx["tpl"], active.get("settings"), selling.in_delve(res.get("hub") or "", ctx["area"]),
                          operate.planet_names(ctx["area"]), area=ctx["area"])
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
                          waits: Optional[Dict[str, int]] = None) -> Dict[str, str]:
    """Read every (or one) character of the profile from ESI. Returns {name: problem} for failures.
    `waits` collects {label: seconds} for data ESI hadn't updated yet (see esi_char.esi_waits)."""
    from astracore.esi import character as esi_char
    from astracore.esi import sso
    problems: Dict[str, str] = {}
    async with ESIClient() as esi:
        for c in characters(profile_id):
            if only and c["character_id"] != only:
                continue
            if not c.get("has_token"):
                continue
            try:
                synced = await esi_char.sync_character(esi, c["character_id"])
                if waits is not None:
                    for label, seconds in synced.get("esi_waits", {}).items():
                        waits[label] = max(waits.get(label, 0), seconds)
            except sso.Transferred:
                problems[c["name"]] = "transferred to another player and removed"
            except sso.NeedsLogin:
                problems[c["name"]] = "needs a new EVE login"
            except Exception as e:  # noqa: BLE001 - report per character
                problems[c["name"]] = str(e)[:160]
            await asyncio.sleep(0)
    return problems
