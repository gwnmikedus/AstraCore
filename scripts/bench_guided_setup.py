"""Measure how the guided setup feels when several pilots walk it at once (issue #85).

Runs against a COPY of a local database, never production:

    python scripts/bench_guided_setup.py --source path/to/astracore.sqlite3 --work /tmp/bench \
        --profile 1 --pilots 1 5 10 --think 3 [--client old|new] [--port 8791]

The script copies the source database into --work, clones --profile into N anonymous bench profiles (same
characters and settings under new ids, no tokens: they plan from the synced data only) and serves the app
on 127.0.0.1:--port. Each simulated pilot then walks the guided setup the way guide.html does: the cards of
every question, a pick, `--think` seconds of reading, the save, and finally the plan. `--client old` makes one
comparison request per question (main before #85); `--client new` streams the cards and asks the server to
warm the next question while the pilot reads. Market prices may be refreshed from public ESI.

Env: ASTRACORE_STATIC_DATA (SDE / templates), ASTRACORE_ENV_FILE, optionally ASTRACORE_SOLVE_CONCURRENCY.
Prints one JSON line per scenario: card wait per question (median / p95 / max), time to the first card,
and how long a pilot's whole walk took (including think time).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import statistics
import sys
import threading
import time
from pathlib import Path

SELL = {
    "nohaul": dict(use_self_haul=False, use_buyback=True, use_local=True, use_jita=False, use_amarr=False, use_sell_orders=False),
    "courier": dict(use_self_haul=False, use_buyback=True, use_local=True, use_jita=True, use_amarr=True, use_sell_orders=False),
    "self": dict(use_self_haul=True, use_buyback=False, use_local=False, use_jita=True, use_amarr=True, use_sell_orders=False),
    "orders": dict(use_self_haul=False, use_buyback=True, use_local=True, use_jita=True, use_amarr=True, use_sell_orders=True),
}
# The questions of guide.html (without the "custom" answer cards), in order.
STEPS = [
    ("goal", None),
    ("cycle", [(d, {"cycle_days": d}) for d in (1, 2, 3, 7)]),
    ("area", [("compact", {"max_systems": 1, "max_jumps": 1}), ("near", {"max_systems": 3, "max_jumps": 3}),
              ("wide", {"max_systems": 0, "max_jumps": 6})]),
    ("tier", [(t, {"max_tier": t}) for t in (1, 2, 3, 4)]),
    ("share", [(n, {"per_planet": n}) for n in (1, 2, 3)]),
    ("chain", [(b, {"cross_character": b}) for b in (False, True)]),
    ("sell", [(k, v) for k, v in SELL.items()]),
    ("batch", [(d, {"ship_every_days": d}) for d in (7, 14, 28)]),
]


def prepare(source: Path, work: Path, profile: int, count: int) -> list:
    """Copy the database and clone `profile` into `count` anonymous profiles. Returns their ids."""
    data = work / "data"
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(data / "astracore.sqlite3")
    src.backup(dst)
    src.close()
    c = dst.cursor()
    prof = c.execute("SELECT settings_json FROM profiles WHERE id=?", (profile,)).fetchone()
    if not prof:
        sys.exit(f"profile {profile} not found in the copy")
    chars = c.execute("SELECT * FROM characters WHERE profile_id=?", (profile,)).fetchall()
    cols = [d[0] for d in c.description]
    scopes = dict(c.execute("SELECT character_id, scopes FROM tokens"))
    settings = c.execute("SELECT module_id, settings_json FROM module_settings WHERE profile_id=?", (profile,)).fetchall()
    overrides = c.execute("SELECT planet_id, richness FROM planet_overrides WHERE profile_id=?", (profile,)).fetchall()
    area_keys = c.execute("SELECT key, value FROM kv WHERE key LIKE 'pi_last_area_query:%'").fetchall()
    ids = []
    for n in range(1, count + 1):
        c.execute("INSERT INTO profiles(created_at, display_name, settings_json, onboarded) VALUES (?, ?, ?, 1)",
                  (time.time(), f"Bench {n}", prof[0]))
        pid = c.lastrowid
        ids.append(pid)
        mapping = {}
        for i, row in enumerate(chars):
            r = dict(zip(cols, row))
            new = r["character_id"] + n * 10 ** 10
            mapping[str(r["character_id"])] = str(new)
            r.update(character_id=new, profile_id=pid, eve_account_id=None, name=f"Bench {n}.{i}", owner_hash=None)
            c.execute(f"INSERT INTO characters({','.join(r)}) VALUES ({','.join('?' * len(r))})", list(r.values()))
            c.execute("INSERT INTO tokens(character_id, refresh_token_enc, scopes) VALUES (?, 'bench-no-token', ?)",
                      (new, scopes.get(r["character_id"], "")))
        for module, js in settings:
            c.execute("INSERT INTO module_settings VALUES (?, ?, ?)", (pid, module, js))
        for planet, rich in overrides:
            c.execute("INSERT INTO planet_overrides VALUES (?, ?, ?)", (pid, planet, rich))
        for key, value in area_keys:   # the area the original characters were planned in
            head, _, tail = key.partition(":")
            ids_part, _, extra = tail.partition("|")
            new_ids = sorted(int(mapping.get(x, x)) for x in ids_part.split(","))
            c.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)",
                      (f"{head}:{','.join(map(str, new_ids))}|{extra}", value))
    dst.commit()
    dst.close()
    return ids


def serve(app, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server


def pct(xs, q):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2) if xs else None


async def walk(http, pid: int, client: str, think: float, stats: dict):
    from astracore.core import sessions
    raw, sess = sessions._create(pid, {"client": ("127.0.0.1", 0)}, {"user-agent": "bench"})
    h = {"X-CSRF-Token": sess["csrf"], "Cookie": f"{sessions.COOKIE}={raw}"}
    api = "/pi/api"

    async def post(path, body, stream=False):
        while True:
            if stream:
                cards, first, t0 = [], None, time.perf_counter()
                async with http.stream("POST", api + path, json=body, headers=h) as r:
                    if r.status_code == 503:
                        await asyncio.sleep(1)
                        continue
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        ev = json.loads(line)
                        if "card" in ev:
                            cards.append(ev["card"])
                            first = first or time.perf_counter() - t0
                        if ev.get("busy"):
                            break
                    else:
                        return cards, first
                await asyncio.sleep(1)
                continue
            r = await http.post(api + path, json=body, headers=h)
            if r.status_code == 503:
                stats["busy"] += 1
                await asyncio.sleep(3)
                continue
            return r.json(), None

    st = {}
    answered = []
    started = time.perf_counter()
    await post("/save", {"answered": [], "guide_step": 0})

    def options_of(step):
        return [{"id": i, "patch": p} for i, p in step[1]]

    for n, step in enumerate(STEPS):
        name, options = step
        if options:
            t0 = time.perf_counter()
            rows, first = await post("/whatif", {"base": st, "options": options_of(step), "stream": client == "new"},
                                     stream=client == "new")
            wait = time.perf_counter() - t0
            stats["wait"].append(wait)
            stats["first"].append(first if first is not None else wait)
            ok = [r for r in rows if isinstance(r, dict) and not r.get("error")]
            stats["cards"] += len(ok)
            stats["errors"] += len(rows) - len(ok)
            pick = max(ok, key=lambda r: r["totals"]["isk_per_day"])["id"] if ok else options[0][0]
            st.update(dict(options)[pick])
        else:
            st.update({"effort": 50})
        if client == "new" and n + 1 < len(STEPS):
            await http.post(api + "/whatif", json={"base": st, "options": options_of(STEPS[n + 1]), "prefetch": True},
                            headers=h)
        await asyncio.sleep(think)
        answered.append(name)
        await post("/save", {**st, "answered": answered, "guide_step": n + 1})
    t0 = time.perf_counter()
    res, _ = await post("/suggest", st)
    if client == "old" and not (res.get("yield") or {}).get("calibrated", True):
        await post("/sensitivity", {"base": {}})   # main loads the yield range with every result
    stats["plan"].append(time.perf_counter() - t0)
    stats["walk"].append(time.perf_counter() - started)


async def scenario(port: int, pids: list, client: str, think: float) -> dict:
    import httpx
    from astracore.core.solvegate import GATE
    GATE.clear()
    stats = {"wait": [], "first": [], "plan": [], "walk": [], "busy": 0, "cards": 0, "errors": 0}
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=300) as http:
        t0 = time.perf_counter()
        await asyncio.gather(*[walk(http, pid, client, think, stats) for pid in pids])
        total = time.perf_counter() - t0
    return {"pilots": len(pids), "client": client, "concurrency": GATE.concurrency, "think_s": think,
            "card_wait_median_s": pct(stats["wait"], 0.5), "card_wait_p95_s": pct(stats["wait"], 0.95),
            "card_wait_max_s": pct(stats["wait"], 1.0), "first_card_median_s": pct(stats["first"], 0.5),
            "first_card_p95_s": pct(stats["first"], 0.95), "plan_median_s": pct(stats["plan"], 0.5),
            "walk_median_s": pct(stats["walk"], 0.5), "walk_max_s": pct(stats["walk"], 1.0),
            "busy_retries": stats["busy"], "cards": stats["cards"], "card_errors": stats["errors"], "total_s": round(total, 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--profile", type=int, default=1)
    ap.add_argument("--pilots", type=int, nargs="+", default=[1, 5, 10])
    ap.add_argument("--think", type=float, default=3.0)
    ap.add_argument("--client", choices=["old", "new"], default="new")
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args()
    if args.port in range(8765, 8778):
        sys.exit("ports 8765-8777 are reserved for the app itself")
    pids = prepare(args.source, args.work, args.profile, sum(args.pilots) + 1)
    os.environ.update(ASTRACORE_DATA=str(args.work / "data"), ASTRACORE_MODE="local")
    from astracore.app import app
    serve(app, args.port)

    async def warm():   # load static data and refresh prices once, outside the measurement
        from astracore.modules.pi import service
        await service.planning_context(pids[-1], persist_default=False)
    asyncio.run(warm())
    used = 0
    for n in args.pilots:
        print(json.dumps(asyncio.run(scenario(args.port, pids[used:used + n], args.client, args.think))), flush=True)
        used += n


if __name__ == "__main__":
    main()
