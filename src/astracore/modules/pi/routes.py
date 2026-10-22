"""AstracorePI pages and API, all under /pi and all scoped to the signed-in profile.

/pi            -> lands on the right page (connect characters / Plan / Operate)
/pi/operate    -> the daily screen
/pi/plan       -> the guided wizard (?view=advanced: every option on one screen)
/pi/area       -> constellations and drop-off
/pi/settings   -> economics and yield
/pi/glossary   -> plain-English PI terms, linked from the "?" answers
/pi/api/...    -> JSON for the wizard and the advanced view (CSRF header required)
/pi/export/... -> templates zip, plan .md / .csv, first-build shopping .csv
"""
from __future__ import annotations

import copy
import csv
import asyncio
import io
import json
import logging
import math
from collections import defaultdict
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from astracore import db
from astracore.core import fmt, freshness
from astracore.core.registry import SCOPE_TEXT
from astracore.core.auth import bundle_active
from astracore.core.sessions import require_user
from astracore.core.solvegate import GATE, Busy, Skipped, Superseded, cache_key
from astracore.core.web import redirect
from astracore.core.web import render as core_render
from astracore.esi import errors as esi_errors
from astracore.esi import sso
from astracore.esi.client import ESI_BASE, default_headers

from . import glossary, service, store
from .intel import space as space_mod
from .module import MODULE
from .planner import compare, nextup, operate, optimizer, prices, selling, setups
from .planner import skills as skills_mod
from .settings import ADMIN_FIELDS, HOUR_DEFAULTS, TEXT_LIMITS, Settings, time_weights
from .static_data import dalshooth, sde_loader, voc

log = logging.getLogger("astracore")
router = APIRouter(prefix="/pi", dependencies=[Depends(require_user)])
legacy = APIRouter()     # old MVP paths -> 301, so old bookmarks keep working
PRICE_REFRESH_EVERY = 600

LIVE_FIELDS = {"effort", "max_tier", "max_systems", "max_jumps", "cycle_days", "per_planet",
               "cross_character", "cross_character_set", "hub_system", "product_blacklist", "use_buyback", "use_jita",
               "use_amarr", "use_local", "use_self_haul", "use_sell_orders", "ship_every_days", "hour_isk", "guide_step",
               "buy_inputs", "input_budget_isk",
               "answered", "selected_constellations", "extra_area"}


def render(request: Request, name: str, page: str, title: str, **ctx) -> HTMLResponse:
    return core_render(request, f"pi/{name}", module_id="pi", page=page, page_title=title,
                       template_repo=dalshooth.REPO_URL, **ctx)


def _pid(request: Request) -> int:
    return request.state.user["id"]


def busy_response() -> JSONResponse:
    return JSONResponse({"busy": True, "retry_after": 3,
                         "error": "AstraCore is busy, your plan is queued."}, status_code=503)


def superseded_response() -> JSONResponse:
    return JSONResponse({"superseded": True}, status_code=409)


# ----------------------------------------------------------------------------- entry
@router.get("", response_class=HTMLResponse)
async def entry(request: Request, rhythm: str = ""):
    pid = _pid(request)
    store.apply_preview_goal(pid, rhythm)
    if not request.state.user.get("onboarded"):   # a plain visit reads only: write just the first time
        db.update_profile(pid, onboarded=1)
    state = service.entry_state(pid)
    if state == "connect":
        chars = service.characters(pid)
        return render(request, "connect.html", "connect", "Connect characters", chars=chars,
                      bundle=MODULE.required_bundle, scope_text=SCOPE_TEXT)
    if state == "excluded":   # Area/Plan/Operate need an included character: never bounce back to them
        return render(request, "excluded.html", "connect", "Characters in this plan", panel=character_panel(pid),
                      open_panel=True)
    return RedirectResponse({"plan": "/pi/plan", "operate": "/pi/operate"}[state], status_code=303)


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
        note = setups.ccu_note(c.get("ccu_level"))
        ccu = (note["status"], note["label"], note["next"])
        products = []
        for col in c.get("colonies", []):
            prod = optimizer.existing_product(pi, col) if pi else None
            products.append({"type": (col.get("planet_type") or "").capitalize(),
                             "product": pi.name(prod) if pi and prod else "?"})
        out.append({**c, "ccu_note": ccu, "colony_summary": products, "pi_ready": service.pi_ready(c),
                    "blocked": bool(c.get("enabled")) and not setups.can_plan(c),
                    "missing_pi": not set(MODULE.required_bundle.scopes) <= set(c.get("scopes") or [])})
    return out


# ----------------------------------------------------------------------------- area
@router.get("/area", response_class=HTMLResponse)
async def area_page(request: Request):
    pid = _pid(request)
    chars = service.planning_characters(pid)
    if not chars:
        return redirect("/pi")   # /pi says why: connect, or include one
    s = store.load_settings(pid)
    outage = esi_errors.Outage()
    area = await service.load_space(chars, s, outage=outage)
    banner = outage.banner(c.get("synced_at") for c in chars)
    if not area:
        return render(request, "space.html", "area", "Area", area=None, groups=[], s=s, sources={}, selected=[],
                      sel_systems=[], esi_outage=banner)
    groups = space_mod.grouped(area, chars, store.planet_overrides(pid))
    if not s.selected_constellations:
        s.selected_constellations = space_mod.default_selection(groups)
    sel_systems = space_mod.selected_systems(area, s.selected_constellations)
    overrides = store.planet_overrides(pid)
    names = {p["planet_id"]: p["name"] for v in area["systems"].values() for p in v["planets"]}
    scan_systems = [{"name": v["name"], "planets": sorted(
        (p for p in v["planets"] if p["type"] not in ("Shattered", "Unknown")), key=lambda p: p["name"])}
        for v in sorted(area["systems"].values(), key=lambda v: v["name"])]
    measured = _measured_richness(chars, area, s)
    return render(request, "space.html", "area", "Area", area=area, groups=groups, s=s,
                  sources=area.get("sources", {}), selected=s.selected_constellations,
                  sel_systems=sorted(v["name"] for v in sel_systems.values()),
                  voc_hubs=voc.COURIER_ORIGINS,
                  scan_systems=[v for v in scan_systems if v["planets"]], richness_labels=RICHNESS_LABELS,
                  overrides=[{"planet_id": k, "name": names.get(k, str(k)), "richness": v,
                              "label": richness_label(v)} for k, v in overrides.items()],
                  measured=[{"planet_id": k, "name": names.get(k, str(k)), "richness": v}
                            for k, v in sorted(measured.items(), key=lambda kv: names.get(kv[0], str(kv[0])))
                            if k not in overrides],
                  esi_outage=banner)


# What an in-game scan shows, as a richness multiplier. Set per planet on the plan result rows.
RICHNESS_LABELS = [("poor", 0.6), ("average", 1.0), ("good", 1.25), ("rich", 1.5)]


def richness_label(value: float) -> str:
    return next((label for label, v in RICHNESS_LABELS if abs(v - float(value)) < 1e-6), "")


def _measured_richness(chars: list, area: Optional[dict], s: Settings) -> dict:
    """Per-planet richness measured from the pilot's own extractors (empty without 2+ extracting colonies)."""
    if not chars or not area or not s.auto_calibrate:
        return {}
    from .intel import richness as rich
    cal = service.calibrated_yield(chars, area)
    return rich.measured_richness({c["character_id"]: c["colonies"] for c in chars}, cal) if cal else {}


def _richness_value(planet, raw):
    """(planet_id, richness or None) for a richness change, or an error text."""
    if not str(planet).isdigit():
        return None, None, "Pick a planet."
    try:
        value = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None, None, "Richness must be a number."
    if value is not None and not 0.1 <= value <= 3:
        return None, None, "Richness must be between 0.1 and 3."
    return int(planet), value, None


@router.post("/area/richness")
async def area_richness(request: Request):
    """Remove (or set) one planet's scanned richness from the Area page's list. Empty value = remove."""
    pid = _pid(request)
    form = await request.form()
    planet, value, err = _richness_value(form.get("planet_id", ""), form.get("richness", ""))
    if err:
        return redirect("/pi/area#richness", err, "warn")
    store.set_planet_override(pid, planet, value)
    return redirect("/pi/area#richness", "Planet richness saved." if value is not None else "Override removed.")


@router.post("/api/richness")
async def api_richness(request: Request):
    """Richness of one planet after scanning it in game (ESI can't tell), from a plan result row.
    Body: {planet_id, richness}; richness null = back to the estimate (or what your extractors measured).
    Saved straight away: it is what the pilot saw in game, not a planner preference to preview."""
    pid = _pid(request)
    body = await request.json()
    planet, value, err = _richness_value(body.get("planet_id"), body.get("richness"))
    if err:
        return JSONResponse({"error": err}, status_code=400)
    store.set_planet_override(pid, planet, value)
    return JSONResponse({"ok": True, "planet_id": planet, "richness": value})


@router.post("/area")
async def area_save(request: Request):
    pid = _pid(request)
    form = await request.form()
    s = store.load_settings(pid)
    chosen = [int(x) for x in form.getlist("con")]
    new_extra = form.get("extra_area", "").strip()[:TEXT_LIMITS["extra_area"]]
    extra_changed = new_extra != s.extra_area
    refresh = bool(form.get("refresh"))
    if not chosen and not (extra_changed or refresh):
        # never save an empty selection: it would quietly turn back into the default on the next visit
        return redirect("/pi/area", "Select at least one constellation. Nothing was changed.", "warn")
    if chosen:
        s.selected_constellations = chosen
    s.hub_system = form.get("hub_system", "")[:100]
    s.extra_area = new_extra
    store.save_settings(pid, s)
    if extra_changed or refresh:
        try:
            await service.load_space(service.planning_characters(pid), s, force=refresh)
        except Exception as e:  # noqa: BLE001 - the saved choice stays; say plainly what didn't happen
            if not esi_errors.is_outage(e):
                raise
            log.warning("area refresh failed: %r", e)
            return redirect("/pi/area", "Your choices are saved, but the area couldn't be read from EVE. "
                            + esi_errors.explain(e), "warn")
        msg = ("Reloaded from ESI and saved your selection." if refresh else
               "Added places are listed below: tick the constellations you want, then Save and plan.")
        return redirect("/pi/area", msg)
    return redirect(form.get("next") or "/pi/plan")


@router.get("/api/area")
async def api_area(request: Request, extra_area: Optional[str] = None,
                   selected_constellations: Optional[str] = None, hub_system: Optional[str] = None):
    """Constellations + drop-off choices for the wizard's Area step (Advanced expander)."""
    pid = _pid(request)
    chars = service.planning_characters(pid)
    s = store.load_settings(pid)
    if extra_area is not None:
        s.extra_area = extra_area.strip()[:TEXT_LIMITS["extra_area"]]
        s.selected_constellations = []
    s.update({key: value for key, value in {"selected_constellations": selected_constellations,
                                          "hub_system": hub_system}.items() if value is not None})
    area = await service.load_space(chars, s) if chars else None
    if not area:
        return JSONResponse({"constellations": [], "selected": [], "systems": [],
                             "selling_coverage": selling.coverage("", None)})
    groups = space_mod.grouped(area, chars, store.planet_overrides(pid))
    selected = (s.selected_constellations if selected_constellations is not None
                else s.selected_constellations or space_mod.default_selection(groups))
    cons = [{"id": c["id"], "name": c["name"], "region": r["name"], "systems": len(c["systems"]),
             "score": c["score"], "has_colonies": c["has_colonies"], "sec": [c["sec_max"], c["sec_min"]]}
            for r in groups for c in r["constellations"]]
    systems = space_mod.selected_systems(area, selected)
    names = sorted({v["name"] for v in systems.values()}
                   | {n for n in voc.COURIER_ORIGINS if space_mod_has(area, n)})
    hub = optimizer.resolve_hub(area, s, systems, store.planet_overrides(pid)) if systems else None
    return JSONResponse({"constellations": cons, "selected": selected, "systems": names,
                         "hub_system": s.hub_system, "voc": voc.COURIER_ORIGINS,
                         "selling_coverage": selling.coverage(hub["name"] if hub else "", area)})


def space_mod_has(area, name) -> bool:
    return any(v["name"] == name for v in area["systems"].values())


# ----------------------------------------------------------------------------- plan
@router.get("/plan", response_class=HTMLResponse)
async def plan_page(request: Request):
    pid = _pid(request)
    if not service.planning_characters(pid):
        return redirect("/pi")   # /pi says why: connect, or include one
    ctx = await service.planning_context(pid, persist_default=False)
    s = ctx["s"]
    hubs = sorted({v["name"] for v in ctx["systems"].values()} |
                  {n for n in voc.COURIER_ORIGINS if ctx["area"] and space_mod_has(ctx["area"], n)})
    advanced = request.query_params.get("view") == "advanced"
    page = "planner.html" if advanced else "guide.html"
    if not advanced:
        s.selected_constellations = store.load_settings(pid).selected_constellations
    eligible = [c for c in ctx["chars"] if setups.can_plan(c)]
    first_visit = not store.has_settings(pid) or not s.answered
    return render(request, page, page[:-5], "Plan", s=s, chars=ctx["chars"], systems=hubs,
                  prices_at=prices.cached().get("at"), calibrated=ctx["calibrated"],
                  head_yield=ctx["head_yield"], settings_json=s.to_json(), voc_hubs=voc.COURIER_ORIGINS,
                  slots=sum(int(c["slots"]) for c in eligible), eligible_characters=len(eligible),
                  blocked_characters=len(ctx["chars"]) - len(eligible),
                  n_systems=len(ctx["systems"]) if advanced or s.selected_constellations else 0,
                  dropoff=ctx["dropoff"] if advanced or s.selected_constellations else None, selling_coverage=selling.coverage(ctx["dropoff"], ctx["area"]), seller=ctx["seller"], api="/pi/api", export="/pi/export",
                  settings_url="/pi/settings", operate_url="/pi/operate", advanced_url="/pi/plan?view=advanced",
                  guided_url="/pi/plan", first_visit=first_visit, panel=character_panel(pid),
                  plans=store.list_plan_runs(pid), waypoints=_waypoint_chars(pid), hour_defaults=HOUR_DEFAULTS,
                  esi_outage=service.outage_banner(ctx), products=_product_names(ctx.get("pi")),
                  richness_labels=RICHNESS_LABELS, expert_url=EXPERT_URL,
                  help_answers=glossary.answers(s, ctx["head_yield"], bool(ctx["calibrated"])), glossary_url=glossary.GLOSSARY_URL)


EXPERT_URL = "/pi/settings?expert=1#expert"


def _product_names(pi) -> list:
    """Every PI product a plan can make (P1-P4), for the "Never produce" checkboxes: [{name, tier}]."""
    if not pi:
        return []
    return sorted(({"name": pi.name(t), "tier": pi.tier(t)} for t in pi.items if 1 <= pi.tier(t) <= 4),
                  key=lambda p: (p["tier"], p["name"]))


# ----------------------------------------------------------------------------- glossary
@router.get("/glossary", response_class=HTMLResponse)
async def glossary_page(request: Request):
    return render(request, "glossary.html", "glossary", "Glossary", entries=glossary.entries())


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
            before = _profile_result_stamp(pid)
            res = copy.deepcopy(await service.solve(pid, s))
            if (before != _profile_result_stamp(pid)
                    or store.plan_settings(s) != store.plan_settings(store.load_settings(pid))):
                return JSONResponse({"error": "Your planning data or answers changed. Recalculate your plan.",
                                     "stale": True}, status_code=409)
    except Busy:
        return busy_response()
    except Superseded:
        return superseded_response()
    res["weights"] = time_weights(s)
    if "error" not in res:
        res["facts"] = compare.plan_facts(res, s)
        res["result_id"] = store.remember_plan_result(pid, s, res, _result_stamp(pid))
    return JSONResponse(res)


ADVANCED_FIELDS = LIVE_FIELDS - {"guide_step", "answered"}


@router.post("/api/preview")
async def api_preview(request: Request):
    return await _advanced_result(request, apply=False)


@router.post("/api/apply")
async def api_apply(request: Request):
    return await _advanced_result(request, apply=True)


async def _advanced_result(request: Request, apply: bool):
    """Experimental controls never change confirmed answers until explicitly applied."""
    pid = _pid(request)
    body = await request.json()
    try:
        async with GATE.request(pid, "advanced"):
            original = store.load_settings(pid)
            baseline = store.plan_settings(original)
            if apply and body.get("baseline") != baseline:
                return JSONResponse({"error": "Your saved settings changed. Reload before applying this preview.",
                                     "stale": True}, status_code=409)
            s = copy.deepcopy(original)
            s.update({k: v for k, v in body.get("settings", {}).items() if k in ADVANCED_FIELDS})
            before = _result_stamp(pid)
            res = copy.deepcopy(await service.solve(pid, s))
            if before != _result_stamp(pid) or baseline != store.plan_settings(store.load_settings(pid)):
                return JSONResponse({"error": "Your planning data or answers changed. Recalculate your preview.",
                                     "stale": True}, status_code=409)
            if "error" not in res and apply:
                # Navigation may have changed during the solve; retain its newest values.
                current = store.load_settings(pid)
                s.guide_step, s.answered = current.guide_step, current.answered
                store.save_settings(pid, s)
            res["weights"] = time_weights(s)
            if "error" not in res and apply:
                res["facts"] = compare.plan_facts(res, s)
                res["result_id"] = store.remember_plan_result(pid, s, res, _result_stamp(pid))
            res["preview"] = not apply
            res["baseline"] = store.plan_settings(s) if apply and "error" not in res else baseline
            return JSONResponse(res)
    except Busy:
        return busy_response()
    except Superseded:
        return superseded_response()


@router.post("/api/save")
async def api_save(request: Request):
    """Store wizard answers without solving. Only the fields sent are changed."""
    pid = _pid(request)
    body = await request.json()
    s = _apply(store.load_settings(pid), body)
    store.save_settings(pid, s)
    return JSONResponse({"ok": True})


WHATIF_OPTIONS = 6          # answer cards per question at most
PREFETCH_PATIENCE = 20.0    # seconds background warming waits for an idle planner before giving up
PREFETCH_POLL = 0.5
QUEUE_UPDATE = 1.0          # seconds between queue-position updates on a streamed comparison
_BACKGROUND: set = set()    # running prefetch / stream tasks (the event loop only keeps weak references)


def _background(coro) -> "asyncio.Task":
    task = asyncio.get_running_loop().create_task(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return task


def _whatif_settings(base: Settings, opt: dict) -> Settings:
    ss = copy.deepcopy(base)
    ss.update({k: v for k, v in opt.get("patch", {}).items() if k in LIVE_FIELDS})
    return ss


async def _whatif_card(pid: int, base: Settings, opt: dict) -> dict:
    """One answer card. The full plan is cached (shared with the plan result), the card shows its summary."""
    ss = _whatif_settings(base, opt)
    key = service.plan_key(pid, ss)
    if key in GATE._cache:
        res = GATE._cache[key]
    else:
        ctx = await service.planning_context(pid, ss, persist_default=False)
        res = await GATE.cached(service.plan_key(pid, ss), service.run_plan, ctx)
    return {"id": opt.get("id"), **service.whatif_summary(res, ss)}


@router.post("/api/whatif")
async def api_whatif(request: Request):
    """Plan several answers to one question side by side.
    Body: {"base": {live fields}, "options": [{"id": ..., "patch": {live fields}}, ...]}

    * Default: one JSON list once every card is planned.
    * "stream": true -> application/x-ndjson, one line per event as it happens: {"queue": {ahead, solves, eta}}
      while waiting for a solve slot, {"card": {...}} per answer as soon as it is planned, and one final
      {"done": true} | {"superseded": true} | {"busy": true, "retry_after": s} | {"error": "..."}.
      Same gate semantics as the list: one comparison per profile, a newer one supersedes it.
    * "prefetch": true -> 202 at once; the cards are planned into the cache in the background, only while
      the planner has a free slot nobody is waiting for (see `_prefetch`)."""
    pid = _pid(request)
    body = await request.json()
    base = _apply(store.load_settings(pid), body.get("base", {}))
    options = body.get("options", [])[:WHATIF_OPTIONS]
    if body.get("prefetch"):
        generation = GATE.supersede(pid, "prefetch")
        _background(_prefetch(pid, base, options, generation))
        return JSONResponse({"queued": len(options)}, status_code=202)
    if body.get("stream"):
        return StreamingResponse(_whatif_stream(pid, base, options), media_type="application/x-ndjson",
                                 headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-transform"})  # proxies (Cloudflare) mustn't buffer or compress the stream
    try:
        async with GATE.request(pid, "whatif"):
            rows = await asyncio.gather(*[_whatif_card(pid, base, o) for o in options])
    except Busy:
        return busy_response()
    except Superseded:
        return superseded_response()
    return JSONResponse(list(rows))


async def _whatif_stream(pid: int, base: Settings, options: list):
    """The comparison as newline-delimited JSON events (see api_whatif). The planning runs in its own task:
    a client that disconnects (or moves on) doesn't cancel solves, and a newer comparison supersedes it."""
    events: asyncio.Queue = asyncio.Queue()

    async def card(opt):
        await events.put({"card": await _whatif_card(pid, base, opt)})

    async def work():
        try:
            async with GATE.request(pid, "whatif"):
                await asyncio.gather(*[card(o) for o in options])
            final = {"done": True}
        except Busy:
            final = {"busy": True, "retry_after": 3}
        except Superseded:
            final = {"superseded": True}
        except Exception:  # noqa: BLE001 - the page offers a retry; the details belong in the log
            log.exception("whatif stream failed")
            final = {"error": "Could not compare these setups."}
        await events.put(final)

    task = _background(work())
    shown = None
    while True:
        try:
            event = await asyncio.wait_for(events.get(), timeout=QUEUE_UPDATE)
        except asyncio.TimeoutError:
            event = None
        if event is None or "card" in event:
            queue = GATE.position(pid)       # cheap: only this process's own queue
            if queue != shown and (queue or shown):
                shown = queue
                yield json.dumps({"queue": queue or {"ahead": 0, "solves": 0, "eta": 0}}) + "\n"
        if event is not None:
            yield json.dumps(event, default=str) + "\n"
            if "card" not in event:
                break
    await task


async def _prefetch(pid: int, base: Settings, options: list, generation: int) -> None:
    """Warm the next question's cards while the pilot reads this one. Low priority: a card is only solved in
    a slot that is free with nobody waiting (GATE.warm); a newer prefetch from the same pilot stops this one
    before its next card; after PREFETCH_PATIENCE seconds of a busy planner it gives up. Never raises."""
    deadline = time.monotonic() + PREFETCH_PATIENCE
    try:
        for opt in options:
            ss = _whatif_settings(base, opt)
            while GATE.is_current(pid, "prefetch", generation):
                if service.plan_key(pid, ss) in GATE._cache:
                    break
                if GATE.idle():
                    ctx = await service.planning_context(pid, ss, persist_default=False)
                    if not GATE.is_current(pid, "prefetch", generation):
                        return
                    try:
                        await GATE.warm(service.plan_key(pid, ss), service.run_plan, ctx)
                        break
                    except Skipped:
                        pass         # a pilot's request took the slot meanwhile: wait for the next one
                if time.monotonic() > deadline:
                    return
                await asyncio.sleep(PREFETCH_POLL)
            else:
                return               # superseded
    except Exception:  # noqa: BLE001 - background warming must never surface; the real request will retry
        log.warning("prefetch for profile %s failed", pid, exc_info=True)


@router.post("/api/alternatives")
async def api_alternatives(request: Request):
    pid = _pid(request)
    try:
        async with GATE.request(pid, "alternatives"):
            body = await request.json()
            s = store.load_settings(pid)
            s.update({k: v for k, v in body.get("base", {}).items() if k in ADVANCED_FIELDS})
            ctx = await service.planning_context(pid, s, persist_default=False)
            key = cache_key(service.data_stamp(pid), ctx["solve_s"].solve_json(), "alternatives")
            alts = await GATE.cached(key, optimizer.alternatives, ctx["pi"], ctx["solve_s"], ctx["area"],
                                     ctx["systems"], ctx["chars"], ctx["values"], ctx["tpl"], ctx["overrides"],
                                     ctx["head_yield"], ctx.get("buy"), ctx.get("buy_cap"))
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
            body = await request.json()
            s = store.load_settings(pid)
            s.update({k: v for k, v in body.get("base", {}).items() if k in ADVANCED_FIELDS})
            ctx = await service.planning_context(pid, s, persist_default=False)
            key = cache_key(service.data_stamp(pid), ctx["solve_s"].solve_json(), "sensitivity")
            rows = await GATE.cached(key, optimizer.yield_sensitivity, ctx["pi"], ctx["solve_s"], ctx["area"],
                                     ctx["systems"], ctx["chars"], ctx["values"], ctx["tpl"], ctx["overrides"],
                                     ctx["head_yield"], ctx.get("buy"), ctx.get("buy_cap"))
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
    if not await service.refresh_prices(pi):      # no order book loaded: the last ones stay in use
        return JSONResponse({"ok": False, "at": at, "error": esi_errors.HEADLINE + " Prices weren't refreshed; "
                             "plans keep using the last ones. Try again in a few minutes."}, status_code=503)
    if prices.history_stale():
        service.refresh_history_soon(pi)
    await voc.refresh_routes()
    return JSONResponse({"ok": True, "at": prices.cached().get("at")})


# ----------------------------------------------------------------------------- saved plans
def _profile_result_stamp(pid: int) -> str:
    """Personal planning inputs, including ownership and character eligibility."""
    chars = [(c["character_id"], c.get("name"), c.get("synced_at"), c.get("enabled"), c.get("status"),
              c.get("slots"), c.get("ccu_level"), c.get("scopes"), c.get("bundle_prefs"),
              c.get("enabled_modules"), c.get("has_token"), c.get("skills"), c.get("colonies"))
             for c in db.list_characters(pid)]
    return json.dumps([chars, store.planet_overrides(pid), store.admin_defaults()], sort_keys=True, default=str)


def _result_stamp(pid: int) -> str:
    return json.dumps([service.data_stamp(pid), _profile_result_stamp(pid)], sort_keys=True, default=str)


@router.post("/api/plans")
async def api_plan_save(request: Request):
    """Save the exact server-owned displayed result. Body: {result_id, label, active}."""
    pid = _pid(request)
    body = await request.json()
    result_id = body.get("result_id")
    if not isinstance(result_id, str) or not result_id:
        return JSONResponse({"error": "Calculate a plan before saving it.", "stale": True}, status_code=409)
    try:
        run = store.save_plan_result(pid, result_id, str(body.get("label") or ""),
                                     lambda: _result_stamp(pid), active=bool(body.get("active")))
    except store.StaleResult as exc:
        return JSONResponse({"error": str(exc), "stale": True}, status_code=409)
    return JSONResponse({"ok": True, "id": run["id"], "label": run["label"], "active": run["active"],
                         "plans": store.list_plan_runs(pid)})


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
                headers={**default_headers(), "Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                return JSONResponse({"error": f"EVE refused the waypoint ({r.status_code}). Is {ch['name']} online?"},
                                    status_code=502)
    return JSONResponse({"ok": True, "sent": len(ids), "character": ch["name"]})


# ----------------------------------------------------------------------------- operate
@router.get("/operate", response_class=HTMLResponse)
async def operate_page(request: Request):
    pid = _pid(request)
    if not service.planning_characters(pid):
        return redirect("/pi")   # /pi says why: connect, or include one
    ctx = await service.planning_context(pid)
    chars = ctx["chars"]
    active = store.active_plan(pid)
    plan = active["result"] if active else None
    days = 30 if request.query_params.get("days") == "30" else 7
    missing = [c["name"] for c in chars if not service.pi_ready(c)]
    ov = service.operate_overview(ctx["pi"], ctx["s"], ctx["books"], chars, ctx["area"], plan)
    pickup_text, pickup_error = "", ""
    try:
        pickup_text = _pickup_item_list(ctx["pi"], chars)
    except HTTPException as exc:
        pickup_error = exc.detail
    return render(request, "operate.html", "operate", "Operate", chars=chars,
                  status=operate.colonies_status(ctx["pi"], chars, ctx["area"]),
                  pickup_text=pickup_text, pickup_error=pickup_error,
                  upkeep=ov["upkeep"], stock=ov["stock"], consolidated=ov["consolidated"], pipe=ov["pipe"],
                  next_up=ov["next_up"][:nextup.SHOWN], next_up_more=max(0, len(ov["next_up"]) - nextup.SHOWN),
                  all_clear=ov["all_clear"], has_colonies=ov["has_colonies"],
                  earned=operate.earnings(ctx["pi"], chars, days), days=days,
                  progress=ov["progress"], drift=ov["drift"], plan=plan, active=active, missing=missing,
                  checklist=service.first_build(ctx, active), restock_buy=service.restock_purchases(ctx, active),
                  plans=store.list_plan_runs(pid), freshness=freshness.state(pid),
                  colony_note=freshness.COLONY_NOTE, buyback_site=voc.BUYBACK_SITE,
                  voc_site=voc.SITE, waypoints=_waypoint_chars(pid), esi_outage=service.outage_banner(ctx))


# ----------------------------------------------------------------------------- exports
PICKUP_NOTE = ("Cached colony stock only; customs-office access and cargo capacity are not checked. "
               "Stock may have changed since the colony snapshot.")


def _csv_text(value: str) -> str:
    # Spreadsheet software may treat untrusted names as formulas even when CSV-quoted.
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def _pickup_rows(pi, chars):
    """Validated cached whole-unit pickups shared by the CSV and item list."""
    if pi is None and any(ch.get("colonies") for ch in chars):
        raise HTTPException(503, "Pickup export needs cached PI item metadata. Open Operate to load it first.")
    rows = []
    for ch in chars:
        for col in ch.get("colonies", []):
            for pin in col.get("pins", []):
                if pin.get("schematic_id") and pin["schematic_id"] not in pi.schematics:
                    raise HTTPException(503, "Pickup export needs cached factory recipes to exclude colony inputs.")
                for item in pin.get("contents", []) or []:
                    amount = item.get("amount")
                    if (isinstance(amount, bool) or not isinstance(amount, (int, float))
                            or not math.isfinite(amount) or amount < 0):
                        raise HTTPException(503, "Pickup export needs known stock quantities. Refresh colony data first.")
                    if amount > 0 and pi.tier(item["type_id"]) < 0:
                        raise HTTPException(503, "Pickup export needs complete cached PI item metadata. "
                                            "Unknown stock cannot be classified as a finished product.")
            for tid, qty in sorted(operate.pickup_stock(pi, col).items()):
                rows.append({"character": ch, "colony": col, "type_id": tid, "quantity": int(qty), "stock_quantity": qty})
    return rows


def _pickup_item_list(pi, chars):
    totals = defaultdict(int)
    for row in _pickup_rows(pi, chars):
        name = pi.items[row["type_id"]].get("name")
        if (not name or not name.strip() or name == str(row["type_id"])
                or any(char in name for char in "\r\n\t")):
            raise HTTPException(503, "The item list needs cached EVE product names. Open Operate to load them first.")
        totals[name] += row["quantity"]
    return voc.paste_list(totals)


@router.get("/export/pickup.txt")
async def export_pickup_items(request: Request):
    text = _pickup_item_list(sde_loader.cached(), service.planning_characters(_pid(request)))
    return Response(text + "\n" if text else "", media_type="text/plain",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-pickup-items.txt"',
                             "Cache-Control": "no-store"})


@router.get("/export/pickup.csv")
async def export_pickup(request: Request):
    chars = service.planning_characters(_pid(request))
    pi = sde_loader.cached()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["character", "character_id", "planet", "planet_id", "system", "product", "type_id",
                     "quantity", "volume_m3", "colony_snapshot", "character_synced_at_utc", "metadata", "limits"])
    for row in _pickup_rows(pi, chars):
        ch, col, tid, qty = row["character"], row["colony"], row["type_id"], row["quantity"]
        synced = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ch["synced_at"])) if ch.get("synced_at") else ""
        planet = operate.colony_name({}, col)
        item = pi.items[tid]
        volume = item.get("volume")
        missing = [key for key in ("name", "volume") if item.get(key) is None]
        writer.writerow([_csv_text(ch["name"]), ch["character_id"], _csv_text(planet["name"]),
                         col["planet_id"], _csv_text(planet["system"]), _csv_text(item.get("name") or str(tid)), tid,
                         qty, round(row["stock_quantity"] * volume, 3) if volume is not None else "",
                         col.get("last_update") or "", synced,
                         "missing " + ", ".join(missing) if missing else "complete", PICKUP_NOTE])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-pickup.csv"',
                             "Cache-Control": "no-store"})


async def _export_run(request: Request) -> dict:
    """Export a displayed result handle, named saved plan, current solve or active plan."""
    pid = _pid(request)
    result_id = request.query_params.get("result")
    if result_id is not None:
        try:
            return store.get_plan_result(pid, result_id, lambda: _result_stamp(pid))
        except store.StaleResult as exc:
            raise HTTPException(409, str(exc)) from exc
    run = request.query_params.get("plan")
    if run is not None:
        # A named plan exports that plan or nothing: never quietly a different one.
        saved = store.get_plan_run(pid, int(run)) if run.isdigit() else None
        if not saved:
            raise HTTPException(404, "That saved plan doesn't exist (any more).")
        return saved
    if request.query_params.get("current") != "1":
        active = store.active_plan(pid)
        if active:
            return active
    s = store.load_settings(pid)
    async with GATE.request(pid, "export"):
        res = await service.solve(pid, s)
    return {"result": res, "settings": json.loads(s.to_json())}


async def _export_plan(request: Request) -> dict:
    return (await _export_run(request))["result"]


def _removal_planet(x: dict) -> str:
    """Plans saved before planet names were stored only have the id."""
    return x.get("planet") or f"planet {x['planet_id']}"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _where_md(x: dict) -> str:
    pickup = (x.get("pickup") or {}).get("text")
    return f"{x['where']} ({pickup})" if pickup else x["where"]


def _haul_md(x: dict) -> str:
    if x.get("haul_isk"):
        return fmt.isk(x["haul_isk"]) + (f" ({x['haul_note']})" if x.get("haul_note") else "")
    return x.get("haul_note") or "–"


def _template_credit_md(source: Optional[str]) -> str:
    return f"[Template by DalShooth]({source or dalshooth.REPO_URL})"


def _first_build_md(k: Optional[dict]) -> list:
    """The Operate first-build checklist as Markdown: Multibuy lists, cost split, steps per character."""
    if not k:
        return []
    out = ["## First build", ""]
    if not k.get("todo"):
        return out + ["Every colony in this plan is already built.", ""]
    c = k["costs"]
    rebuilt = f", {k['rebuild']} of them rebuilt" if k.get("rebuild") else ""
    out += [f"{_plural(k['todo'], 'colony', 'colonies')} to build{rebuilt}. AstraCore can't buy anything or place "
            "market orders for you: paste the lists into EVE's Multibuy window (Market → Multibuy), check the "
            "prices and buy it yourself. Structures and command center upgrades aren't market items: the "
            "planetary interface charges them to your wallet when you submit.", ""]
    if k.get("blocked"):
        out += [f"**{_plural(k['blocked'], 'colony', 'colonies')} can't be built as planned yet** "
                "(see Train first / Template missing below).", ""]
    when = f" Market prices from {fmt.ago(k['prices_at'])}." if k.get("prices_at") else ""
    out += [f"**Estimated startup cost: {fmt.isk(c['total'])} ISK** (without starter stock).{when} "
            "Customs import tax isn't included.", "",
            f"- Command centers (market): {fmt.isk(c['command_centers'])}"
            + (" (includes an estimate: no cached market price for some)" if c.get("estimated_cc") else ""),
            f"- Command center upgrades (wallet, in game): {fmt.isk(c['upgrades'])}",
            f"- Structures (wallet, in game): {fmt.isk(c['structures'])}",
            f"- Optional factory starter stock (market): {fmt.isk(c['supplies'])}", ""]
    out += ["### 1 · Buy on the market", ""]
    if k["command_centers"]:
        out += ["| Item | Qty | Where | Each | Goods | Hauling | Landed |", "|---|---|---|---|---|---|---|"]
        out += [f"| {x['name']} | {x['qty']} | {_where_md(x)} | {fmt.isk(x['unit_isk'])}"
                f"{' (est.)' if x['estimated'] else ''} | {fmt.isk(x['isk'])} | {_haul_md(x)} "
                f"| {fmt.isk(x.get('landed_isk', x['isk']))} |" for x in k["command_centers"]]
        out += ["", "Multibuy list:", "", "```", k["multibuy"], "```", "",
                f"{fmt.m3(k['cc_m3'])} to carry"
                + ("; the Delve market sells them, which saves the haul." if k.get("cc_local")
                   else " from the trade hub to your systems."), ""]
    else:
        out += ["Nothing to buy: every colony still to build is a rebuild on a planet where you already have "
                "a command center.", ""]
    if k.get("supplies"):
        out += [f"### Optional · Factory starter stock ({fmt.num(k['supply_days'], 1)} days of inputs)", "",
                "| Item | Qty | Where | Goods | Hauling | Landed | For |", "|---|---|---|---|---|---|---|"]
        out += [f"| {x['item']} | {fmt.num(x['qty'])} | {_where_md(x) if x['where'] else '–'} "
                f"| {fmt.isk(x['isk']) if x['where'] else '–'} | {_haul_md(x) if x['where'] else '–'} "
                f"| {fmt.isk(x.get('landed_isk', x['isk'])) if x['where'] else '–'} | {', '.join(x['for'])} |"
                for x in k["supplies"]]
        out += ["", "Multibuy list:", "", "```", k["supplies_multibuy"], "```", "",
                "Your miners in this plan make these inputs. Buy a starter stock only to run the factories from "
                "day one instead of after the first pickup."
                + (f" No seller cached for {', '.join(k['unpriced'])}." if k.get("unpriced") else ""), ""]
    hl = k.get("hauling") or {}
    if hl.get("contracts") or hl.get("self_haul"):
        out += [f"### Hauling to {hl.get('dropoff')}", ""]
        for c in hl.get("contracts", []):
            extra = " extra" if c.get("shared") else ""
            split = f" over {c['contracts']} contracts (VOC's size limit)" if c.get("contracts", 1) > 1 else ""
            carry = (f", then carry it {c['carry_jumps']} jump{'s' if c['carry_jumps'] != 1 else ''} to "
                     f"{hl.get('dropoff')} yourself") if c.get("carry_jumps") else ""
            approx = (f" *Approximation: VOC's tariff lists {c['to']} → {c['from']} only; the same rate is assumed "
                      "this way. Check it on vochauling.com before you contract.*") if c.get("approx") else ""
            what = " (starter stock)" if c.get("section") == "starter_stock" else ""
            diy = (f" The fee is more than these goods are worth: with a Deep Space Transport ({c['self_haul_trips']} "
                   f"trip{'s' if c['self_haul_trips'] != 1 else ''} of ≈ 60,000 m³) flying it yourself may be cheaper; "
                   "AstraCore doesn't price that trip or its risk.") if c.get("self_haul_trips") else ""
            out.append(f"- VOC courier {c['from']} → {c['to']}{what}: {fmt.m3(c['m3'])}, collateral "
                       f"{fmt.isk(c['collateral'])},{extra} fee {fmt.isk(c['fee'])}{split}{carry}.{diy}{approx}")
        if hl.get("self_haul"):
            out.append(f"- From {' and '.join(hl['self_haul'])}: no VOC courier route to your drop-off is known, "
                       "so you haul it yourself and the hauling isn't priced.")
        out.append("")
    out += ["### 2 · Upgrade and build, per character and planet", "",
            "Follow each character's pickup route; costs are EVE's standard planetary prices.", ""]
    for ch in k["characters"]:
        bring = ", ".join(f"{n}× {t}" for t, n in ch["command_centers"].items())
        if bring:
            bring = f" · bring {bring} Command Center{'s' if sum(ch['command_centers'].values()) != 1 else ''}"
        out += [f"#### {ch['name']}", "",
                f"{_plural(len(ch['planets']), 'planet', 'planets')} · Command Center Upgrades {ch['ccu_skill']}"
                f"{bring} · ≈ {fmt.isk(ch['isk'])} ISK in game", ""]
        if ch.get("removals"):
            gone = "; ".join(r["planet"] + (f" ({r['system']})" if r.get("system") else "")
                             + (f", {r['current']}" if r.get("current") else "") for r in ch["removals"])
            out += [f"First free the slots this plan doesn't keep: pick up the products, then abandon {gone}.", ""]
        for i, p in enumerate(ch["planets"], 1):
            upgrade = f" (upgrade {fmt.isk(p['upgrade']['isk'])})" if p["upgrade"]["isk"] else ""
            out.append(f"{i}. **{p['planet']}** ({p['system']} · {p['planet_type']}) · {p['action']} · "
                       f"{p['template']} · {_template_credit_md(p.get('template_url'))} · "
                       f"**{p['compat']['label']}**: {p['compat']['text']} · "
                       f"≈ {fmt.isk(p['build_isk'])} ISK{upgrade}")
            out += [f"    {j}. {step}" for j, step in enumerate(p["steps"], 1)]
        out.append("")
    return out


@router.get("/export/templates.zip")
async def export_templates(request: Request):
    try:
        res = await _export_plan(request)
    except (Busy, Superseded):
        return Response("AstraCore is busy. Try again in a moment.", status_code=503)
    return Response(dalshooth.zip_pack(res.get("templates_needed", [])), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-templates.zip"'})


@router.get("/export/plan.md")
async def export_md(request: Request):
    try:
        run = await _export_run(request)
    except (Busy, Superseded):
        return Response("AstraCore is busy. Try again in a moment.", status_code=503)
    res = run["result"]
    if "error" in res:
        return Response(res["error"], status_code=400)
    checklist = await service.first_build_for(_pid(request), res, run.get("settings"))
    t = res["totals"]
    out = ["# AstraCore PI plan", "",
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
                out.append(f"| {c['planet']} ({c['planet_type']}) | {c['template']} · "
                           f"{_template_credit_md(c.get('template_url'))} | {outs} "
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
        out += [f"- {x['character']}: {_removal_planet(x)} ({x['current']})" for x in res["removals"]]
    first = _first_build_md(checklist)
    if first:
        out += [""] + first
    return Response("\n".join(out), media_type="text/markdown",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-plan.md"'})


@router.get("/export/plan.csv")
async def export_csv(request: Request):
    try:
        res = await _export_plan(request)
    except (Busy, Superseded):
        return Response("AstraCore is busy. Try again in a moment.", status_code=503)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["character", "system", "planet", "planet_type", "template", "product", "out_per_day",
                "in_per_day", "isk_per_day", "m3_per_week", "action", "template_author", "template_source"])
    for c in res.get("colonies", []):
        w.writerow([c["character"], c["system"], c["planet"], c["planet_type"], c["template"], c["product"],
                    json.dumps(c["out_per_day"]), json.dumps(c["in_per_day"]), c["value_per_day"],
                    c["m3_per_week"], c["action"], "DalShooth", c.get("template_url") or dalshooth.REPO_URL])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-plan.csv"'})


@router.get("/export/shopping.csv")
async def export_shopping(request: Request):
    """The first-build shopping list: command centers and optional factory starter stock, priced where the
    checklist buys them, then the in-game costs (paid from the wallet, not on the market) as cost rows."""
    try:
        run = await _export_run(request)
    except (Busy, Superseded):
        return Response("AstraCore is busy. Try again in a moment.", status_code=503)
    res = run["result"]
    if "error" in res:
        return Response(res["error"], status_code=400)
    k = await service.first_build_for(_pid(request), res, run.get("settings")) or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "item", "qty", "where", "unit_isk", "isk", "estimated", "for",
                "haul_isk", "landed_isk", "hauling", "pickup"])

    def haul(x):
        return [x.get("haul_isk", ""), x.get("landed_isk", ""), x.get("haul_note") or "",
                (x.get("pickup") or {}).get("text", "")]
    for c in k.get("command_centers", []):
        w.writerow(["command_center", c["name"], c["qty"], c["where"], c["unit_isk"], c["isk"],
                    int(bool(c["estimated"])), ""] + haul(c))
    for x in k.get("supplies", []):
        priced = bool(x["where"])
        w.writerow(["starter_stock", x["item"], x["qty"], x["where"] or "", x["unit_isk"] if priced else "",
                    x["isk"] if priced else "", "", "; ".join(x["for"])] + (haul(x) if priced else ["", "", "", ""]))
    if k.get("todo"):
        costs = k["costs"]
        w.writerow(["in_game", "Command center upgrades", "", "Planetary interface", "", costs["upgrades"], "", "",
                    "", "", "", ""])
        w.writerow(["in_game", "Structures", "", "Planetary interface", "", costs["structures"], "", "",
                    "", "", "", ""])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="astracore-pi-shopping.csv"'})


# ----------------------------------------------------------------------------- settings
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    pid = _pid(request)
    s = store.load_settings(pid)
    chars = service.planning_characters(pid)
    outage = esi_errors.Outage()
    area = await service.load_space(chars, s, outage=outage) if chars else None
    cal = service.calibrated_yield(chars, area) if chars else None
    from .intel import richness as rich
    measured = rich.measured_richness({c["character_id"]: c["colonies"] for c in chars}, cal) if cal else {}
    customs_on = [c["name"] for c in service.characters(pid) if bundle_active(c, "pi.optional.customs")]
    return render(request, "settings.html", "settings", "Settings", s=s, calibrated=cal, measured=measured,
                  expert_open=request.query_params.get("expert") == "1",
                  rates=[skills_mod.character_rates(c) for c in chars if c.get("skills")],
                  seller=skills_mod.best_seller(chars), poco=skills_mod.customs_rates(chars),
                  customs_on=customs_on,
                  esi_outage=outage.banner(c.get("synced_at") for c in chars))


@router.post("/settings")
async def settings_save(request: Request):
    pid = _pid(request)
    form = await request.form()
    data = {k: v for k, v in form.items() if k not in ADMIN_FIELDS and k != "csrf_token"}
    data["__bool_fields__"] = form.getlist("__bool_fields__")
    s = store.load_settings(pid)
    s.update(data)
    store.save_settings(pid, s)
    return redirect(EXPERT_URL, "Saved.")


@router.get("/reset", response_class=HTMLResponse)
async def reset_pi_page(request: Request):
    return render(request, "reset.html", "profile", "Reset AstraCore PI", profile=db.get_profile(_pid(request)))


@router.post("/reset")
async def reset_pi(request: Request):
    pid = _pid(request)
    profile = db.get_profile(pid)
    form = await request.form()
    if form.get("confirm", "") != profile["display_name"]:
        return redirect("/pi/reset", f"Type {profile['display_name']} exactly to confirm.", "warn")
    store.reset_profile(pid)
    return redirect("/profile", "AstraCore PI was reset: settings, plans and planet overrides are gone. "
                                "Your characters are still linked.")


# ----------------------------------------------------------------------------- old MVP paths (301: bookmarks keep working)
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
