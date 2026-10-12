"""Refresh on visit (#75): Home and Operate read characters again when their data is getting old.

The page renders at once from what is stored and says how old it is; when it's older than
`REFRESH_AFTER`, a small script asks `/refresh/auto` to read the stale characters from ESI and
reloads the page when that's done. The ESI client still only fetches routes whose `Expires` has
passed, and a profile reads ESI at most every `pages.REFRESH_EVERY` seconds, by hand or on a visit.

One refresh per profile runs at a time: a second tab (or Home, then Operate) waits for the same one.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

from astracore import db

log = logging.getLogger("astracore")
REFRESH_AFTER = 15 * 60      # data older than this is read again when the pilot opens Home or Operate
FRESH_FOR = 60 * 60          # "Updated 40 min ago" is still green; older is amber
COLONY_NOTE = ("ESI only updates a colony after you open it in game, so stock and storage are projected "
               "from the last time you looked at it there.")

_running: Dict[int, asyncio.Task] = {}


def _refresh_every() -> int:
    from .pages import REFRESH_EVERY
    return REFRESH_EVERY


def refreshable(profile_id: int) -> List[dict]:
    """Characters Home and Operate show that AstraCore can read: included, with a working EVE login."""
    return [c for c in db.list_characters(profile_id, enabled_only=True)
            if c.get("has_token") and c.get("status") != "needs_login"]


def stale_ids(profile_id: int, now: Optional[float] = None) -> set:
    now = time.time() if now is None else now
    return {c["character_id"] for c in refreshable(profile_id)
            if now - (c.get("synced_at") or 0) > REFRESH_AFTER}


def refresh_wait(profile_id: int, now: Optional[float] = None) -> int:
    """Seconds until this profile may read ESI again."""
    now = time.time() if now is None else now
    last = (db.get_profile(profile_id) or {}).get("last_esi_refresh_at") or 0
    return max(0, int(_refresh_every() - (now - last)))


def running(profile_id: int) -> bool:
    t = _running.get(profile_id)
    return bool(t and not t.done())


def state(profile_id: int, now: Optional[float] = None) -> dict:
    """The freshness line: when the shown data was read, and whether the page should refresh it."""
    now = time.time() if now is None else now
    chars = refreshable(profile_id)
    times = [c.get("synced_at") or 0 for c in chars]
    oldest = min(times) if times else None
    stale = [c for c in chars if now - (c.get("synced_at") or 0) > REFRESH_AFTER]
    auto = bool(stale) and (running(profile_id) or refresh_wait(profile_id, now) == 0)
    # name characters only when they differ: one old character among fresh ones
    behind = [{"name": c["name"], "synced_at": c.get("synced_at") or 0} for c in stale] \
        if stale and len(stale) < len(chars) else []
    return {"synced_at": oldest or None, "age": None if not oldest else now - oldest,
            "fresh": bool(oldest) and now - oldest <= FRESH_FOR, "stale": bool(stale), "auto": auto,
            "behind": behind, "characters": len(chars)}


async def refresh_stale(profile_id: int) -> dict:
    """Read the profile's stale characters from ESI, or wait for the refresh already running.
    Returns {"refreshed": bool, "problems": {name: problem}, "wait": seconds}."""
    task = _running.get(profile_id)
    if task is None or task.done():
        ids = stale_ids(profile_id)
        wait = refresh_wait(profile_id)
        if not ids or wait:
            return {"refreshed": False, "problems": {}, "wait": wait}
        db.update_profile(profile_id, last_esi_refresh_at=time.time())
        from astracore.modules.pi.service import refresh_profile
        task = asyncio.get_running_loop().create_task(refresh_profile(profile_id, ids=ids))
        _running[profile_id] = task
        task.add_done_callback(lambda t, pid=profile_id: _running.pop(pid, None) if _running.get(pid) is t else None)
    try:
        # shielded: a pilot leaving the page mid-refresh doesn't cut it off
        problems = await asyncio.shield(task)
    except Exception:  # noqa: BLE001 - the page keeps showing the stored data
        log.exception("refresh on visit")
        return {"refreshed": False, "problems": {"ESI": "refresh failed"}, "wait": 0}
    return {"refreshed": True, "problems": problems or {}, "wait": 0}
