"""Sign-in, adding characters and scope changes, all through EVE SSO.

| Situation                                              | Result                                            |
|--------------------------------------------------------|---------------------------------------------------|
| signed out, character linked to a profile              | sign in to that profile, update its token         |
| signed out, character unknown                          | new profile (invite gate in production), onboarding |
| signed in, add, character unknown                      | link it to the current profile                    |
| signed in, add, character already in this profile      | refresh its token/scopes ("updated")              |
| signed in, add, character linked to another profile    | ask: move it here (or merge, if it was the last one) |
| upgrade for X but SSO returned Y                       | handled as "add Y", with a note which one was authorised |

The `state` sent to EVE is single-use, expires after 10 minutes and is bound to this browser's
session cookie and to the intent (login / add / upgrade:<character_id>).
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from typing import List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from astracore import db
from astracore.esi import sso

from . import accounts, registry, sessions
from .crypto import decrypt, encrypt
from .web import redirect, render

log = logging.getLogger("astracore")
router = APIRouter()
STATE_TTL = 600


# --------------------------------------------------------------------------- state
def _new_state(sess: dict, intent: str, data: Optional[dict] = None) -> str:
    state = secrets.token_urlsafe(24)
    with db.session() as c:
        c.execute("DELETE FROM sso_states WHERE created_at < ?", (time.time() - STATE_TTL,))
        c.execute("INSERT INTO sso_states(state, session_hash, intent, data_json, created_at) VALUES(?,?,?,?,?)",
                  (state, sess["id_hash"], intent, json.dumps(data or {}), time.time()))
    return state


def _take_state(state: str, sess: Optional[dict]) -> Optional[dict]:
    """Single use: the row is deleted whether or not it matches."""
    if not state:
        return None
    with db.session() as c:
        r = c.execute("SELECT * FROM sso_states WHERE state=?", (state,)).fetchone()
        c.execute("DELETE FROM sso_states WHERE state=?", (state,))
    if not r or not sess or r["session_hash"] != sess["id_hash"] or time.time() - r["created_at"] > STATE_TTL:
        return None
    return {"intent": r["intent"], "data": json.loads(r["data_json"] or "{}")}


# --------------------------------------------------------------------------- scopes
def bundle_active(ch: dict, bundle_id: str) -> bool:
    """Granted by the character's token and not switched off by the user."""
    b = registry.bundle(bundle_id)
    if not b or not set(b.scopes) <= set(ch.get("scopes") or []):
        return False
    return (ch.get("bundle_prefs") or {}).get(bundle_id, True) is not False


def missing_required(ch: dict, module_id: str) -> bool:
    m = registry.get(module_id)
    return bool(m) and not set(m.required_bundle.scopes) <= set(ch.get("scopes") or [])


def scopes_for_bundles(bundle_ids: List[str]) -> List[str]:
    out: List[str] = list(registry.signin_scopes())
    for bid in bundle_ids:
        b = registry.bundle(bid)
        if b:
            out += [s for s in b.scopes if s not in out]
    return out


def active_optional(ch: dict) -> List[str]:
    return [b.id for m in registry.MODULES for b in m.optional_bundles if bundle_active(ch, b.id)]


# --------------------------------------------------------------------------- routes: start
@router.get("/auth/login")
async def login(request: Request, intent: str = "login", next: str = ""):
    if not sso.configured():
        return redirect("/", "The EVE application isn't configured for this site yet.", "bad")
    sess = sessions.ensure(request)
    intent = "add" if request.state.user and intent == "add" else "login"
    if request.state.user and intent == "login":
        intent = "add"
    destination = next if next in ("/feedback", "/roadmap") else ""
    state = _new_state(sess, intent, {"next": destination})
    return RedirectResponse(sso.authorize_url(state, registry.signin_scopes()), status_code=303)


@router.get("/auth/community")
async def community_login(request: Request):
    if request.state.user:
        return RedirectResponse("/feedback", status_code=303)
    return await login(request, next="/feedback")


@router.get("/auth/upgrade/{character_id}")
async def upgrade(request: Request, character_id: int, bundle: str = "", action: str = "on"):
    """Re-login one character with a different set of optional bundles (on = add `bundle`, off = drop it).
    No bundle = just log in again with what it has (e.g. "needs login")."""
    user = request.state.user
    if not user:
        return redirect("/", "Sign in first.")
    ch = db.owned_character(user["id"], character_id)
    if not ch:
        return redirect("/profile", "That character isn't in your profile.", "bad")
    want = set(active_optional(ch))
    if bundle and registry.bundle(bundle):
        (want.add if action == "on" else want.discard)(bundle)
    sess = sessions.ensure(request)
    state = _new_state(sess, f"upgrade:{character_id}", {"bundles": sorted(want), "bundle": bundle, "action": action})
    return RedirectResponse(sso.authorize_url(state, scopes_for_bundles(sorted(want))), status_code=303)


# --------------------------------------------------------------------------- routes: callback
async def _affiliation(character_id: int) -> dict:
    from astracore.esi import character as esi_char
    from astracore.esi.client import ESIClient
    try:
        async with ESIClient() as esi:
            return await esi_char.affiliation(esi, character_id)
    except Exception:  # noqa: BLE001 - affiliation is best effort; gate then only matches by character
        log.warning("affiliation lookup failed for %s", character_id)
        return {}


async def _store_token(login: dict, keep_superset: bool = True) -> None:
    """Save the fresh token. On a plain sign-in, a stored token with *more* scopes (opted-in bundles) is
    kept and the new one revoked, so signing in never silently drops an optional bundle."""
    cid = login["character_id"]
    old = db.get_token(cid)
    new_scopes = set(login["scopes"].split())
    if keep_superset and old and old["refresh_token"] and new_scopes < set(old["scopes"].split()):
        await sso.revoke(login["refresh_token"])
        return
    db.save_token(cid, login["refresh_token"], login["access_token"], login["expires_in"], login["scopes"])
    if old and old["refresh_token"] and old["refresh_token"] != login["refresh_token"]:
        await sso.revoke(old["refresh_token"])


async def _refresh_character(character_id: int) -> str:
    """Read the character's data from ESI right after login. Returns '' or a short problem description."""
    from astracore.esi import character as esi_char
    from astracore.esi.client import ESIClient
    try:
        async with ESIClient() as esi:
            await esi_char.sync_character(esi, character_id)
        return ""
    except Exception as e:  # noqa: BLE001 - show ESI trouble, never fail the login over it
        log.warning("ESI sync after login failed for %s: %s", character_id, e)
        return "reading its data from ESI failed for now; it will be retried on the next refresh"


def _link_new(profile_id: int, login: dict, aff: dict) -> None:
    db.link_character(login["character_id"], profile_id, login["name"], login["owner"])
    if aff:
        db.set_character(login["character_id"], **{k: v for k, v in aff.items() if v is not None})


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    sess = request.state.session
    st = _take_state(state, sess)
    if error or not code or not st:
        return redirect("/", "EVE login was cancelled or expired. Try again.", "warn")
    try:
        login = await sso.exchange_code(code)
    except sso.SSOError as e:
        return redirect("/", str(e), "bad")
    cid, name = login["character_id"], login["name"]
    user = request.state.user
    intent = st["intent"]
    destination = st["data"].get("next")
    destination = destination if destination in ("/feedback", "/roadmap") else ""
    existing = db.get_character(cid)

    # Same character id, different owner hash: it changed hands. The old profile loses it.
    if existing and existing.get("owner_hash") and login["owner"] and login["owner"] != existing["owner_hash"]:
        await sso.character_transferred(cid)
        if user and user["id"] == existing["profile_id"] and not db.get_profile(user["id"]):
            sessions.sign_out(request)
            user = None
        existing = None

    note = ""
    if intent.startswith("upgrade:"):
        expected = int(intent.split(":", 1)[1])
        if not user:
            return redirect("/", "Sign in first.")
        if cid == expected and existing and existing["profile_id"] == user["id"]:
            await _store_token(login, keep_superset=False)
            db.set_character(cid, status="ok", name=name, owner_hash=login["owner"] or existing.get("owner_hash"))
            prefs = dict(existing.get("bundle_prefs") or {})
            for bid in st["data"].get("bundles", []):
                prefs.pop(bid, None)                     # re-granted: on
            if st["data"].get("action") == "off" and st["data"].get("bundle"):
                prefs.pop(st["data"]["bundle"], None)    # dropped from the token itself
            db.set_character(cid, bundle_prefs=prefs)
            ch = db.get_character(cid)
            b = registry.bundle(st["data"].get("bundle", ""))
            if b and st["data"].get("action") == "on":
                msg = (f"{b.title} is on for {name}." if bundle_active(ch, b.id)
                       else f"EVE didn't grant {b.title} for {name}.")
            elif b:
                msg = f"{b.title} is off for {name}; EVE no longer grants it."
            else:
                msg = f"{name} is logged in again."
            problem = await _refresh_character(cid)
            return redirect("/profile", msg + (f" ({problem})" if problem else ""))
        expected_ch = db.get_character(expected)
        note = (f" You authorised {name} in EVE's character picker, not "
                f"{expected_ch['name'] if expected_ch else 'the character you picked'}, so {name} was handled as an added character.")
        intent = "add"

    if not user:
        # ---- sign in / sign up
        if existing:
            await _store_token(login)
            db.set_character(cid, status="ok", name=name, owner_hash=login["owner"] or existing.get("owner_hash"))
            sessions.sign_in(request, existing["profile_id"])
            problem = await _refresh_character(cid)
            return redirect(destination or "/", f"Signed in as {name}." + (f" ({problem})" if problem else ""))
        aff = await _affiliation(cid)
        if not accounts.gate_allows(cid, aff.get("corporation_id"), aff.get("alliance_id")):
            await sso.revoke(login["refresh_token"])
            return render(request, "invite_only.html", page="invite", page_title="Invite only", who=name,
                          status_code=403)
        pid = db.create_profile(name, cid)
        _link_new(pid, login, aff)
        await _store_token(login)
        sessions.sign_in(request, pid)
        await _refresh_character(cid)
        return redirect(destination or "/welcome")

    # ---- signed in: add a character
    if existing and existing["profile_id"] == user["id"]:
        await _store_token(login)
        db.set_character(cid, status="ok", name=name, owner_hash=login["owner"] or existing.get("owner_hash"))
        problem = await _refresh_character(cid)
        return redirect(_back(request), f"{name} updated." + note + (f" ({problem})" if problem else ""))
    if existing:
        sessions.set_data(request, pending={
            "character_id": cid, "name": name, "owner": login["owner"], "scopes": login["scopes"],
            "rt": encrypt(login["refresh_token"]), "at": encrypt(login["access_token"]),
            "expires_in": login["expires_in"], "from_profile": existing["profile_id"], "note": note.strip(),
            "at_time": time.time()})
        return RedirectResponse("/auth/choose", status_code=303)
    aff = await _affiliation(cid)
    _link_new(user["id"], login, aff)
    await _store_token(login)
    problem = await _refresh_character(cid)
    return redirect(_back(request), f"Added {name}." + note + (f" ({problem})" if problem else ""))


def _back(request: Request) -> str:
    p = request.state.user and db.get_profile(request.state.user["id"])
    return "/welcome" if p and not p["onboarded"] else "/profile"


# --------------------------------------------------------------------------- move / merge
def _pending(request: Request) -> Optional[dict]:
    sess = request.state.session
    p = (sess or {}).get("data", {}).get("pending")
    if p and time.time() - p.get("at_time", 0) > STATE_TTL:
        return None
    return p


@router.get("/auth/choose")
async def choose_page(request: Request):
    user = request.state.user
    p = _pending(request)
    if not user or not p:
        return redirect("/profile")
    other = db.get_profile(p["from_profile"])
    others = db.list_characters(p["from_profile"]) if other else []
    return render(request, "choose.html", page="choose", page_title="Move character", pending=p, other=other,
                  last=len(others) <= 1, other_chars=others)


@router.post("/auth/choose")
async def choose(request: Request):
    user = request.state.user
    p = _pending(request)
    form = await request.form()
    action = form.get("action", "cancel")
    if not user or not p:
        return redirect("/profile", "That choice expired. Add the character again.", "warn")
    sessions.set_data(request, pending=None)
    cid, name = p["character_id"], p["name"]
    login = {"character_id": cid, "name": name, "owner": p["owner"], "scopes": p["scopes"],
             "refresh_token": decrypt(p["rt"]), "access_token": decrypt(p["at"]), "expires_in": p["expires_in"]}
    ch = db.get_character(cid)
    if action == "cancel" or not ch or ch["profile_id"] != p["from_profile"]:
        await sso.revoke(login["refresh_token"])
        return redirect("/profile", f"{name} was left where it was.")
    if action == "merge" and len(db.list_characters(p["from_profile"])) > 1:
        action = "move"   # merging is only offered for a profile's last character; never take a whole profile
    if action == "merge":
        src = p["from_profile"]
        accounts.merge_profiles(src, user["id"])
        await _store_token(login)
        db.set_character(cid, status="ok")
        msg = f"Merged the other profile into this one, including {name}."
    else:
        accounts.move_character(cid, user["id"])
        await _store_token(login)
        db.set_character(cid, status="ok", owner_hash=login["owner"] or ch.get("owner_hash"))
        msg = f"Moved {name} to this profile."
    problem = await _refresh_character(cid)
    return redirect(_back(request), msg + (" " + p["note"] if p.get("note") else "") + (f" ({problem})" if problem else ""))


# --------------------------------------------------------------------------- sign out
@router.post("/auth/logout")
async def logout(request: Request):
    sessions.sign_out(request)
    return redirect("/", "Signed out.")


@router.post("/auth/logout-everywhere")
async def logout_everywhere(request: Request):
    user = request.state.user
    if user:
        sessions.sign_out_everywhere(user["id"])
    sessions.sign_out(request)
    return redirect("/", "Signed out on every browser.")
