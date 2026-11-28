"""Capsuleer's logbook: which easter eggs a pilot found, and an opt-in ranking (docs/easter-eggs.md).

The easter eggs are intentional. Finds are reported by the browser (js/easter-eggs.js), so they are a game, not
proof: anyone can claim one with a request. Calendar eggs are checked against the server's clock, so the
high-value ones at least need the right day. A pilot appears on the ranking only after choosing one of their own
characters for it; removing that character, the choice or the profile takes them off without a trace.

LOGBOOK_SCHEMA is added by migration v10 and is additive only, so a rollback to an older build keeps working.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from astracore import db

from . import sessions
from .web import redirect, render

router = APIRouter()

LOGBOOK_SCHEMA = """
CREATE TABLE IF NOT EXISTS logbook_finds (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    egg TEXT NOT NULL, found_at REAL NOT NULL,
    PRIMARY KEY(profile_id, egg)
);
CREATE INDEX IF NOT EXISTS logbook_finds_egg ON logbook_finds(egg, found_at);
CREATE TABLE IF NOT EXISTS logbook_ranking (
    profile_id INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL, created_at REAL NOT NULL
);
"""

# The logbook opens once a pilot has found this many.
UNLOCK = 3
RANKING_SIZE = 50


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def _on_day(month: int, days: range) -> Callable[[float], bool]:
    # The browser decides on its UTC date; an hour of slack either side covers a slow request around midnight.
    def check(ts: float) -> bool:
        return any(d.month == month and d.day in days
                   for d in (_utc(ts - 3600), _utc(ts), _utc(ts + 3600)))
    return check


def _downtime(ts: float) -> bool:
    return any(d.hour == 11 and d.minute < 30 for d in (_utc(ts - 300), _utc(ts), _utc(ts + 300)))


# id, title, hint while not found, points, optional server-side check of when it can be found.
# Order is the order on the logbook page: easy first, calendar ones last.
EGGS = (
    {"id": "flashbang", "title": "Flashbang warning", "points": 1,
     "hint": "The theme switch has opinions about your eyes. Ask it in the dark."},
    {"id": "yc_year", "title": "YC 128", "points": 1,
     "hint": "Even the copyright line counts in New Eden years."},
    {"id": "logo", "title": "o7 from the logo", "points": 1,
     "hint": "The small logo in the footer likes attention. Lots of it, quickly."},
    {"id": "o7", "title": "o7", "points": 1,
     "hint": "Say what capsuleers say. Anywhere but in a text field."},
    {"id": "not_on_overview", "title": "Not on your overview", "points": 2,
     "hint": "Get lost. Then look closely at where you ended up."},
    {"id": "theme_flip", "title": "Make up your mind", "points": 2,
     "hint": "Light, dark, light, dark, light, dark."},
    {"id": "konami", "title": "Cheat code", "points": 2,
     "hint": "Some codes are older than New Eden. Up, up…"},
    {"id": "console", "title": "Console capsuleer", "points": 2,
     "hint": "Pilots who read the source get a hello. Say one back."},
    {"id": "rare_tip", "title": "The rare tip", "points": 3,
     "hint": "One footer tip in fifty is special."},
    {"id": "long_session", "title": "An hour of planning", "points": 3,
     "hint": "Patience. About an hour of it, on one page."},
    {"id": "downtime", "title": "Downtime", "points": 3, "check": _downtime,
     "hint": "Visit while Tranquility naps, from 11:00 UTC."},
    {"id": "birthday", "title": "New Eden's birthday", "points": 5, "check": _on_day(5, range(6, 7)),
     "hint": "Come back on the day EVE first undocked."},
    {"id": "april_fools", "title": "Check the date", "points": 5, "check": _on_day(4, range(1, 2)),
     "hint": "One day a year, our tips can't be trusted."},
    {"id": "holidays", "title": "Customs never closes", "points": 5, "check": _on_day(12, range(24, 27)),
     "hint": "Visit during the winter holidays."},
    {"id": "new_year", "title": "New extractor cycle", "points": 5, "check": _on_day(1, range(1, 2)),
     "hint": "Be here on the first day of the year."},
)
EGG_BY_ID: Dict[str, dict] = {e["id"]: e for e in EGGS}
TOTAL = len(EGGS)


def can_find(egg: str, now: Optional[float] = None) -> bool:
    item = EGG_BY_ID.get(egg)
    if not item:
        return False
    check = item.get("check")
    return check is None or check(time.time() if now is None else now)


def finds(profile_id: int) -> Dict[str, float]:
    with db.session() as c:
        return {r["egg"]: r["found_at"] for r in c.execute(
            "SELECT egg, found_at FROM logbook_finds WHERE profile_id=?", (profile_id,)) if r["egg"] in EGG_BY_ID}


def record(profile_id: int, eggs: List[str], now: Optional[float] = None) -> List[str]:
    """Store the eggs that are real and findable right now; returns the ones that are new for this pilot."""
    now = time.time() if now is None else now
    new = []
    with db.session() as c:
        for egg in dict.fromkeys(eggs):
            if not can_find(egg, now):
                continue
            cur = c.execute("INSERT OR IGNORE INTO logbook_finds(profile_id, egg, found_at) VALUES(?,?,?)",
                            (profile_id, egg, now))
            if cur.rowcount:
                new.append(egg)
    return new


def points(found: Dict[str, float]) -> int:
    return sum(EGG_BY_ID[e]["points"] for e in found)


def state(user: Optional[dict]) -> dict:
    """What the footer line needs: found ids, count, total and whether the logbook is open."""
    found = finds(user["id"]) if user else {}
    return {"found": sorted(found), "count": len(found), "total": TOTAL, "unlock": UNLOCK,
            "open": bool(user) and len(found) >= UNLOCK, "signed_in": bool(user)}


def ranking_choice(profile_id: int) -> Optional[int]:
    with db.session() as c:
        r = c.execute("SELECT lr.character_id FROM logbook_ranking lr JOIN characters ch "
                      "ON ch.character_id=lr.character_id AND ch.profile_id=lr.profile_id WHERE lr.profile_id=?",
                      (profile_id,)).fetchone()
    return r["character_id"] if r else None


def set_ranking(profile_id: int, character_id: Optional[int]) -> bool:
    """Opt in with one of the pilot's own characters, or None to leave the ranking."""
    with db.session() as c:
        if character_id is None:
            c.execute("DELETE FROM logbook_ranking WHERE profile_id=?", (profile_id,))
            return True
        owned = c.execute("SELECT 1 FROM characters WHERE character_id=? AND profile_id=?",
                          (character_id, profile_id)).fetchone()
        if not owned:
            return False
        c.execute("INSERT INTO logbook_ranking(profile_id, character_id, created_at) VALUES(?,?,?) "
                  "ON CONFLICT(profile_id) DO UPDATE SET character_id=excluded.character_id, created_at=excluded.created_at",
                  (profile_id, character_id, time.time()))
    return True


def _public_pilots(c) -> Dict[int, dict]:
    """profile id -> the character it chose for the ranking, only while that character is still theirs."""
    return {r["profile_id"]: {"character_id": r["character_id"], "name": r["name"]} for r in c.execute(
        "SELECT lr.profile_id, ch.character_id, ch.name FROM logbook_ranking lr JOIN characters ch "
        "ON ch.character_id=lr.character_id AND ch.profile_id=lr.profile_id")}


def ranking() -> dict:
    """Opted-in pilots by points, then by who got there first; plus first finders and how many hunt in private."""
    with db.session() as c:
        public = _public_pilots(c)
        rows = c.execute("SELECT profile_id, egg, found_at FROM logbook_finds ORDER BY found_at").fetchall()
    per: Dict[int, dict] = {}
    first: Dict[str, Optional[dict]] = {}
    found_by: Dict[str, int] = {}
    for r in rows:
        egg = r["egg"]
        if egg not in EGG_BY_ID:
            continue
        p = per.setdefault(r["profile_id"], {"eggs": 0, "points": 0, "last": 0.0})
        p["eggs"] += 1
        p["points"] += EGG_BY_ID[egg]["points"]
        p["last"] = max(p["last"], r["found_at"])
        found_by[egg] = found_by.get(egg, 0) + 1
        if egg not in first:   # rows come oldest first: the first row per egg is its first finder
            first[egg] = public.get(r["profile_id"])
    hunters = [pid for pid, p in per.items() if p["eggs"] >= UNLOCK]
    board = sorted(({"profile_id": pid, **public[pid], **per[pid]} for pid in hunters if pid in public),
                   key=lambda x: (-x["points"], -x["eggs"], x["last"]))
    for i, row in enumerate(board, start=1):
        row["rank"] = i
    return {"board": board[:RANKING_SIZE], "all": board, "first": first, "found_by": found_by,
            "private": len([pid for pid in hunters if pid not in public]), "hunters": len(hunters)}


# --------------------------------------------------------------------------- routes
def _not_found(request: Request):
    return render(request, "error.html", page="error", page_title="Not found", code=404,
                  message="This page doesn't exist.", status_code=404)


@router.post("/logbook/found")
async def logbook_found(request: Request):
    user = sessions.require_user(request)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad request")
    eggs = body.get("eggs") if isinstance(body, dict) else None
    if not isinstance(eggs, list) or len(eggs) > TOTAL or not all(isinstance(e, str) for e in eggs):
        raise HTTPException(status_code=400, detail="Bad request")
    before = len(finds(user["id"]))
    new = record(user["id"], eggs)
    found = finds(user["id"])
    return JSONResponse({"new": new, "found": sorted(found), "count": len(found), "total": TOTAL,
                         "open": len(found) >= UNLOCK, "opened": before < UNLOCK <= len(found)})


@router.get("/logbook")
async def logbook_page(request: Request):
    user = request.state.user
    if not user:
        return _not_found(request)
    found = finds(user["id"])
    if len(found) < UNLOCK:   # hidden until it's earned: it looks like any missing page
        return _not_found(request)
    board = ranking()
    mine = next((row for row in board["all"] if row["profile_id"] == user["id"]), None)
    from .community import own_characters
    return render(request, "logbook.html", page="logbook", page_title="Capsuleer's logbook",
                  eggs=EGGS, found=found, my_points=points(found), total=TOTAL,
                  total_points=sum(e["points"] for e in EGGS), board=board, mine=mine,
                  characters=own_characters(user["id"]), choice=ranking_choice(user["id"]),
                  utc=_utc)


@router.post("/logbook/ranking")
async def logbook_ranking(request: Request):
    user = sessions.require_user(request)
    if len(finds(user["id"])) < UNLOCK:
        return _not_found(request)
    form = await request.form()
    value = str(form.get("character_id") or "").strip()
    digits = value[1:] if value.startswith("-") else value
    character_id = int(value) if digits.isdigit() and len(digits) < 16 else None
    if value and character_id is None:
        return redirect("/logbook#ranking", "Choose one of your characters.", "warn")
    if not set_ranking(user["id"], character_id):
        return redirect("/logbook#ranking", "Choose one of your own characters.", "warn")
    return redirect("/logbook#ranking", "You're on the ranking. It updates as you find more." if character_id
                    else "You're off the ranking. Your finds stay in your logbook.", "ok")

