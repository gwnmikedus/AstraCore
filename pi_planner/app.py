"""FastAPI web UI: 1. Characters (EVE login) -> 2. Space -> 3. Live suggestions."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import db
import copy

from .config import REQUIRED_SCOPES, SSO_SCOPES, Settings, callback_url, effort_weights, sso_credentials
from .esi import character as esi_char
from .esi import sso
from .esi.client import ESIClient
from .intel import richness as rich
from .intel import space as space_mod
from .planner import operate, optimizer, prices, selling
from .planner import skills as skills_mod
from .static_data import dalshooth, pi_rules, sde_loader, voc

BASE = Path(__file__).parent
app = FastAPI(title="PI Planner")
templates = Jinja2Templates(directory=str(BASE / "templates"))


def _isk(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(v) >= div:
            return f"{v / div:,.1f}{unit}"
    return f"{v:,.0f}"


def _ago(ts) -> str:
    if not ts:
        return "never"
    d = time.time() - ts
    if d < 120:
        return "just now"
    if d < 7200:
        return f"{int(d // 60)} min ago"
    if d < 172800:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} days ago"


templates.env.filters["isk"] = _isk
templates.env.filters["ago"] = _ago


@app.on_event("startup")
async def startup() -> None:
    db.init()


def render(request: Request, name: str, step: int = 0, **ctx) -> HTMLResponse:
    chars = db.list_characters()
    s = db.load_settings()
    ctx.update(request=request, step=step, flash=request.query_params.get("msg"),
               has_chars=bool(chars), has_space=bool(s.selected_constellations))
    return templates.TemplateResponse(name, ctx)


def redirect(url: str, msg: Optional[str] = None) -> RedirectResponse:
    if msg:
        url += ("&" if "?" in url else "?") + "msg=" + quote(msg)
    return RedirectResponse(url, status_code=303)


# ----------------------------------------------------------------------------- shared loading
async def load_static():
    async with ESIClient() as esi:
        pi = await sde_loader.load(esi)
        tpl = await dalshooth.load(esi, pi.by_name)
    return pi, tpl


async def load_space(chars, s, force: bool = False):
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


async def planning_context(s: Optional[Settings] = None):
    """Everything a plan needs. `s` = settings to plan with (default: the saved ones)."""
    s = s or db.load_settings()
    chars = db.list_characters(enabled_only=True)
    pi, tpl = await load_static()
    area = await load_space(chars, s) if chars else None
    if area and not s.selected_constellations:
        s.selected_constellations = space_mod.default_selection(space_mod.grouped(area, chars))
        db.save_settings(s)
    systems = space_mod.selected_systems(area, s.selected_constellations) if area else {}
    books = await market_data(pi)
    cal = calibrated_yield(chars, area) if s.auto_calibrate else None
    head_yield = cal or s.head_yield_per_hour
    # planet richness: your manual overrides win, then what your own extractors measured
    measured = rich.measured_richness({c["character_id"]: c["colonies"] for c in chars}, head_yield) \
        if s.auto_calibrate else {}
    overrides = {**measured, **db.planet_overrides()}
    hub = optimizer.resolve_hub(area, s, systems, overrides) if area and systems else None
    dropoff = hub["name"] if hub else ""
    local = selling.in_delve(dropoff, area)
    origin, origin_jumps = selling.courier_origin(dropoff, area)
    seller = skills_mod.best_seller(chars)
    sell_s = skills_mod.apply(s, seller)   # taxes of the character who sells
    solve_s = copy.deepcopy(sell_s)
    solve_s.hub_system = dropoff  # values below are computed for this drop-off
    values = selling.best_values(pi, sell_s, books, dropoff, local, origin)
    return dict(s=sell_s, solve_s=solve_s, chars=chars, pi=pi, tpl=tpl, area=area, systems=systems, books=books,
                values=values, dropoff=dropoff, local=local, overrides=overrides, origin=origin,
                origin_jumps=origin_jumps, seller=seller, measured=measured,
                head_yield=head_yield, calibrated=cal)


def run_plan(ctx, s=None) -> dict:
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
        if ctx["origin"] is None and ctx["dropoff"]:
            res["warnings"].append(f"VOC doesn't pick up in {ctx['dropoff']} and no VOC pickup is reachable in your "
                                   f"space, so products that need a courier are valued at 0. Pick a drop-off "
                                   f"from {', '.join(voc.COURIER_ORIGINS)}.")
        elif ctx["origin"] != ctx["dropoff"]:
            res["warnings"].append(f"VOC doesn't pick up in {ctx['dropoff']}: courier values assume you move the "
                                   f"goods to {ctx['origin']} ({ctx['origin_jumps']} jumps) first.")
        n_measured = len([p for p in ctx["measured"] if p not in db.planet_overrides()])
        if n_measured:
            res["warnings"].append(f"Richness of {n_measured} planet(s) comes from your own extractors.")
    return res


# ----------------------------------------------------------------------------- step routing
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, code: str = "", state: str = ""):
    if code:  # EVE app registered with the site root as callback
        return await auth_callback(code, state)
    if not db.list_characters():
        return redirect("/characters")
    if not db.load_settings().selected_constellations:
        return redirect("/space")
    return redirect("/planner")


# ----------------------------------------------------------------------------- step 1: characters
@app.get("/characters", response_class=HTMLResponse)
async def characters_page(request: Request):
    chars = db.list_characters()
    pi = sde_loader.cached()
    for c in chars:
        c["colony_summary"] = []
        for col in c["colonies"]:
            prod = optimizer.existing_product(pi, col) if pi else None
            c["colony_summary"].append({
                "type": (col.get("planet_type") or "").capitalize(),
                "product": pi.name(prod) if pi and prod else "?",
            })
    for c in chars:
        c["missing_scopes"] = [x for x in REQUIRED_SCOPES if x not in c["scopes"]]
    return render(request, "characters.html", step=1, chars=chars, sso_ok=sso.configured(),
                  template_ccu=optimizer.MINER_CCU)


@app.get("/auth/login")
async def auth_login():
    if not sso.configured():
        return redirect("/characters", "The EVE application isn't configured (.env).")
    return RedirectResponse(sso.login_url())


@app.get("/auth/callback")
async def auth_callback(code: str = "", state: str = ""):
    if not code or not sso.check_state(state):
        return redirect("/characters", "Login failed or expired - try again.")
    cid, name = await sso.exchange_code(code)
    db.upsert_character(cid, name, "esi")
    try:
        async with ESIClient() as esi:
            await esi_char.sync_character(esi, cid)
        msg = f"Added {name}."
    except Exception as e:  # noqa: BLE001 - show any ESI failure to the user
        msg = f"Added {name}, but reading skills/colonies failed: {e}"
    s = db.load_settings()
    s.selected_constellations = []  # re-derive the space from the new character set
    db.save_settings(s)
    return redirect("/characters", msg)


@app.post("/characters/sync")
async def characters_sync(request: Request):
    back = (await request.form()).get("back", "/characters")
    errors = []
    async with ESIClient() as esi:
        for c in db.list_characters():
            try:
                await esi_char.sync_character(esi, c["character_id"])
            except Exception as e:  # noqa: BLE001
                errors.append(f"{c['name']}: {e}")
    return redirect(back, "Refreshed from ESI." if not errors else "Issues: " + "; ".join(errors))


@app.post("/characters/{character_id}/toggle")
async def characters_toggle(character_id: int):
    for c in db.list_characters():
        if c["character_id"] == character_id:
            db.upsert_character(character_id, c["name"], c["source"], enabled=0 if c["enabled"] else 1)
    return redirect("/characters")


@app.post("/characters/{character_id}/delete")
async def characters_delete(character_id: int):
    db.delete_character(character_id)
    return redirect("/characters", "Removed.")


# ----------------------------------------------------------------------------- step 2: space
@app.get("/space", response_class=HTMLResponse)
async def space_page(request: Request):
    chars = db.list_characters(enabled_only=True)
    if not chars:
        return redirect("/characters", "Add a character first.")
    s = db.load_settings()
    area = await load_space(chars, s)
    if not area:
        return render(request, "space.html", step=2, area=None, groups=[], s=s, sources={}, selected=[],
                      sel_systems=[])
    groups = space_mod.grouped(area, chars, db.planet_overrides())
    if not s.selected_constellations:
        s.selected_constellations = space_mod.default_selection(groups)
        db.save_settings(s)
    sel_systems = space_mod.selected_systems(area, s.selected_constellations)
    return render(request, "space.html", step=2, area=area, groups=groups, s=s,
                  sources=area.get("sources", {}), selected=s.selected_constellations,
                  sel_systems=sorted(v["name"] for v in sel_systems.values()))


@app.post("/space")
async def space_save(request: Request):
    form = await request.form()
    s = db.load_settings()
    s.selected_constellations = [int(x) for x in form.getlist("con")]
    s.hub_system = form.get("hub_system", "")
    new_extra = form.get("extra_area", "").strip()
    extra_changed = new_extra != s.extra_area
    s.extra_area = new_extra
    db.save_settings(s)
    if extra_changed or form.get("refresh"):
        chars = db.list_characters(enabled_only=True)
        await load_space(chars, s, force=bool(form.get("refresh")))
        return redirect("/space", "Space updated.")
    if not s.selected_constellations:
        return redirect("/space", "Select at least one constellation.")
    return redirect("/planner")


# ----------------------------------------------------------------------------- step 3: planner
@app.get("/planner", response_class=HTMLResponse)
async def planner_page(request: Request):
    if not db.list_characters(enabled_only=True):
        return redirect("/characters", "Add a character first.")
    ctx = await planning_context()
    s = ctx["s"]
    hubs = sorted({v["name"] for v in ctx["systems"].values()} |
                  {n for n in voc.COURIER_ORIGINS if ctx["area"] and space_mod_has(ctx["area"], n)})
    page = "planner.html" if request.query_params.get("view") == "advanced" else "guide.html"
    eligible = [c for c in ctx["chars"] if int(c.get("ccu_level", 0)) >= 2]
    return render(request, page, step=3, s=s, chars=ctx["chars"], systems=hubs,
                  prices_at=prices.cached().get("at"), calibrated=ctx["calibrated"],
                  head_yield=ctx["head_yield"], settings_json=s.to_json(), voc_hubs=voc.COURIER_ORIGINS,
                  slots=sum(int(c["slots"]) for c in eligible), n_systems=len(ctx["systems"]),
                  dropoff=ctx["dropoff"], seller=ctx["seller"])


def space_mod_has(area, name) -> bool:
    return any(v["name"] == name for v in area["systems"].values())


LIVE_FIELDS = {"effort", "max_tier", "max_systems", "max_jumps", "cycle_days", "per_planet",
               "cross_character", "hub_system", "product_blacklist", "use_buyback", "use_jita",
               "use_amarr", "use_local", "use_sell_orders", "ship_every_days"}


@app.post("/api/suggest")
async def api_suggest(request: Request):
    body = await request.json()
    s = db.load_settings()
    s.update({k: v for k, v in body.items() if k in LIVE_FIELDS})
    db.save_settings(s)
    ctx = await planning_context()
    res = await run_in_threadpool(run_plan, ctx)
    res["weights"] = effort_weights(ctx["s"].effort)
    return JSONResponse(res)


@app.post("/api/save")
async def api_save(request: Request):
    """Store answers from the guided plan without solving."""
    body = await request.json()
    s = db.load_settings()
    s.update({k: v for k, v in body.items() if k in LIVE_FIELDS})
    db.save_settings(s)
    return JSONResponse({"ok": True})


_WHATIF_CACHE: dict = {}


def _whatif_summary(res: dict) -> dict:
    if "error" in res:
        return {"error": res["error"]}
    sp = res.get("selling") or {}
    return {"totals": res["totals"], "mix": optimizer._mix(res["colonies"]), "hub": res["hub"],
            "sell_net_per_day": sp.get("net_per_day"), "sell_net_per_cycle": sp.get("net_per_cycle"),
            "holds": sum(1 for b in sp.get("batches", []) if b.get("hold")),
            "channels": sorted({b["label"] for b in sp.get("batches", []) if not b.get("hold")}),
            "warnings": len(res.get("warnings", []))}


@app.post("/api/whatif")
async def api_whatif(request: Request):
    """Plan several answers to one question side by side.
    Body: {"base": {live fields}, "options": [{"id": ..., "patch": {live fields}}, ...]}"""
    body = await request.json()
    base = db.load_settings()
    base.update({k: v for k, v in body.get("base", {}).items() if k in LIVE_FIELDS})
    stamp = (prices.cached().get("at"), tuple((c["character_id"], c.get("synced_at"), c["enabled"])
                                             for c in db.list_characters()))

    async def one(opt):
        ss = copy.deepcopy(base)
        ss.update({k: v for k, v in opt.get("patch", {}).items() if k in LIVE_FIELDS})
        key = (ss.to_json(), stamp)
        if key not in _WHATIF_CACHE:
            ctx = await planning_context(ss)
            _WHATIF_CACHE[key] = _whatif_summary(await run_in_threadpool(run_plan, ctx))
            if len(_WHATIF_CACHE) > 300:
                _WHATIF_CACHE.pop(next(iter(_WHATIF_CACHE)))
        return {"id": opt.get("id"), **_WHATIF_CACHE[key]}

    return JSONResponse(await asyncio.gather(*[one(o) for o in body.get("options", [])]))


@app.post("/api/alternatives")
async def api_alternatives():
    ctx = await planning_context()
    alts = await run_in_threadpool(optimizer.alternatives, ctx["pi"], ctx["solve_s"], ctx["area"], ctx["systems"],
                                   ctx["chars"], ctx["values"], ctx["tpl"], ctx["overrides"], ctx["head_yield"])
    return JSONResponse(alts)


@app.post("/api/sensitivity")
async def api_sensitivity():
    ctx = await planning_context()
    rows = await run_in_threadpool(optimizer.yield_sensitivity, ctx["pi"], ctx["solve_s"], ctx["area"],
                                   ctx["systems"], ctx["chars"], ctx["values"], ctx["tpl"], ctx["overrides"],
                                   ctx["head_yield"])
    return JSONResponse({"calibrated": bool(ctx["calibrated"]), "rows": rows})


@app.post("/api/prices/refresh")
async def api_prices_refresh():
    pi, _ = await load_static()
    async with ESIClient() as esi:
        await prices.refresh(esi, pi)
    await voc.refresh_routes()
    return JSONResponse({"ok": True, "at": prices.cached().get("at")})


# ----------------------------------------------------------------------------- step 4: operate
@app.get("/operate", response_class=HTMLResponse)
async def operate_page(request: Request):
    if not db.list_characters(enabled_only=True):
        return redirect("/characters", "Add a character first.")
    ctx = await planning_context()
    chars = ctx["chars"]
    plan = await run_in_threadpool(run_plan, ctx)
    days = int(request.query_params.get("days", 7))
    missing = [c["name"] for c in chars if any(x not in c["scopes"] for x in REQUIRED_SCOPES)]
    return render(request, "operate.html", step=4, chars=chars,
                  status=operate.colonies_status(ctx["pi"], chars, ctx["area"]),
                  stock=operate.hangar_stock(ctx["pi"], ctx["s"], ctx["books"], chars, ctx["area"]),
                  pipe=operate.pipeline(ctx["pi"], ctx["books"], chars),
                  earned=operate.earnings(ctx["pi"], chars, days), days=days,
                  progress=operate.build_progress(plan), plan=plan, missing=missing,
                  synced=min((c.get("synced_at") or 0) for c in chars), buyback_site=voc.BUYBACK_SITE,
                  voc_site=voc.SITE)


# ----------------------------------------------------------------------------- exports
async def _current_plan():
    ctx = await planning_context()
    return await run_in_threadpool(run_plan, ctx)


@app.get("/export/templates.zip")
async def export_templates():
    res = await _current_plan()
    return Response(dalshooth.zip_pack(res.get("templates_needed", [])), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="pi-templates.zip"'})


@app.get("/export/plan.md")
async def export_md():
    res = await _current_plan()
    if "error" in res:
        return Response(res["error"], status_code=400)
    t = res["totals"]
    out = ["# PI plan", "",
           f"Hub **{res['hub']}** · {t['colonies']}/{t['slots_total']} colonies · "
           f"**{_isk(t['isk_per_day'])} ISK/day** ({_isk(t['isk_per_week'])}/week) · "
           f"{t['m3_per_week']:,} m³/week · {t['systems']} systems", ""]
    for ch in res["characters"]:
        out += [f"## {ch['name']} ({ch['used']}/{ch['slots']})", ""]
        if ch.get("route"):
            out += ["Route: " + " → ".join(ch["route"]["order"]), ""]
        out += ["| Planet | Template | Product/day | ISK/day | Action |", "|---|---|---|---|---|"]
        for c in res["colonies"]:
            if c["character_id"] == ch["character_id"]:
                outs = ", ".join(f"{k} {v:,.0f}" for k, v in c["out_per_day"].items())
                out.append(f"| {c['planet']} ({c['planet_type']}) | {c['template']} | {outs} "
                           f"| {_isk(c['value_per_day'])} | {c['action']} |")
        out.append("")
    sp = res.get("selling")
    if sp:
        out += [f"## How you get paid (every {sp['every_days']:.0f} days from {sp['dropoff']})", ""]
        for b in sp["batches"]:
            items = ", ".join(f"{v:,.0f} {k}" for k, v in b["items"].items())
            line = f"- **{b['label']}**: {items} ({b['m3']:,} m³) - " + ("hold" if b.get("hold") else f"≈ {_isk(b['net'])} net")
            c = b.get("contract") or {}
            if c.get("type") == "Courier":
                line += (f" - Courier, private to {c['assign_to']}, {c['from']} → {c['to']}, "
                         f"reward {c['reward']:,}, collateral {c['collateral']:,}")
            out.append(line)
        out.append("")
    if res["transfers"]:
        out += ["## Transfers between characters", ""]
        out += [f"- {x['from']} → {x['to']}: {x['units_per_day']:,.0f} {x['item']}/day" for x in res["transfers"]]
    if res["removals"]:
        out += ["", "## Remove", ""]
        out += [f"- {x['character']}: planet {x['planet_id']} ({x['current']})" for x in res["removals"]]
    return Response("\n".join(out), media_type="text/markdown",
                    headers={"Content-Disposition": 'attachment; filename="pi-plan.md"'})


@app.get("/export/plan.csv")
async def export_csv():
    res = await _current_plan()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["character", "system", "planet", "planet_type", "template", "product", "out_per_day",
                "in_per_day", "isk_per_day", "m3_per_week", "action"])
    for c in res.get("colonies", []):
        w.writerow([c["character"], c["system"], c["planet"], c["planet_type"], c["template"], c["product"],
                    json.dumps(c["out_per_day"]), json.dumps(c["in_per_day"]), c["value_per_day"],
                    c["m3_per_week"], c["action"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="pi-plan.csv"'})


# ----------------------------------------------------------------------------- settings
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    s = db.load_settings()
    chars = db.list_characters(enabled_only=True)
    area = await load_space(chars, s) if chars else None
    cid, _ = sso_credentials()
    cal = calibrated_yield(chars, area) if chars else None
    measured = rich.measured_richness({c["character_id"]: c["colonies"] for c in chars}, cal) if cal else {}
    return render(request, "settings.html", s=s, client_id=cid, callback=callback_url(), scopes=SSO_SCOPES,
                  calibrated=cal, measured=measured,
                  rates=[skills_mod.character_rates(c) for c in chars if c.get("skills")],
                  seller=skills_mod.best_seller(chars), poco=skills_mod.customs_rates(chars),
                  routes=voc.routes_cached(), routes_info=voc.routes_info(), voc_site=voc.SITE)


@app.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    data = dict(form)
    data["__bool_fields__"] = form.getlist("__bool_fields__")
    s = db.load_settings()
    s.update(data)
    db.save_settings(s)
    return redirect("/settings", "Saved.")
