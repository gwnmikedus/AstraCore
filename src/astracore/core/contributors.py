"""Public GitHub contributor credits, refreshed off the page-rendering path."""
from __future__ import annotations

import asyncio
import json
import re
import time
from functools import lru_cache
from pathlib import Path

import httpx

from astracore import db
from .project import REPOSITORY_URL

REFRESH_EVERY = 3600
RETRY_AFTER = 900
CACHE_KEY = f"project_contributors:{REPOSITORY_URL}"
_sync_lock = asyncio.Lock()
IDENTITIES = Path(__file__).resolve().parent.parent / "contributor_identities.json"


def _saved_snapshot() -> dict:
    return db.kv_get(CACHE_KEY, {"people": [], "last_success": 0, "next_poll_at": 0, "unavailable": False})


@lru_cache(maxsize=1)
def character_links() -> dict:
    """Opt-in public credits, independent of private AstraCore profiles."""
    links = {}
    for identity in json.loads(IDENTITIES.read_text(encoding="utf-8")):
        github_id = identity["github_id"]
        if type(github_id) is not int or github_id <= 0 or github_id in links:
            raise ValueError("Invalid or duplicate GitHub credit identity")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", identity["github_login"]):
            raise ValueError("Invalid GitHub credit login")
        characters = []
        for character in identity["characters"]:
            if (type(character["id"]) is not int or character["id"] <= 0
                    or not isinstance(character["name"], str) or not character["name"].strip()):
                raise ValueError("Invalid public character credit")
            characters.append({"id": character["id"], "name": character["name"],
                               "portrait_url": f"https://images.evetech.net/characters/{character['id']}/portrait?size=128"})
        links[github_id] = characters
    return links


def snapshot() -> dict:
    saved = _saved_snapshot()
    links = character_links()
    people = []
    for person in saved["people"]:
        github_id = person.get("github_id")
        if github_id is None:
            # Older snapshots encode the validated GitHub ID in the constructed avatar URL.
            match = re.fullmatch(r"https://avatars\.githubusercontent\.com/u/([0-9]+)\?s=128",
                                 person.get("avatar_url", ""))
            github_id = int(match[1]) if match else None
        people.append({**person, "characters": links.get(github_id, [])})
    return {**saved, "people": people}


def _person(value: dict) -> dict:
    login, user_id = value.get("login"), value.get("id")
    if (not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login)
            or type(user_id) is not int or user_id <= 0):
        raise ValueError("Incomplete contributor identity")
    # Construct public links from validated identities rather than accepting arbitrary URLs.
    return {"login": login, "github_id": user_id, "url": f"https://github.com/{login}",
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
        saved = _saved_snapshot()
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
