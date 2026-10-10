"""AstracorePI pages and API, all under /pi and all scoped to the signed-in profile.

/pi            -> lands on the right page (connect characters / Area / Plan / Operate)
/pi/operate    -> the daily screen
/pi/plan       -> the guided wizard (?view=advanced: every option on one screen)
/pi/area       -> constellations and drop-off
/pi/settings   -> economics and yield
/pi/api/...    -> JSON for the wizard and the advanced view (CSRF header required)
/pi/export/... -> templates zip, plan .md / .csv
"""
from __future__ import annotations

import copy
import csv
import io
import json
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from astracore import db
from astracore.core import fmt
from astracore.core.auth import bundle_active
from astracore.core.sessions import require_user
from astracore.core.solvegate import GATE, Busy, Superseded, cache_key
from astracore.core.web import redirect
from astracore.core.web import render as core_render
from astracore.esi import sso
from astracore.esi.client import ESI_BASE

from . import service, store
from .intel import space as space_mod
from .module import MODULE
from .planner import operate, optimizer, prices
from .planner import skills as skills_mod
from .settings import ADMIN_FIELDS, Settings, effort_weights
from .static_data import dalshooth, voc

router = APIRouter(prefix="/pi", dependencies=[Depends(require_user)])
legacy = APIRouter()     # old MVP paths -> 301 (one release)
PRICE_REFRESH_EVERY = 600

LIVE_FIELDS = {"effort", "max_tier", "max_systems", "max_jumps", "cycle_days", "per_planet",
               "cross_character", "hub_system", "product_blacklist", "use_buyback", "use_jita",
               "use_amarr", "use_local", "use_sell_orders", "ship_every_days", "hour_isk", "guide_step",
               "answered", "selected_constellations", "extra_area"}


def render(request: Request, name: str, page: str, title: str, **ctx) -> HTMLResponse:
    return core_render(request, f"pi/{name}", module_id="pi", page=page, page_title=title, **ctx)


def _pid(request: Request) -> int:
    return request.state.user["id"]


def busy_response() -> JSONResponse:
    return JSONResponse({"busy": True, "retry_after": 3,
                         "error": "Astracore is busy, your plan is queued."}, status_code=503)


def superseded_response() -> JSONResponse:
    return JSONResponse({"superseded": True}, status_code=409)


# ----------------------------------------------------------------------------- entry
@router.get("", response_class=HTMLResponse)
async def entry(request: Request):
    pid = _pid(request)
    state = service.entry_state(pid)
    if state == "connect":
        chars = service.characters(pid)
        return render(request, "connect.html", "connect", "Connect characters", chars=chars,
                      bundle=MODULE.required_bundle)
    return RedirectResponse({"area": "/pi/area", "plan": "/pi/plan", "operate": "/pi/operate"}[state], status_code=303)


# ----------------------------------------------------------------------------- characters in PI
@router.post("/characters/{character_id}/toggle")
async def characters_toggle(request: Request, character_id: int):
    pid = _pid(request)
    ch = db.owned_character(pid, character_id)
    if ch:
        db.set_character(character_id, enabled=0 if ch["enabled"] else 1)
    form = await request.form()
    return redirect(form.get("back") or "/pi/plan")


def character_panel(pid: int) -> list:
    """Characters in this plan: include/exclude, slots, CCU and what it allows, colonies, login state."""
    pi = None
    try:
        from .static_data import sde_loader
        pi = sde_loader.cached()
    except Exception:  # noqa: BLE001
        pass
    out = []
    for c in service.characters(pid):
        lvl = int(c.get("ccu_level") or 0)
        if lvl >= 5:
            ccu = ("ok", "OK for every template")
        elif lvl >= optimizer.MINER_CCU:
            ccu = ("ok", "Nullsec miners and factories (lowsec miners need 5)")
        elif lvl >= 2:
            ccu = ("warn", "Factories only")
        else:
            ccu = ("bad", "Too low for any template")
        products = []
        for col in c.get("colonies", []):
            prod = optimizer.existing_product(pi, col) if pi else None
            products.append(f"{(col.get('planet_type') or '').capitalize()} · {pi.name(prod) if pi and prod else '?'}")
        out.append({**c, "ccu_note": ccu, "colony_summary": products, "pi_ready": service.pi_ready(c),
                    "missing_pi": not set(MODULE.required_bundle.scopes) <= set(c.get("scopes") or [])})
    return out


# ----------------------------------------------------------------------------- area
@router.get("/area", response_class=HTMLResponse)
async def area_page(request: Request):
    pid = _pid(request)
    chars = service.planning_characters(pid)
    if not chars:
        return redirect("/pi", "Connect a character first.")
    s = store.load_settings(pid)
    area = await service.load_space(chars, s)
    if not area:
        return render(request, "space.html", "area", "Area", area=None, groups=[], s=s, sources={}, selected=[],
                      sel_systems=[])
    groups = space_mod.grouped(area, chars, store.planet_overrides(pid))
    if not s.selected_constellations:
        s.selected_constellations = space_mod.default_selection(groups)
        store.save_settings(pid, s)
    sel_systems = space_mod.selected_systems(area, s.selected_constellations)
    return render(request, "space.html", "area", "Area", area=area, groups=groups, s=s,
                  sources=area.get("sources", {}), selected=s.selected_constellations,
                  sel_systems=sorted(v["name"] for v in sel_systems.values()),
                  voc_hubs=voc.COURIER_ORIGINS)


@router.post("/area")
async def area_save(request: Request):
    pid = _pid(request)
    form = await request.form()
    s = store.load_settings(pid)
    s.selected_constellations = [int(x) for x in form.getlist("con")]
    s.hub_system = form.get("hub_system", "")
    new_extra = form.get("extra_area", "").strip()
    extra_changed = new_extra != s.extra_area
    s.extra_area = new_extra
    store.save_settings(pid, s)
    if extra_changed or form.get("refresh"):
        await service.load_space(service.planning_characters(pid), s, force=bool(form.get("refresh")))
        return redirect("/pi/area", "Area updated.")
    if not s.selected_constellations:
        return redirect("/pi/area", "Select at least one constellation.", "warn")
    return redirect(form.get("next") or "/pi/plan")


@router.get("/api/area")
async def api_area(request: Request):
    """Constellations + drop-off choices for the wizard's Area step (Advanced expander)."""
    pid = _pid(request)
    chars = service.planning_characters(pid)
    s = store.load_settings(pid)
    area = await service.load_space(chars, s) if chars else None
    if not area:
        return JSONResponse({"groups": [], "selected": [], "systems": []})
    groups = space_mod.grouped(area, chars, store.planet_overrides(pid))
    selected = s.selected_constellations or space_mod.default_selection(groups)
    cons = [{"id": c["id"], "name": c["name"], "region": r["name"], "systems": len(c["systems"]),
             "score": c["score"], "has_colonies": c["has_colonies"], "sec": [c["sec_max"], c["sec_min"]]}
            for r in groups for c in r["constellations"]]
    names = sorted({v["name"] for v in space_mod.selected_systems(area, selected).values()}
                   | {n for n in voc.COURIER_ORIGINS if space_mod_has(area, n)})
    return JSONResponse({"constellations": cons, "selected": selected, "systems": names,
                         "hub_system": s.hub_system, "voc": voc.COURIER_ORIGINS})


def space_mod_has(area, name) -> bool:
    return any(v["name"] == name for v in area["systems"].values())


# ----------------------------------------------------------------------------- plan
@router.get("/plan", response_class=HTMLResponse)
async def plan_page(request: Request):
    pid = _pid(request)
    if not service.planning_characters(pid):
        return redirect("/pi", "Connect a character first.")
    ctx = await service.planning_context(pid)
    s = ctx["s"]
    hubs = sorted({v["name"] for v in ctx["systems"].values()} |
                  {n for n in voc.COURIER_ORIGINS if ctx["area"] and space_mod_has(ctx["area"], n)})
    advanced = request.query_params.get("view") == "advanced"
    page = "planner.html" if advanced else "guide.html"
    eligible = [c for c in ctx["chars"] if int(c.get("ccu_level", 0)) >= 2]
    first_visit = not store.has_settings(pid) or not s.answered
    return render(request, page, page[:-5], "Plan", s=s, chars=ctx["chars"], systems=hubs,
                  prices_at=prices.cached().get("at"), calibrated=ctx["calibrated"],
                  head_yield=ctx["head_yield"], settings_json=s.to_json(), voc_hubs=voc.COURIER_ORIGINS,
                  slots=sum(int(c["slots"]) for c in eligible), n_systems=len(ctx["systems"]),
                  dropoff=ctx["dropoff"], seller=ctx["seller"], api="/pi/api", export="/pi/export",
                  settings_url="/pi/settings", operate_url="/pi/operate", advanced_url="/pi/plan?view=advanced",
                  guided_url="/pi/plan", first_visit=first_visit, panel=character_panel(pid),
                  plans=store.list_plan_runs(pid), waypoints=_waypoint_chars(pid))


def _waypoint_chars(pid: int) -> list:
    return [{"character_id": c["character_id"], "name": c["name"]} for c in service.characters(pid)
            if bundle_active(c, "pi.optional.waypoints")]


def _apply(s: Settings, body: dict) -> Settings:
    s.update({k: v for k, v in body.items() if k in LIVE_FIELDS})
    return s


@router.post("/api/suggest")
async def api_suggest(request: Request):
    pid = _pid(request)
    body = await request.json()
    s = _apply(store.load_settings(pid), body)
    store.save_settings(pid, s)
    try:
        async with GATE.request(pid, "suggest"):
            res = copy.deepcopy(await service.solve(pid, s))
    except Busy:
        return busy_response()
    except Superseded:
        return superseded_response()
    res["weights"] = effort_weights(s.effort)
    return JSONResponse(res)


@router.post("/api/save")
async def api_save(request: Request):
    """Store wizard answers without solving. Only the fields sent are changed."""
    pid = _pid(request)
    body = await request.json()
    s = _apply(store.load_settings(pid), body)
    store.save_settings(pid, s)
    return JSONResponse({"ok": True})


@router.post("/api/whatif")
async def api_whatif(request: Request):
    """Plan several answers to one question side by side.
    Body: {"base": {live fields}, "options": [{"id": ..., "patch": {live fields}}, ...]}"""
    pid = _pid(request)
    body = await request.json()
    base = _apply(store.load_settings(pid), body.get("base", {}))
    stamp = service.data_stamp(pid)

    async def one(opt):
        ss = copy.deepcopy(base)
        ss.update({k: v for k, v in opt.get("patch", {}).items() if k in LIVE_FIELDS})
        key = cache_key(stamp, ss.to_json(), "whatif")
        if key in GATE._cache:
            return {"id": opt.get("id"), **GATE._cache[key]}
        ctx = await service.planning_context(pid, ss, persist_default=False)
        res = await GATE.cached(key, lambda: service.whatif_summary(service.run_plan(ctx)))
        return {"id": opt.get("id"), **res}

    import asyncio
    try:
        async with GATE.request(pid, "whatif"):
            rows = await asyncio.gather(*[one(o) for o in body.get("options", [])[:6]])
    except Busy:
        return busy_response()
    except Superseded:
        return superseded_response()
    return JSONResponse(list(rows))


@router.post("/api/alternatives")
async def api_alternatives(request: Request):
    pid = _pid(request)
    try:
        async with GATE.request(pid, "alternatives"):
            ctx = await service.planning_context(pid)
            key = cache_key(service.data_stamp(pid), ctx["solve_s"].to_json(), "alternatives")
            alts = await GATE.cached(key, optimizer.alternatives, ctx["pi"], ctx["solve_s"], ctx["area"],
                                     ctx["systems"], ctx["chars"], ctx["values"], ctx["tpl"], ctx["overrides"],
                                     ctx["head_yield"])
    except Busy:
        return busy_response()
    except Superseded:
        return superseded_response()
    return JSONResponse(alts)


@router.post("/api/sensitivity")
async def api_sensitivity(request: Request):
    pid = _pid(request)
    try:
        async with GATE.request(pid, "sensitivity"):
            ctx = await service.planning_context(pid)
            key = cache_key(service.data_stamp(pid), ctx["solve_s"].to_json(), "sensitivity")
            rows = await GATE.cached(key, optimizer.yield_sensitivity, ctx["pi"], ctx["solve_s"], ctx["area"],
                                     ctx["systems"], ctx["chars"], ctx["values"], ctx["tpl"], ctx["overrides"],
                                     ctx["head_yield"])
    except Busy:
        return busy_response()
    except Superseded:
        return superseded_response()
    return JSONResponse({"calibrated": bool(ctx["calibrated"]), "rows": rows})


@router.post("/api/prices/refresh")
async def api_prices_refresh(request: Request):
    """Market prices are shared by everyone: refreshed at most every 10 minutes."""
    import time as _t
    at = prices.cached().get("at") or 0
    if _t.time() - at < PRICE_REFRESH_EVERY:
        return JSONResponse({"ok": True, "at": at, "note": "Prices are less than 10 minutes old."})
    pi, _ = await service.load_static()
    from astracore.esi.client import ESIClient
    async with ESIClient() as esi:
        await prices.refresh(esi, pi)
    await voc.refresh_routes()
    return JSONResponse({"ok": True, "at": prices.cached().get("at")})


# ----------------------------------------------------------------------------- saved plans
@router.post("/api/plans")
async def api_plan_save(request: Request):
    """Save the plan for the current settings. Body: {label, active}."""
    pid = _pid(request)
    body = await request.json()
    s = store.load_settings(pid)
    try:
        async with GATE.request(pid, "save-plan"):
            res = await service.solve(pid, s)
    except Busy:
        return busy_response()
    except Superseded:
        return superseded_response()
    if "error" in res:
        return JSONResponse({"error": res["error"]}, status_code=400)
    label = (body.get("label") or "").strip() or f"Plan {len(store.list_plan_runs(pid)) + 1}"
    active = bool(body.get("active")) or not store.active_plan(pid)
    rid = store.save_plan_run(pid, label, s, res, active=active)
    return JSONResponse({"ok": True, "id": rid, "label": label, "active": active,
                         "plans": store.list_plan_runs(pid)})


@router.post("/api/plans/{run_id}/activate")
async def api_plan_activate(request: Request, run_id: int):
    pid = _pid(request)
    if not store.set_active_plan(pid, run_id):
        return JSONResponse({"error": "Unknown plan."}, status_code=404)
    return JSONResponse({"ok": True, "plans": store.list_plan_runs(pid)})


@router.post("/plans/{run_id}/activate")
async def plan_activate(request: Request, run_id: int):
    ok = store.set_active_plan(_pid(request), run_id)
    return redirect("/pi/operate", "Active plan changed." if ok else "Unknown plan.")


@router.post("/plans/{run_id}/delete")
async def plan_delete(request: Request, run_id: int):
    ok = store.delete_plan_run(_pid(request), run_id)
    form = await request.form()
    return redirect(form.get("back") or "/pi/plan", "Plan deleted." if ok else "Unknown plan.")


# ----------------------------------------------------------------------------- waypoints (opt-in bundle)
@router.post("/api/waypoints")
async def api_waypoints(request: Request):
    """Send a route to the character's running EVE client. Needs the pi.optional.waypoints bundle."""
    pid = _pid(request)
    body = await request.json()
    ch = db.owned_character(pid, int(body.get("character_id") or 0))
    if not ch or not bundle_active(ch, "pi.optional.waypoints"):
        return JSONResponse({"error": "Turn on \"Send routes to your EVE client\" for this character on your profile."},
                            status_code=403)
    names = [str(x) for x in body.get("systems", [])][:30]
    s = store.load_settings(pid)
    area = await service.load_space(service.planning_characters(pid), s)
    ids = []
    for n in names:
        sysrow = space_mod.area_mod.system_by_name(area, n) if area else None
        if sysrow:
            ids.append(sysrow["system_id"])
    if not ids:
        return JSONResponse({"error": "No known systems in that route."}, status_code=400)
    try:
        token = await sso.access_token(ch["character_id"])
    except sso.SSOError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    async with httpx.AsyncClient(timeout=15) as c:
        for i, sid in enumerate(ids):
            r = await c.post(f"{ESI_BASE}/ui/autopilot/waypoint/", params={
                "destination_id": sid, "add_to_beginning": "false", "clear_other_waypoints": "true" if i == 0 else "false"},
                headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                return JSONResponse({"error": f"EVE refused the waypoint ({r.status_code}). Is {ch['name']} online?"},
                                    status_code=502)
    return JSONResponse({"ok": True, "sent": len(ids), "character": ch["name"]})


# ----------------------------------------------------------------------------- operate
@router.get("/operate", response_class=HTMLResponse)
async def operate_page(request: Request):
    pid = _pid(request)
    if not service.planning_characters(pid):
        return redirect("/pi", "Connect a character first.")
    ctx = await service.planning_context(pid)
    chars = ctx["chars"]
    active = store.active_plan(pid)
    plan = active["result"] if active else None
    days = 30 if request.query_params.get("days") == "30" else 7
    missing = [c["name"] for c in chars if not service.pi_ready(c)]
    stock = operate.hangar_stock(ctx["pi"], ctx["s"], ctx["books"], chars, ctx["area"])
    return render(request, "operate.html", "operate", "Operate", chars=chars,
                  status=operate.colonies_status(ctx["pi"], chars, ctx["area"]),
                  stock=stock, consolidated=operate.consolidate(stock, ctx["area"]),
                  pipe=operate.pipeline(ctx["pi"], ctx["books"], chars),
                  earned=operate.earnings(ctx["pi"], chars, days), days=days,
                  progress=service.progress(plan, chars), plan=plan, active=active, missing=missing,
                  plans=store.list_plan_runs(pid),
                  synced=min((c.get("synced_at") or 0) for c in chars), buyback_site=voc.BUYBACK_SITE,
                  voc_site=voc.SITE, waypoints=_waypoint_chars(pid))


# ----------------------------------------------------------------------------- exports
async def _export_plan(request: Request) -> dict:
    pid = _pid(request)
    run = request.query_params.get("plan")
    if run and run.isdigit():
        saved = store.get_plan_run(pid, int(run))
        if saved:
            return saved["result"]
    if request.query_params.get("current") != "1":
        active = store.active_plan(pid)
        if active:
            return active["result"]
    async with GATE.request(pid, "export"):
        return await service.solve(pid)


@router.get("/export/templates.zip")
async def export_templates(request: Request):
    try:
        res = await _export_plan(request)
    except (Busy, Superseded):
        return Response("Astracore is busy. Try again in a moment.", status_code=503)
    return Response(dalshooth.zip_pack(res.get("templates_needed", [])), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-templates.zip"'})


@router.get("/export/plan.md")
async def export_md(request: Request):
    try:
        res = await _export_plan(request)
    except (Busy, Superseded):
        return Response("Astracore is busy. Try again in a moment.", status_code=503)
    if "error" in res:
        return Response(res["error"], status_code=400)
    t = res["totals"]
    out = ["# AstracorePI plan", "",
           f"Drop-off **{res['hub']}** · {t['colonies']}/{t['slots_total']} colonies · "
           f"**{fmt.isk(t['isk_per_day'])} ISK/day** ({fmt.isk(t['isk_per_week'])}/week) · "
           f"{fmt.m3(t['m3_per_week'])}/week · {t['systems']} systems", ""]
    for ch in res["characters"]:
        out += [f"## {ch['name']} ({ch['used']}/{ch['slots']})", ""]
        if ch.get("route"):
            out += ["Route: " + " → ".join(ch["route"]["order"]), ""]
        out += ["| Planet | Template | Product/day | ISK/day | Action |", "|---|---|---|---|---|"]
        for c in res["colonies"]:
            if c["character_id"] == ch["character_id"]:
                outs = ", ".join(f"{k} {fmt.num(v)}" for k, v in c["out_per_day"].items())
                out.append(f"| {c['planet']} ({c['planet_type']}) | {c['template']} | {outs} "
                           f"| {fmt.isk(c['value_per_day'])} | {c['action']} |")
        out.append("")
    sp = res.get("selling")
    if sp:
        out += [f"## How you get paid (every {fmt.num(sp['every_days'])} days from {sp['dropoff']})", ""]
        for b in sp["batches"]:
            items = ", ".join(f"{fmt.num(v)} {k}" for k, v in b["items"].items())
            line = f"- **{b['label']}**: {items} ({fmt.m3(b['m3'])}) - " + ("hold" if b.get("hold") else f"≈ {fmt.isk(b['net'])} net")
            c = b.get("contract") or {}
            if c.get("type") == "Courier":
                line += (f" - Courier, private to {c['assign_to']}, {c['from']} → {c['to']}, "
                         f"reward {fmt.num(c['reward'])}, collateral {fmt.num(c['collateral'])}")
            out.append(line)
        out.append("")
    if res.get("transfers"):
        out += ["## Transfers between characters", ""]
        out += [f"- {x['from']} → {x['to']}: {fmt.num(x['units_per_day'])} {x['item']}/day" for x in res["transfers"]]
    if res.get("removals"):
        out += ["", "## Remove", ""]
        out += [f"- {x['character']}: planet {x['planet_id']} ({x['current']})" for x in res["removals"]]
    return Response("\n".join(out), media_type="text/markdown",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-plan.md"'})


@router.get("/export/plan.csv")
async def export_csv(request: Request):
    try:
        res = await _export_plan(request)
    except (Busy, Superseded):
        return Response("Astracore is busy. Try again in a moment.", status_code=503)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["character", "system", "planet", "planet_type", "template", "product", "out_per_day",
                "in_per_day", "isk_per_day", "m3_per_week", "action"])
    for c in res.get("colonies", []):
        w.writerow([c["character"], c["system"], c["planet"], c["planet_type"], c["template"], c["product"],
                    json.dumps(c["out_per_day"]), json.dumps(c["in_per_day"]), c["value_per_day"],
                    c["m3_per_week"], c["action"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-plan.csv"'})


# ----------------------------------------------------------------------------- settings
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    pid = _pid(request)
    s = store.load_settings(pid)
    chars = service.planning_characters(pid)
    area = await service.load_space(chars, s) if chars else None
    cal = service.calibrated_yield(chars, area) if chars else None
    from .intel import richness as rich
    measured = rich.measured_richness({c["character_id"]: c["colonies"] for c in chars}, cal) if cal else {}
    customs_on = [c["name"] for c in service.characters(pid) if bundle_active(c, "pi.optional.customs")]
    return render(request, "settings.html", "settings", "Settings", s=s, calibrated=cal, measured=measured,
                  rates=[skills_mod.character_rates(c) for c in chars if c.get("skills")],
                  seller=skills_mod.best_seller(chars), poco=skills_mod.customs_rates(chars),
                  routes=voc.routes_cached(), routes_info=voc.routes_info(), voc_site=voc.SITE,
                  customs_on=customs_on, is_admin=request.state.user.get("is_admin"))


@router.post("/settings")
async def settings_save(request: Request):
    pid = _pid(request)
    form = await request.form()
    data = {k: v for k, v in form.items() if k not in ADMIN_FIELDS and k != "csrf_token"}
    data["__bool_fields__"] = form.getlist("__bool_fields__")
    s = store.load_settings(pid)
    s.update(data)
    store.save_settings(pid, s)
    return redirect("/pi/settings", "Saved.")


@router.post("/reset")
async def reset_pi(request: Request):
    store.reset_profile(_pid(request))
    return redirect("/profile", "AstracorePI was reset: settings, plans and planet overrides are gone. "
                                "Your characters are still linked.")


# ----------------------------------------------------------------------------- old MVP paths (301, one release)
_OLD = {"/space": "/pi/area", "/planner": "/pi/plan", "/operate": "/pi/operate", "/settings": "/pi/settings",
        "/characters": "/profile", "/export/templates.zip": "/pi/export/templates.zip",
        "/export/plan.md": "/pi/export/plan.md", "/export/plan.csv": "/pi/export/plan.csv"}


def _legacy(to: str):
    async def handler(request: Request):
        q = request.url.query
        return RedirectResponse(to + (f"?{q}" if q else ""), status_code=301)
    return handler


for _old, _new in _OLD.items():
    legacy.add_api_route(_old, _legacy(_new), methods=["GET"], include_in_schema=False)
