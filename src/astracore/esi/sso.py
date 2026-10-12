"""EVE SSO (OAuth2 authorization code flow): login URLs, token exchange with full JWT validation,
refresh, revocation, and what happens when EVE says a character changed hands or access was revoked."""
from __future__ import annotations

import base64
import logging
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode

import httpx
import jwt

from astracore import db
from astracore.config import callback_url, sso_credentials

log = logging.getLogger("astracore")

AUTHORIZE_URL = "https://login.eveonline.com/v2/oauth/authorize"
# Where a pilot removes AstraCore's access themselves (EVE's third-party applications / authorized apps;
# the old community.eveonline.com/support/third-party-applications/ address now redirects elsewhere).
AUTHORIZED_APPS_URL = "https://developers.eveonline.com/authorized-apps"
TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
REVOKE_URL = "https://login.eveonline.com/v2/oauth/revoke"
METADATA_URL = "https://login.eveonline.com/.well-known/oauth-authorization-server"
ISSUERS = ["https://login.eveonline.com", "login.eveonline.com"]
JWKS_TTL = 24 * 3600

_jwks_cache: Dict = {"at": 0.0, "keys": None}


class SSOError(RuntimeError):
    pass


class NeedsLogin(SSOError):
    """The refresh token stopped working (access revoked, password changed): log in again."""


class Transferred(SSOError):
    """The character's owner hash changed: it now belongs to another EVE account."""


def configured() -> bool:
    cid, secret = sso_credentials()
    return bool(cid and secret)


def authorize_url(state: str, scopes: List[str]) -> str:
    cid, _ = sso_credentials()
    q = {"response_type": "code", "redirect_uri": callback_url(), "client_id": cid, "state": state}
    if scopes:
        q["scope"] = " ".join(scopes)
    return f"{AUTHORIZE_URL}?{urlencode(q)}"


def _basic_auth() -> str:
    cid, secret = sso_credentials()
    return "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()


# --------------------------------------------------------------------------- JWT validation
async def _fetch_jwks() -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        meta = (await c.get(METADATA_URL)).raise_for_status().json()
        return (await c.get(meta["jwks_uri"])).raise_for_status().json()


async def jwks(force: bool = False) -> dict:
    if force or not _jwks_cache["keys"] or time.time() - _jwks_cache["at"] > JWKS_TTL:
        _jwks_cache["keys"] = await _fetch_jwks()
        _jwks_cache["at"] = time.time()
    return _jwks_cache["keys"]


async def validate(access_token: str) -> dict:
    """Verify the access token's signature (EVE's JWKS), issuer, audience and expiry; return its claims."""
    cid, _ = sso_credentials()
    try:
        kid = jwt.get_unverified_header(access_token).get("kid")
    except jwt.PyJWTError as e:
        raise SSOError(f"Malformed token from EVE SSO: {e}") from e
    for attempt in range(2):
        keys = (await jwks(force=attempt > 0)).get("keys", [])
        key = next((k for k in keys if k.get("kid") == kid and k.get("alg", "RS256") == "RS256"), None)
        if key:
            break
    else:
        raise SSOError("EVE SSO signed the token with an unknown key.")
    try:
        return jwt.decode(access_token, jwt.PyJWK(key).key, algorithms=["RS256"], audience=cid,
                          issuer=ISSUERS, leeway=30, options={"require": ["exp", "sub", "iss", "aud"]})
    except jwt.PyJWTError as e:
        raise SSOError(f"EVE SSO token rejected: {e}") from e


def _scopes(claims: dict) -> str:
    scp = claims.get("scp", [])
    return " ".join(scp if isinstance(scp, list) else [scp])


# --------------------------------------------------------------------------- token endpoint
async def _token_request(data: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30) as c:
        return await c.post(TOKEN_URL, data=data, headers={
            "Authorization": _basic_auth(), "Content-Type": "application/x-www-form-urlencoded",
            "Host": "login.eveonline.com"})


async def exchange_code(code: str) -> dict:
    """Code -> validated login: {character_id, name, owner, scopes, refresh_token, access_token, expires_in}."""
    r = await _token_request({"grant_type": "authorization_code", "code": code})
    if r.status_code != 200:
        raise SSOError(f"EVE SSO refused the login ({r.status_code}).")
    tok = r.json()
    claims = await validate(tok["access_token"])
    return {
        "character_id": int(str(claims["sub"]).split(":")[-1]),
        "name": claims.get("name", ""),
        "owner": claims.get("owner"),
        "scopes": _scopes(claims),
        "refresh_token": tok["refresh_token"],
        "access_token": tok["access_token"],
        "expires_in": int(tok.get("expires_in", 1199)),
    }


async def revoke(refresh_token: Optional[str]) -> bool:
    """Tell EVE SSO to revoke a refresh token. Best effort: returns False if EVE didn't confirm."""
    if not refresh_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(REVOKE_URL, data={"token_type_hint": "refresh_token", "token": refresh_token},
                             headers={"Authorization": _basic_auth(),
                                      "Content-Type": "application/x-www-form-urlencoded",
                                      "Host": "login.eveonline.com"})
        return r.status_code == 200
    except httpx.HTTPError:
        log.warning("token revoke failed (network)")
        return False


async def access_token(character_id: int) -> Optional[str]:
    """A valid access token for the character, refreshing when needed.

    Raises NeedsLogin when EVE refuses the refresh token (the character is marked "needs login",
    its data stays) and Transferred when the owner hash changed (the character is unlinked)."""
    t = db.get_token(character_id)
    if not t or not t["refresh_token"]:
        return None
    if t["access_token"] and t["expires_at"] and t["expires_at"] > time.time():
        return t["access_token"]
    r = await _token_request({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    if r.status_code in (400, 401):
        err = ""
        try:
            err = r.json().get("error", "")
        except ValueError:
            pass
        if err == "invalid_grant" or r.status_code == 401:
            mark_needs_login(character_id)
            raise NeedsLogin("EVE no longer accepts this character's login.")
    if r.status_code != 200:
        raise SSOError(f"EVE SSO refresh failed ({r.status_code}).")
    tok = r.json()
    claims = await validate(tok["access_token"])
    ch = db.get_character(character_id)
    owner = claims.get("owner")
    if ch and owner and ch.get("owner_hash") and owner != ch["owner_hash"]:
        await character_transferred(character_id)
        raise Transferred(f"{ch['name']} was transferred to another player.")
    if ch and owner and not ch.get("owner_hash"):
        db.set_character(character_id, owner_hash=owner)
    db.save_token(character_id, tok.get("refresh_token", t["refresh_token"]), tok["access_token"],
                  int(tok.get("expires_in", 1199)), _scopes(claims))
    if ch and ch.get("status") != "ok":
        db.set_character(character_id, status="ok")
    return tok["access_token"]


def mark_needs_login(character_id: int) -> None:
    ch = db.get_character(character_id)
    if ch and ch["status"] != "needs_login":
        db.set_character(character_id, status="needs_login")
        db.add_notice(ch["profile_id"], f"EVE no longer accepts the login of {ch['name']} (access revoked or "
                                        f"password changed). Log in with {ch['name']} again; its data is kept.")


async def character_transferred(character_id: int) -> None:
    """Owner hash changed: drop the token, unlink the character, tell the profile."""
    from astracore.core import accounts
    ch = db.get_character(character_id)
    if not ch:
        return
    await accounts.unlink_character(ch["profile_id"], character_id, revoke_token=False)
    db.add_notice(ch["profile_id"], f"{ch['name']} was transferred to another player, so it was removed from your profile.",
                  "bad")
