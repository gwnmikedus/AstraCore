"""EVE SSO (OAuth2 authorization-code flow) for a local web app."""
from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx

from .. import db
from ..config import SSO_SCOPES, callback_url, sso_credentials

AUTHORIZE_URL = "https://login.eveonline.com/v2/oauth/authorize"
TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"

_pending_states: dict = {}


def configured() -> bool:
    cid, secret = sso_credentials()
    return bool(cid and secret)


def login_url() -> str:
    cid, _ = sso_credentials()
    state = secrets.token_urlsafe(16)
    _pending_states[state] = time.time()
    q = urlencode({
        "response_type": "code",
        "redirect_uri": callback_url(),
        "client_id": cid,
        "scope": " ".join(SSO_SCOPES),
        "state": state,
    })
    return f"{AUTHORIZE_URL}?{q}"


def check_state(state: str) -> bool:
    ts = _pending_states.pop(state, None)
    return ts is not None and time.time() - ts < 900


def _basic_auth() -> str:
    cid, secret = sso_credentials()
    return "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()


def _decode_jwt(token: str) -> dict:
    # The token was received directly from login.eveonline.com over TLS, so we
    # only need its claims (character id/name); no third party handed it to us.
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


async def _token_request(data: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, data=data, headers={
            "Authorization": _basic_auth(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "login.eveonline.com",
        })
    r.raise_for_status()
    return r.json()


async def exchange_code(code: str) -> Tuple[int, str]:
    tok = await _token_request({"grant_type": "authorization_code", "code": code})
    claims = _decode_jwt(tok["access_token"])
    character_id = int(claims["sub"].split(":")[-1])
    name = claims.get("name", str(character_id))
    scp = claims.get("scp", [])
    scopes = " ".join(scp if isinstance(scp, list) else [scp])
    db.save_token(character_id, tok["refresh_token"], tok["access_token"], int(tok["expires_in"]), scopes)
    return character_id, name


async def access_token(character_id: int) -> Optional[str]:
    t = db.get_token(character_id)
    if not t:
        return None
    if t["access_token"] and t["expires_at"] and t["expires_at"] > time.time():
        return t["access_token"]
    tok = await _token_request({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    scp = _decode_jwt(tok["access_token"]).get("scp", [])
    db.save_token(character_id, tok.get("refresh_token", t["refresh_token"]),
                  tok["access_token"], int(tok["expires_in"]),
                  " ".join(scp if isinstance(scp, list) else [scp]))
    return tok["access_token"]
