"""Release history shipped with this running application, independent of GitHub availability."""
from __future__ import annotations

import json
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .project import REPOSITORY_URL

RELEASE_DATA = Path(__file__).resolve().parent.parent / "release_data.json"
VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{7,40}")


def validate(data: dict, expected_version: Optional[str] = None) -> None:
    """Reject inconsistent history before publishing or serving it."""
    if not isinstance(data, dict):
        raise ValueError("release metadata must be an object")
    version = data.get("current_version", "")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ValueError("current_version must be a semantic version such as 1.1.0")
    if expected_version is not None and version != expected_version:
        raise ValueError("release data and package version must match")
    entries = data.get("releases")
    if not isinstance(entries, list) or not entries:
        raise ValueError("release history must contain at least one entry")
    seen = set()
    previous_version = None
    previous_date = None
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("release entries must be objects")
        entry_version = entry.get("version", "")
        if not isinstance(entry_version, str) or not VERSION_PATTERN.fullmatch(entry_version):
            raise ValueError("each release needs a semantic version")
        if entry_version in seen:
            raise ValueError("release versions must be unique")
        seen.add(entry_version)
        ordered_version = tuple(int(part) for part in entry_version.split("."))
        if previous_version is not None and ordered_version >= previous_version:
            raise ValueError("release history must be newest first")
        previous_version = ordered_version
        if not isinstance(entry.get("title"), str) or not entry["title"].strip():
            raise ValueError("each release needs a title")
        released = entry.get("date")
        if released is None:
            if entry.get("kind") != "baseline":
                raise ValueError("only a historical baseline may omit its date")
        else:
            if not isinstance(released, str):
                raise ValueError("release dates must use YYYY-MM-DD")
            try:
                parsed = date.fromisoformat(released)
            except ValueError as exc:
                raise ValueError("release dates must use YYYY-MM-DD") from exc
            if parsed.isoformat() != released:
                raise ValueError("release dates must use YYYY-MM-DD")
            if previous_date is not None and parsed > previous_date:
                raise ValueError("release dates must be newest first")
            previous_date = parsed
        for field in ("changes", "technical", "limitations"):
            items = entry.get(field)
            if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
                raise ValueError(f"{field} must contain nonempty text entries")
        if not entry["changes"] and not entry["technical"]:
            raise ValueError("a release needs user-facing or technical changes")
        references = entry.get("references", [])
        if not isinstance(references, list):
            raise ValueError("references must be a list")
        for reference in references:
            if not isinstance(reference, dict) or not isinstance(reference.get("label"), str) or not reference["label"].strip():
                raise ValueError("release references need a label")
            url = reference.get("url", "")
            if not isinstance(url, str) or not url.startswith(REPOSITORY_URL + "/"):
                raise ValueError("release references must link to the project repository")
    if entries[0]["version"] != version:
        raise ValueError("the first release must match current_version")


@lru_cache(maxsize=1)
def _data() -> dict:
    data = json.loads(RELEASE_DATA.read_text(encoding="utf-8"))
    validate(data)
    return data


def history() -> list:
    return _data()["releases"]


def current() -> dict:
    data = _data()
    commit = os.environ.get("ASTRACORE_COMMIT", "").strip().lower()
    if not COMMIT_PATTERN.fullmatch(commit):
        commit = ""
    return {
        "version": data["current_version"],
        "entry": data["releases"][0],
        "commit": commit,
        "commit_url": f"{REPOSITORY_URL}/commit/{commit}" if commit else "",
    }
