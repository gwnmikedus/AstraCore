"""Core pages: home (landing / dashboard), onboarding, profile, what we read, privacy, admin."""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from astracore import config, db

from . import accounts, registry, releases, sessions
from .auth import bundle_active, missing_required
from .web import redirect, render

log = logging.getLogger("astracore")
router = APIRouter()
REFRESH_EVERY = 300          # a profile may ask ESI for fresh data at most every 5 minutes
STALE_AFTER = 3 * 86400


@router.get("/project", response_class=HTMLResponse)
async def project_page(request: Request):
    return render(request, "project.html", page="project", page_title="Source & contribute")


@router.get("/releases", response_class=HTMLResponse)
async def releases_page(request: Request):
    return render(request, "releases.html", page="releases", page_title="What’s new",
                  release_history=releases.history())


def _user(request: Request) -> Optional[dict]:
    return request.state.user


def _login_first() -> RedirectResponse:
    return redirect("/", "Sign in first.")


# --------------------------------------------------------------------------- home
@router.get("/", response_class=HTMLResponse)
@router.get("/about", response_class=HTMLResponse)
async def home(request: Request, code: str = "", state: str = ""):
    if code:   # EVE app registered with the site root as callback
        return RedirectResponse(f"/auth/callback?code={code}&state={state}", status_code=303)
    user = _user(request)
    if not user or request.url.path == "/about":
        return render(request, "home.html", page="home", page_title="", modules=registry.MODULES,
                      members=_member_groups())
    p = db.get_profile(user["id"])
    if p and not p["onboarded"]:
        return RedirectResponse("/welcome", status_code=303)
    tiles = []
    for m in registry.MODULES:
        tile = {}
        if m.dashboard_tile:
            try:
                tile = await m.dashboard_tile(user)
            except Exception:  # noqa: BLE001 - one module must never break the dashboard
                log.exception("dashboard tile %s", m.id)
        tiles.append({"module": m, **tile})
    return render(request, "dashboard.html", page="dashboard", page_title="Dashboard", tiles=tiles,
                  alerts=_alerts(user["id"]))


def _member_groups() -> dict:
    """The corporation/alliance whose members may always log in (shown on the landing page)."""
    from astracore.core import eveimg
    groups = eveimg.home_groups()
    out = {}
    corp, ally = groups.get("corporation"), groups.get("alliance")
    if corp and (corp["id"] in config.ALLOWED["corporation"] or not config.ACCESS_GATE):
        out["corporation"] = corp
    if ally and (ally["id"] in config.ALLOWED["alliance"] or not config.ACCESS_GATE):
        out["alliance"] = ally
    return out


def _alerts(profile_id: int) -> list:
    out = [{"kind": n.get("kind", "warn"), "text": n["text"]} for n in db.pop_notices(profile_id)]
    now = time.time()
    for ch in db.list_characters(profile_id):
        if ch["status"] == "needs_login" or not ch["has_token"]:
            out.append({"kind": "warn", "text": f"{ch['name']} needs a new EVE login.",
                        "href": f"/auth/upgrade/{ch['character_id']}", "action": f"Log in as {ch['name']}"})
            continue
        for m in registry.MODULES:
            if m.id in (ch.get("enabled_modules") or ["pi"]) and missing_required(ch, m.id):
                out.append({"kind": "warn", "text": f"{ch['name']} needs one more EVE login for {m.name}.",
                            "href": f"/auth/upgrade/{ch['character_id']}", "action": "Log in again"})
        if ch.get("synced_at") and now - ch["synced_at"] > STALE_AFTER:
            days = int((now - ch["synced_at"]) // 86400)
            out.append({"kind": "info", "text": f"{ch['name']}: last ESI refresh {days} days ago.",
                        "form": "/profile/refresh", "action": "Refresh now"})
    return out


# --------------------------------------------------------------------------- onboarding
@router.get("/welcome", response_class=HTMLResponse)
async def welcome(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    chars = db.list_characters(user["id"])
    return render(request, "welcome.html", page="welcome", page_title="Welcome", chars=chars,
                  accounts=db.list_accounts(user["id"]), first=chars[0] if chars else None,
                  max_per_account=db.MAX_CHARACTERS_PER_ACCOUNT)


@router.post("/welcome/done")
async def welcome_done(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    db.update_profile(user["id"], onboarded=1)
    form = await request.form()
    return redirect(form.get("next") or "/pi")


# --------------------------------------------------------------------------- profile
@router.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    pid = user["id"]
    chars = db.list_characters(pid)
    accs = db.list_accounts(pid)
    for ch in chars:
        ch["bundles"] = []
        for m in registry.MODULES:
            for b in m.bundles:
                granted = set(b.scopes) <= set(ch["scopes"])
                ch["bundles"].append({"bundle": b, "module": m, "required": b is m.required_bundle,
                                      "granted": granted, "active": bundle_active(ch, b.id),
                                      "switched_off": granted and not bundle_active(ch, b.id)})
        ch["needs_pi_login"] = missing_required(ch, "pi")
        used = {sc for b in registry.all_bundles().values() for sc in b.scopes}
        ch["extra_scopes"] = sorted(set(ch["scopes"]) - used)
    columns = [{"account": a, "chars": [c for c in chars if c["eve_account_id"] == a["id"]]} for a in accs]
    unassigned = [c for c in chars if not c["eve_account_id"]]
    cur = request.state.session["id_hash"] if request.state.session else None
    return render(request, "profile.html", page="profile", page_title="Profile", chars=chars, columns=columns,
                  unassigned=unassigned, accounts=accs, sessions=sessions.list_sessions(pid), current_session=cur,
                  max_per_account=db.MAX_CHARACTERS_PER_ACCOUNT, profile=db.get_profile(pid),
                  refresh_wait=_refresh_wait(pid))


def _refresh_wait(profile_id: int) -> int:
    p = db.get_profile(profile_id) or {}
    last = p.get("last_esi_refresh_at") or 0
    return max(0, int(REFRESH_EVERY - (time.time() - last)))


@router.post("/profile/refresh")
async def profile_refresh(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    form = await request.form()
    back = form.get("back") or "/profile"
    if not back.startswith("/") or back.startswith("//"):
        back = "/profile"
    wait = _refresh_wait(user["id"])
    if wait:
        return redirect(back, f"ESI was read less than 5 minutes ago. Try again in {wait // 60 + 1} min.", "warn")
    db.update_profile(user["id"], last_esi_refresh_at=time.time())
    only = int(form["character_id"]) if str(form.get("character_id", "")).isdigit() else None
    from astracore.modules.pi.service import refresh_profile
    problems = await refresh_profile(user["id"], only)
    if problems:
        return redirect(back, "Refreshed, with problems: " + "; ".join(f"{k}: {v}" for k, v in problems.items()), "warn")
    return redirect(back, "Refreshed from ESI.")


@router.post("/profile/main")
async def set_main(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    form = await request.form()
    ch = db.owned_character(user["id"], int(form.get("character_id") or 0))
    if ch:
        db.update_profile(user["id"], main_character_id=ch["character_id"], display_name=ch["name"])
    return redirect("/profile", f"{ch['name']} is your main character now." if ch else "Unknown character.")


@router.post("/profile/accounts")
async def account_create(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    form = await request.form()
    db.create_account(user["id"], form.get("name", ""))
    return redirect(form.get("back") or "/profile")


@router.post("/profile/accounts/{account_id}/rename")
async def account_rename(request: Request, account_id: int):
    user = _user(request)
    if not user:
        return _login_first()
    form = await request.form()
    db.rename_account(user["id"], account_id, form.get("name", ""))
    return redirect(form.get("back") or "/profile")


@router.post("/profile/accounts/{account_id}/delete")
async def account_delete(request: Request, account_id: int):
    user = _user(request)
    if not user:
        return _login_first()
    form = await request.form()
    db.delete_account(user["id"], account_id)
    return redirect(form.get("back") or "/profile", "EVE account removed; its characters are unassigned now.")


@router.post("/profile/characters/{character_id}/account")
async def character_account(request: Request, character_id: int):
    user = _user(request)
    if not user:
        return _login_first()
    form = await request.form()
    raw = form.get("account_id", "")
    err = db.assign_account(user["id"], character_id, int(raw) if str(raw).isdigit() else None)
    return redirect(form.get("back") or "/profile", err or None, "warn" if err else None)


@router.post("/profile/characters/{character_id}/bundles/{bundle_id}/pause")
async def bundle_pause(request: Request, character_id: int, bundle_id: str):
    """Switch an optional bundle off without a new login: the scopes stay granted but are never used."""
    user = _user(request)
    if not user:
        return _login_first()
    ch = db.owned_character(user["id"], character_id)
    b = registry.bundle(bundle_id)
    if not ch or not b or any(b is m.required_bundle for m in registry.MODULES):
        return redirect("/profile", "Unknown option.", "bad")
    prefs = dict(ch.get("bundle_prefs") or {})
    prefs[bundle_id] = False
    db.set_character(character_id, bundle_prefs=prefs)
    if bundle_id == "pi.optional.customs":
        db.set_character(character_id, customs_offices=[])
    return redirect("/profile", f"{b.title} is off for {ch['name']}. EVE still grants it (\"granted but unused\"); "
                                f"log in again to drop it completely.")


@router.post("/profile/characters/{character_id}/bundles/{bundle_id}/resume")
async def bundle_resume(request: Request, character_id: int, bundle_id: str):
    user = _user(request)
    if not user:
        return _login_first()
    ch = db.owned_character(user["id"], character_id)
    if not ch:
        return redirect("/profile", "Unknown character.", "bad")
    prefs = dict(ch.get("bundle_prefs") or {})
    prefs.pop(bundle_id, None)
    db.set_character(character_id, bundle_prefs=prefs)
    return redirect("/profile")


@router.post("/profile/characters/{character_id}/remove")
async def character_remove(request: Request, character_id: int):
    user = _user(request)
    if not user:
        return _login_first()
    pid = user["id"]
    ch = db.owned_character(pid, character_id)
    if not ch:
        return redirect("/profile", "Unknown character.", "bad")
    if len(db.list_characters(pid)) <= 1:
        return redirect("/profile/reset", f"{ch['name']} is your last character: removing it deletes your profile.",
                        "warn")
    await accounts.unlink_character(pid, character_id)
    return redirect("/profile", f"Removed {ch['name']} and revoked its EVE login. You can also check EVE's "
                                f"third-party applications page on eveonline.com.")


@router.post("/profile/sessions/{id_hash}/end")
async def session_end(request: Request, id_hash: str):
    user = _user(request)
    if not user:
        return _login_first()
    sessions.end_session(user["id"], id_hash)
    return redirect("/profile", "Signed out that browser.")


@router.get("/profile/export.json")
async def export_data(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    data = accounts.export_profile(user["id"])
    return Response(json.dumps(data, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="astracore-my-data.json"'})


@router.get("/profile/reset", response_class=HTMLResponse)
async def reset_page(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    return render(request, "reset.html", page="reset", page_title="Reset profile",
                  profile=db.get_profile(user["id"]), chars=db.list_characters(user["id"]))


@router.post("/profile/reset")
async def reset_profile(request: Request):
    user = _user(request)
    if not user:
        return _login_first()
    form = await request.form()
    p = db.get_profile(user["id"])
    if (form.get("confirm") or "").strip() != p["display_name"]:
        return redirect("/profile/reset", f"Type {p['display_name']} exactly to confirm.", "warn")
    await accounts.reset_profile(user["id"])
    sessions.sign_out(request)
    return redirect("/", "Your profile was deleted.")


# --------------------------------------------------------------------------- public pages
@router.get("/what-we-read", response_class=HTMLResponse)
async def what_we_read(request: Request):
    from .registry import SCOPE_TEXT
    return render(request, "what_we_read.html", page="scopes", page_title="What we read",
                  modules=registry.MODULES, scope_text=SCOPE_TEXT)


@router.get("/credits", response_class=HTMLResponse)
async def credits(request: Request):
    return render(request, "credits.html", page="credits", page_title="Credits")


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return render(request, "privacy.html", page="privacy", page_title="Privacy", modules=registry.MODULES)


# --------------------------------------------------------------------------- admin
def _admin(request: Request) -> Optional[dict]:
    u = _user(request)
    return u if u and u.get("is_admin") else None


@router.get("/admin", response_class=HTMLResponse)
async def admin(request: Request):
    if not _admin(request):
        return render(request, "error.html", page="error", page_title="Not found", code=404,
                      message="This page doesn't exist.", status_code=404)
    from astracore.modules.pi import store as pi_store
    from astracore.modules.pi.static_data import voc
    from .solvegate import GATE
    with db.session() as c:
        n_profiles = c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        n_chars = c.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
        n_sessions = c.execute("SELECT COUNT(*) FROM sessions WHERE profile_id IS NOT NULL").fetchone()[0]
    env_rows = [{"kind": k, "entity_id": i} for k, ids in config.ALLOWED.items() for i in sorted(ids)]
    names = await _entity_names([r["entity_id"] for r in env_rows])
    for r in env_rows:
        r["name"] = names.get(r["entity_id"], "")
    return render(request, "admin.html", page="admin", page_title="Admin", s=pi_store.admin_settings(),
                  access=db.access_list(), env_rows=env_rows, gate=config.ACCESS_GATE, people=_people(),
                  me=_admin(request)["id"], admin_ids=sorted(config.ADMIN_CHARACTER_IDS),
                  stats={"profiles": n_profiles, "characters": n_chars, "sessions": n_sessions,
                         "solving": GATE.running, "waiting": GATE.waiting},
                  routes=voc.routes_cached(), routes_info=voc.routes_info(), mode=config.MODE)


async def _entity_names(ids) -> dict:
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    try:
        from astracore.esi import public
        from astracore.esi.client import ESIClient
        async with ESIClient() as esi:
            return await public.ids_to_names(esi, ids)
    except Exception:  # noqa: BLE001 - names are a convenience
        return {}


def _people() -> list:
    with db.session() as c:
        profiles = [dict(r) for r in c.execute("SELECT id, display_name, main_character_id, created_at, last_login_at "
                                               "FROM profiles ORDER BY last_login_at DESC")]
    for p in profiles:
        chars = db.list_characters(p["id"])
        p["chars"] = [{"id": ch["character_id"], "name": ch["name"], "corp": ch.get("corporation_name") or "",
                       "alliance": ch.get("alliance_name") or ""} for ch in chars]
        p["is_admin"] = any(ch["character_id"] in config.ADMIN_CHARACTER_IDS for ch in chars)
    return profiles


@router.post("/admin/people/{profile_id}/remove")
async def admin_remove_profile(request: Request, profile_id: int):
    """Take someone's access away: revokes their EVE logins and deletes their profile. Admin profiles can't be removed."""
    admin = _admin(request)
    if not admin:
        return redirect("/")
    target = db.get_profile(profile_id)
    if not target:
        return redirect("/admin", "Unknown profile.", "warn")
    if profile_id == admin["id"] or db.is_admin(profile_id):
        return redirect("/admin", "Admin profiles can't be removed here.", "warn")
    await accounts.reset_profile(profile_id)
    return redirect("/admin", f"Removed {target['display_name']}'s profile and revoked their EVE logins. "
                              "Take them off the invite list too, or they can sign up again.")


@router.post("/admin/settings")
async def admin_settings(request: Request):
    if not _admin(request):
        return redirect("/")
    from astracore.modules.pi import store as pi_store
    form = await request.form()
    pi_store.save_admin_settings(dict(form))
    from .solvegate import GATE
    GATE.clear()
    return redirect("/admin", "Saved.")


@router.post("/admin/access")
async def admin_access(request: Request):
    if not _admin(request):
        return redirect("/")
    form = await request.form()
    kind = form.get("kind", "")
    raw = (form.get("entity", "") or "").strip()
    if kind not in ("character", "corporation", "alliance") or not raw:
        return redirect("/admin", "Pick a kind and enter a name or ID.", "warn")
    entity_id, name = (int(raw), "") if raw.isdigit() else (None, raw)
    try:
        from astracore.esi import public
        from astracore.esi.client import ESIClient
        async with ESIClient() as esi:
            if entity_id is None:
                found = await public.resolve_names(esi, [raw])
                rows = found.get({"character": "characters", "corporation": "corporations",
                                  "alliance": "alliances"}[kind], [])
                if rows:
                    entity_id, name = rows[0]["id"], rows[0]["name"]
            elif not name:
                name = (await public.ids_to_names(esi, [entity_id])).get(entity_id, "")
    except Exception:  # noqa: BLE001 - names are a convenience
        log.warning("access list name lookup failed")
    if entity_id is None:
        return redirect("/admin", f"No {kind} called {raw} found.", "warn")
    db.access_add(kind, entity_id, name)
    return redirect("/admin", f"Added {name or entity_id} to the invite list.")


@router.post("/admin/access/{kind}/{entity_id}/remove")
async def admin_access_remove(request: Request, kind: str, entity_id: int):
    if not _admin(request):
        return redirect("/")
    db.access_remove(kind, entity_id)
    return redirect("/admin", "Removed from the invite list.")
