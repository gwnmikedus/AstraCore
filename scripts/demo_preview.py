"""Screenshot-only fictional PI preview. Run with --help; never imports live configuration."""

import argparse
import asyncio
import copy
import json
import os
import re
from pathlib import Path
import secrets
import tempfile
import sys
import time


def isolated_environment(directory: Path, port: int) -> None:
    """Replace inherited application settings before importing any AstraCore module."""
    if "astracore.config" in sys.modules:
        raise RuntimeError("Start the screenshot runner in a fresh Python process.")
    for name in tuple(os.environ):
        if name.startswith(("ASTRACORE_", "EVE_", "PI_PLANNER_")):
            del os.environ[name]
    os.environ.update(ASTRACORE_MODE="local", ASTRACORE_DEMO="fictional", ASTRACORE_HOME=str(directory),
                      ASTRACORE_DATA=str(directory / "data"),
                      ASTRACORE_STATIC_DATA=str(directory / "static"),
                      ASTRACORE_ENV_FILE=str(directory / ".env.demo"),
                      ASTRACORE_PUBLIC_URL=f"http://127.0.0.1:{port}",
                      ASTRACORE_SESSION_SECRET=secrets.token_hex(32))


def create_demo():
    if os.environ.get("ASTRACORE_DEMO") != "fictional":
        raise RuntimeError("Initialize an isolated fictional environment first.")
    import httpx
    from fastapi import Request
    from fastapi.responses import JSONResponse, RedirectResponse, PlainTextResponse
    from astracore import db
    from astracore.core import community, sessions
    from astracore.modules.pi import service, store, routes
    from astracore.modules.pi.settings import Settings, time_weights
    from astracore.modules.pi.static_data.sde_loader import build_from_rows
    from astracore.app import create_app

    async def no_network(*args, **kwargs):
        raise RuntimeError("The fictional preview cannot contact external services.")

    httpx.AsyncClient.request = no_network

    async def idle():
        await asyncio.Event().wait()

    community.run_sync_loop = idle
    service.warm_history = idle
    db.init()
    pid = db.create_profile("Fictional demo crew")
    chars = []
    for cid, name in ((-1151, "Demo Pilot Aurora"), (-1152, "Demo Pilot Beacon")):
        db.link_character(cid, pid, name)
        db.set_character(cid, ccu_level=5, slots=2, synced_at=time.time(), source="demo")
        ch = db.get_character(cid)
        ch.update(has_token=True, scopes=sorted(service.REQUIRED_SCOPES))
        chars.append(ch)
    original_list_characters = db.list_characters
    db.list_characters = lambda profile_id, **kwargs: (copy.deepcopy(chars) if profile_id == pid
                                                       else original_list_characters(profile_id, **kwargs))
    service.planning_characters = lambda profile_id: copy.deepcopy(chars)
    service.characters = lambda profile_id, **kwargs: copy.deepcopy(chars)
    area = {"sources": {"alliances": [], "colony_constellations": [], "extra": ["Fictional Example Region"]},
            "systems": {"-115": {"system_id": -115, "name": "Demo Harbour", "security": -0.6,
                "region": "Fictional Example Region", "constellation_id": -115, "constellation": "Demo Coast",
                "neighbours": [], "planets": [{"planet_id": -1150 - i, "name": f"Demo Harbour {i}",
                    "type": kind} for i, kind in enumerate(("Barren", "Storm", "Oceanic"), 1)]}}}
    s = Settings(effort=50, selected_constellations=[-115], hub_system="Demo Harbour",
                 use_self_haul=True, use_buyback=False, use_local=False, use_jita=True)
    store.save_settings(pid, s)
    pi = build_from_rows([], [])
    result = {"totals": {"isk_per_day": 1200000, "isk_per_week": 8400000, "m3_per_week": 7000,
                 "systems": 1, "colonies": 0, "slots_total": 4, "restarts_per_week": 0, "factories": 0},
              "hub": "Demo Harbour", "characters": [], "colonies": [], "transfers": [], "removals": [],
              "templates_needed": [], "sold": [], "warnings": [], "solve_seconds": 0,
              "systems_in_scope": 1, "yield": {"head_yield": 1000, "calibrated": False},
              "selling": {"net_per_day": 1200000, "net_per_cycle": 8400000, "every_days": 7,
                          "dropoff": "Demo Harbour", "batches": []}, "channels": [], "channel_labels": {},
              "taxes": {"sales_tax_pct": 8, "broker_fee_pct": 3},
              "selling_coverage": {"local": False, "courier": False, "trade_hub": False}}
    # A labelled summary fixture, not an optimizer result or an in-game colony template.
    result["warnings"] = [{"text": "Fictional summary only: no colony allocation, live prices or templates.",
                           "level": "warn", "code": "demo", "steps": []}]

    async def space(*args, **kwargs):
        return copy.deepcopy(area)

    async def context(profile_id, settings=None, **kwargs):
        settings = settings or store.load_settings(pid)
        return dict(s=settings, solve_s=settings, chars=copy.deepcopy(chars), pi=pi, tpl=[], area=area,
                    systems={-115: area["systems"]["-115"]}, books={}, values={}, overrides={},
                    head_yield=1000, calibrated=False, dropoff="Demo Harbour", seller=None)

    service.load_space = space
    service.planning_context = context
    service.data_stamp = lambda profile_id: ("fictional-demo",)
    service.run_plan = lambda ctx, **kwargs: copy.deepcopy(result)
    service.first_build = lambda ctx, active: None
    original_overview = service.operate_overview

    def overview(*args, **kwargs):
        ov = original_overview(*args, **kwargs)
        ov["next_up"] = [dict(kind="view", level="info", href="#upkeep", verb="Check colonies in EVE",
                              where="Demo Harbour", system="Demo Harbour", character="Demo Pilot Aurora",
                              when="Example action")]
        return ov

    service.operate_overview = overview
    app = create_app()

    @app.get("/demo/{scene}")
    async def scene(request: Request, scene: str):
        destinations = {"characters": "/profile", "area": "/pi/area", "question": "/pi/plan",
                        "result": "/pi/plan?view=advanced", "operate": "/pi/operate"}
        if scene not in destinations:
            return PlainTextResponse("Choose characters, area, question, result or operate.", status_code=404)
        sessions.sign_in(request, pid)
        settings = store.load_settings(pid)
        settings.guide_step = 0
        store.save_settings(pid, settings)
        return RedirectResponse(destinations[scene], status_code=303)

    @app.middleware("http")
    async def screenshot_only(request, call_next):
        path = request.url.path
        if request.method != "GET":
            if path == "/pi/api/alternatives":
                return JSONResponse([{ "name": name, "effort": effort, "totals": result["totals"],
                                       "mix": "Fixed fictional summary; not optimized"}
                                      for name, effort in (("Set and forget", 0), ("Balanced", 50), ("Maximum ISK", 100))])
            if path == "/pi/api/save":
                return JSONResponse({"ok": True, "demo": True})  # acknowledge UI position without storing it
            if path == "/pi/api/whatif":
                body = await request.json()
                if body.get("prefetch"):
                    return JSONResponse({"queued": 0, "demo": True}, status_code=202)
                cards = [{"id": option.get("id"), **service.whatif_summary(result, s)}
                         for option in body.get("options", [])[:routes.WHATIF_OPTIONS]]
                if body.get("stream"):
                    events = [{"card": card} for card in cards] + [{"done": True}]
                    return PlainTextResponse("".join(json.dumps(event) + "\n" for event in events),
                                             media_type="application/x-ndjson")
                return JSONResponse(cards)
            if path == "/pi/api/preview":
                return JSONResponse({**copy.deepcopy(result), "preview": True,
                                     "baseline": store.plan_settings(s), "weights": time_weights(s)})
            if path == "/pi/api/suggest":
                return JSONResponse(result)
            if path == "/pi/api/sensitivity":
                return JSONResponse({"rows": [], "calibrated": False})
            return JSONResponse({"error": "Screenshot-only demo: actions and saving are disabled."}, status_code=403)
        if path.startswith(("/auth/", "/pi/export/", "/refresh")):
            return PlainTextResponse("Screenshot-only demo: EVE login, refresh and exports are disabled.", status_code=403)
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            body = b"".join([chunk async for chunk in response.body_iterator])
            banner = ('<aside style="position:sticky;top:0;z-index:100;padding:16px 16px 16px 96px;background:#ff7619;color:#111;font-weight:bold">'
                      'FICTIONAL DEMO · Screenshot-only · No EVE login or live pilot data. Fixed illustrative numbers; own-trip example, not an executable plan. '
                      '<a style="color:#111;text-decoration:underline" href="/demo/characters">Characters</a> · <a style="color:#111;text-decoration:underline" href="/demo/area">Area</a> · '
                      '<a style="color:#111;text-decoration:underline" href="/demo/question">Question</a> · <a style="color:#111;text-decoration:underline" href="/demo/result">Summary</a> · '
                      '<a style="color:#111;text-decoration:underline" href="/demo/operate">Operate</a></aside>')
            body = re.sub(rb'https://images\.evetech\.net/characters/[^"\s]+',
                          b'/static/img/mark.svg', body)
            start = body.find(b'>', body.find(b'<body')) + 1
            body = body[:start] + banner.encode() + body[start:]
            from starlette.responses import Response
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(body, status_code=response.status_code, headers=headers)
        return response

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=19115)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose an unprivileged local port between 1024 and 65535.")
    with tempfile.TemporaryDirectory(prefix="astracore-fictional-demo-") as tmp:
        isolated_environment(Path(tmp), args.port)
        import uvicorn
        print(f"Fictional screenshot preview: http://127.0.0.1:{args.port}/demo/characters")
        uvicorn.run(create_demo(), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
