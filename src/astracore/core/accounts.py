"""Profiles and characters: linking, moving, merging, removing, resetting, the invite gate, data export."""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from astracore import config, db

from . import registry

log = logging.getLogger("astracore")


async def _revoke(character_id: int) -> bool:
    from astracore.esi import sso
    t = db.get_token(character_id)
    return await sso.revoke(t["refresh_token"]) if t else False


def _fix_main(profile_id: int) -> None:
    p = db.get_profile(profile_id)
    chars = db.list_characters(profile_id)
    if p and chars and p["main_character_id"] not in {c["character_id"] for c in chars}:
        db.update_profile(profile_id, main_character_id=chars[0]["character_id"], display_name=chars[0]["name"])


async def unlink_character(profile_id: int, character_id: int, revoke_token: bool = True) -> bool:
    """Remove a character from a profile: revoke its EVE token, delete token + synced data, strip it from
    module data (saved plans). The profile itself stays, even with no characters left (the caller decides)."""
    ch = db.owned_character(profile_id, character_id)
    if not ch:
        return False
    if revoke_token:
        await _revoke(character_id)
    db.delete_character(character_id)
    for m in registry.MODULES:
        if m.on_character_removed:
            m.on_character_removed(profile_id, character_id)
    _fix_main(profile_id)
    return True


async def reset_profile(profile_id: int) -> int:
    """Delete everything: revoke every token with EVE SSO, then the profile and all its rows."""
    n = 0
    for ch in db.list_characters(profile_id):
        if await _revoke(ch["character_id"]):
            n += 1
    for m in registry.MODULES:
        if m.on_profile_reset:
            m.on_profile_reset(profile_id)
    db.delete_profile(profile_id)
    return n


def move_character(character_id: int, to_profile: int) -> Optional[int]:
    """Move a character (ownership just proven by a fresh SSO login) to another profile.
    Returns the profile it came from. A source profile left without characters is deleted."""
    ch = db.get_character(character_id)
    if not ch or ch["profile_id"] == to_profile:
        return None
    src = ch["profile_id"]
    db.link_character(character_id, to_profile, ch["name"])
    for m in registry.MODULES:
        if m.on_character_removed:
            m.on_character_removed(src, character_id)
    if not db.list_characters(src):
        db.delete_profile(src)
    else:
        _fix_main(src)
    return src


def merge_profiles(src: int, dst: int) -> None:
    """Fold profile `src` into `dst`: characters, EVE accounts and saved plans move; planet overrides move
    where dst has none; dst's settings win. `src` is deleted afterwards (its sessions too)."""
    if src == dst:
        return
    with db.session() as c:
        c.execute("UPDATE eve_accounts SET profile_id=? WHERE profile_id=?", (dst, src))
        c.execute("UPDATE characters SET profile_id=? WHERE profile_id=?", (dst, src))
        c.execute("UPDATE plan_runs SET profile_id=?, active=0 WHERE profile_id=?", (dst, src))
        c.execute("UPDATE community_feedback SET profile_id=? WHERE profile_id=?", (dst, src))
        c.execute("INSERT OR IGNORE INTO community_votes(profile_id, target, created_at) "
                  "SELECT ?, target, created_at FROM community_votes WHERE profile_id=?", (dst, src))
        c.execute("INSERT OR IGNORE INTO planet_overrides(profile_id, planet_id, richness) "
                  "SELECT ?, planet_id, richness FROM planet_overrides WHERE profile_id=?", (dst, src))
    db.delete_profile(src)
    _fix_main(dst)


# --------------------------------------------------------------------------- invite gate
def member_groups() -> dict:
    """The corporation/alliance whose members may always log in (landing and invite-only pages).

    Each group keeps its exact EVE name (``name``) and gets ``label``, the name for running text: a
    trailing full stop ("Insidious.") would otherwise end the sentence it is joined into. ``phrase``
    joins the labels ("Dutch Legions and Insidious")."""
    from astracore.core import eveimg
    groups = eveimg.home_groups()
    out = {}
    for kind in ("corporation", "alliance"):
        group = groups.get(kind)
        if group and (group["id"] in config.ALLOWED[kind] or not config.ACCESS_GATE):
            out[kind] = {**group, "label": group["name"].rstrip(". ") or group["name"]}
    if out:
        out["phrase"] = " and ".join(g["label"] for g in out.values())
    return out


def gate_allows(character_id: int, corporation_id: Optional[int], alliance_id: Optional[int]) -> bool:
    """Production invite list: a login passes if the character, its corporation or its alliance is listed
    (in the env file or on the admin page). Local mode has no gate."""
    if not config.ACCESS_GATE:
        return True
    if character_id in config.ADMIN_CHARACTER_IDS:
        return True
    allowed = {k: set(v) for k, v in config.ALLOWED.items()}
    for row in db.access_list():
        allowed.setdefault(row["kind"], set()).add(int(row["entity_id"]))
    return (character_id in allowed.get("character", set())
            or (corporation_id is not None and corporation_id in allowed.get("corporation", set()))
            or (alliance_id is not None and alliance_id in allowed.get("alliance", set())))


# --------------------------------------------------------------------------- export
def export_profile(profile_id: int) -> Dict:
    """Everything stored for the profile, as JSON. Tokens are left out (they're secrets, not your data)."""
    p = db.get_profile(profile_id) or {}
    chars: List[dict] = []
    for ch in db.list_characters(profile_id):
        ch = dict(ch)
        ch.pop("has_token", None)
        chars.append(ch)
    with db.session() as c:
        plans = [dict(r) for r in c.execute("SELECT id, created, label, active, settings_json, result_json "
                                            "FROM plan_runs WHERE profile_id=?", (profile_id,))]
        overrides = [dict(r) for r in c.execute("SELECT planet_id, richness FROM planet_overrides WHERE profile_id=?",
                                                (profile_id,))]
        modset = [dict(r) for r in c.execute("SELECT module_id, settings_json FROM module_settings WHERE profile_id=?",
                                             (profile_id,))]
        sessions = [dict(r) for r in c.execute("SELECT created_at, last_seen_at, user_agent, ip_hint FROM sessions "
                                               "WHERE profile_id=?", (profile_id,))]
        # Your bug reports and ideas, with where they went (published ones also live on GitHub).
        feedback = [dict(r) for r in c.execute(
            "SELECT id, kind, title, body, version, created_at, updated_at, delivery, issue_number "
            "FROM community_feedback WHERE profile_id=? ORDER BY created_at", (profile_id,))]
    return {"exported_at": time.time(), "profile": p, "eve_accounts": db.list_accounts(profile_id),
            "characters": chars, "module_settings": modset, "plans": plans, "planet_overrides": overrides,
            "sessions": sessions, "feedback": feedback}
