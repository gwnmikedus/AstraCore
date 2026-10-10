"""Public GitHub contributor credits, refreshed off the page-rendering path."""
from __future__ import annotations

import asyncio
import re
import time

import httpx

from astracore import db
from .project import REPOSITORY_URL

REFRESH_EVERY = 3600
RETRY_AFTER = 900
CACHE_KEY = f"project_contributors:{REPOSITORY_URL}"
_sync_lock = asyncio.Lock()


def snapshot() -> dict:
    return db.kv_get(CACHE_KEY, {"people": [], "last_success": 0, "next_poll_at": 0, "unavailable": False})


def _person(value: dict) -> dict:
    login, user_id = value.get("login"), value.get("id")
    if (not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login)
            or type(user_id) is not int or user_id <= 0):
        raise ValueError("Incomplete contributor identity")
    # Construct public links from validated identities rather than accepting arbitrary URLs.
    return {"login": login, "url": f"https://github.com/{login}",
            "avatar_url": f"https://avatars.githubusercontent.com/u/{user_id}?s=128"}


async def _fetch(client: httpx.AsyncClient) -> list:
    people = {}
    repository = REPOSITORY_URL.removeprefix("https://github.com/")
    for page in range(1, 101):
        response = await client.get(f"https://api.github.com/repos/{repository}/contributors",
                                    params={"per_page": 100, "page": page})
        response.raise_for_status()
        if response.status_code == 204:
            if page != 1:
                raise ValueError("Incomplete contributor listing")
            return []
        if response.status_code != 200:
            raise ValueError("Contributor listing is not ready")
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Unexpected contributor listing")
        for value in batch:
            if not isinstance(value, dict) or value.get("type") not in ("User", "Bot", "Anonymous"):
                raise ValueError("Unexpected contributor identity")
            if value["type"] == "User":
                person = _person(value)
                people[person["login"].lower()] = person
        if len(batch) < 100:
            return sorted(people.values(), key=lambda person: person["login"].lower())
    raise ValueError("Incomplete contributor listing")


async def sync_once(*, force: bool = False, transport=None) -> None:
    if _sync_lock.locked():
        return
    async with _sync_lock:
        saved = snapshot()
        now = time.time()
        if not force and saved["next_poll_at"] > now:
            return
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10",
                   "User-Agent": "AstraCore contributor credits"}
        try:
            # Public metadata needs no token or extra permissions on the Issues integration.
            async with httpx.AsyncClient(timeout=15, headers=headers, transport=transport) as client:
                people = await _fetch(client)
        except (httpx.HTTPError, ValueError):
            db.kv_set(CACHE_KEY, {**saved, "next_poll_at": now + RETRY_AFTER, "unavailable": True})
            return
        db.kv_set(CACHE_KEY, {"people": people, "last_success": time.time(),
                              "next_poll_at": now + REFRESH_EVERY, "unavailable": False})
