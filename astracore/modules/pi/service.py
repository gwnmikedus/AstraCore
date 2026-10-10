"""AstracorePI: everything a plan needs for one profile, solving through the fair-use gate,
and the dashboard tile."""
from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Dict, List, Optional

from astracore import db
from astracore.core.solvegate import GATE, cache_key
from astracore.esi.client import ESIClient

from . import store
from .intel import richness as rich
from .intel import space as space_mod
from .module import PI_REQUIRED
from .planner import operate, optimizer, prices, selling
from .planner import skills as skills_mod
from .settings import Settings
from .static_data import dalshooth, sde_loader, voc

log = logging.getLogger("astracore")
REQUIRED_SCOPES = set(PI_REQUIRED.scopes)


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


async def market_data(pi):
    if prices.stale():
        async with ESIClient() as esi:
            await prices.refresh(esi, pi)
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
    return dict(profile_id=profile_id, s=sell_s, solve_s=solve_s, chars=chars, pi=pi, tpl=tpl, area=area,
                systems=systems, books=books, values=values, dropoff=dropoff, local=local, overrides=overrides,
                manual_overrides=manual, origin=origin, origin_jumps=origin_jumps, seller=seller,
                measured=measured, head_yield=head_yield, calibrated=cal)


def run_plan(ctx, s=None) -> dict:
    """One optimiser solve (blocking; call through GATE)."""
    s = s or ctx["solve_s"]
    res = optimizer.plan(ctx["pi"], s, ctx["area"], ctx["systems"], ctx["chars"], ctx["values"],
                         ctx["tpl"], ctx["overrides"], ctx["head_yield"])
    if "error" not in res:
        units = {x["type_id"]: x["units_per_day"] for x in res["sold"]}
        res["selling"] = selling.sell_plan(ctx["pi"], ctx["s"], ctx["books"], ctx["dropoff"], units,
                                           local=ctx["local"], origin=ctx["origin"],
                                           origin_jumps=ctx["origin_jumps"])
        res["channels"] = selling.compare_table(ctx["pi"], ctx["s"], ctx["books"], ctx["dropoff"],
                                                list(units), ctx["local"], ctx["origin"])
        res["channel_labels"] = {k: selling.LABELS[k] for k in selling.PLANNER_CHANNELS}
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
            prices.cached().get("at"), voc.routes_info().get("at"), tuple(sorted(store.admin_defaults().items())))


async def solve(profile_id: int, s: Optional[Settings] = None) -> dict:
    """Full plan for the profile with settings `s` (default: saved), cached and through the gate."""
    s = s or store.load_settings(profile_id)
    key = cache_key(data_stamp(profile_id), s.to_json(), "plan")
    ctx = await planning_context(profile_id, copy.deepcopy(s), persist_default=False) \
        if key not in GATE._cache else None
    return await GATE.cached(key, run_plan, ctx) if ctx else GATE._cache[key]


def whatif_summary(res: dict) -> dict:
    if "error" in res:
        return {"error": res["error"]}
    sp = res.get("selling") or {}
    return {"totals": res["totals"], "mix": optimizer._mix(res["colonies"]), "hub": res["hub"],
            "sell_net_per_day": sp.get("net_per_day"), "sell_net_per_cycle": sp.get("net_per_cycle"),
            "holds": sum(1 for b in sp.get("batches", []) if b.get("hold")),
            "channels": sorted({b["label"] for b in sp.get("batches", []) if not b.get("hold")}),
            "warnings": len(res.get("warnings", []))}


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


async def refresh_profile(profile_id: int, only: Optional[int] = None) -> Dict[str, str]:
    """Read every (or one) character of the profile from ESI. Returns {name: problem} for failures."""
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
                await esi_char.sync_character(esi, c["character_id"])
            except sso.Transferred:
                problems[c["name"]] = "transferred to another player and removed"
            except sso.NeedsLogin:
                problems[c["name"]] = "needs a new EVE login"
            except Exception as e:  # noqa: BLE001 - report per character
                problems[c["name"]] = str(e)[:160]
            await asyncio.sleep(0)
    return problems
