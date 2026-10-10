"""Feedback login keeps EVE state protections and the hosted-service invite gate."""
from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from astracore import config, db
from astracore.core import auth, community, registry, sessions
from astracore.esi import sso

_character_ids = iter(range(93_000_000, 94_000_000))


class FakeEVE:
    def __init__(self):
        self.logins = {}
        self.revoked = []
        self.exchanged = []

    def prepare(self, character_id: int) -> str:
        code = f"community-code-{character_id}-{len(self.logins)}"
        self.logins[code] = {
            "character_id": character_id, "name": f"Pilot {character_id}", "owner": "community-owner",
            "scopes": " ".join(registry.signin_scopes()), "refresh_token": f"refresh-{code}",
            "access_token": f"access-{code}", "expires_in": 1199,
        }
        return code


@pytest.fixture()
def eve(monkeypatch):
    fake = FakeEVE()

    async def exchange(code):
        fake.exchanged.append(code)
        return dict(fake.logins[code])

    async def revoke(token):
        fake.revoked.append(token)
        return True

    async def refresh(character_id):
        return ""

    async def affiliation(character_id):
        return {}

    async def idle_sync():
        await asyncio.Event().wait()

    monkeypatch.setattr(sso, "configured", lambda: True)
    monkeypatch.setattr(sso, "exchange_code", exchange)
    monkeypatch.setattr(sso, "revoke", revoke)
    monkeypatch.setattr(auth, "_refresh_character", refresh)
    monkeypatch.setattr(auth, "_affiliation", affiliation)
    monkeypatch.setattr(community, "run_sync_loop", idle_sync)
    return fake


@pytest.fixture()
def browsers(eve):
    from astracore.app import app
    clients = []

    def create():
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield create
    for client in clients:
        client.__exit__(None, None, None)


def _start(client, path="/auth/community"):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    state = parse_qs(urlparse(location).query)["state"][0]
    return state, location


def _finish(client, eve, character_id, state):
    code = eve.prepare(character_id)
    response = client.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)
    return response, code


def _profile(client):
    session = sessions._load(client.cookies.get(sessions.COOKIE))
    return session["profile_id"] if session else None


def test_community_login_records_safe_destination_and_returns_to_feedback(browsers, eve):
    client = browsers()
    state, location = _start(client)
    with db.session() as connection:
        saved = connection.execute("SELECT intent,data_json FROM sso_states WHERE state=?", (state,)).fetchone()
    assert saved["intent"] == "login"
    assert json.loads(saved["data_json"])["next"] == "/feedback"
    scopes = parse_qs(urlparse(location).query).get("scope", [""])[0].split()
    assert set(scopes) == set(registry.signin_scopes())
    response, _ = _finish(client, eve, next(_character_ids), state)
    assert response.status_code == 303
    assert urlparse(response.headers["location"]).path == "/feedback"
    assert _profile(client) is not None


def test_already_signed_in_community_link_does_not_start_add_character_flow(browsers, eve):
    client = browsers()
    state, _ = _start(client)
    _finish(client, eve, next(_character_ids), state)
    profile_id = _profile(client)
    characters = db.list_characters(profile_id)
    with db.session() as connection:
        states_before = connection.execute("SELECT COUNT(*) FROM sso_states").fetchone()[0]
    response = client.get("/auth/community", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/feedback"
    assert _profile(client) == profile_id
    assert db.list_characters(profile_id) == characters
    with db.session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sso_states").fetchone()[0] == states_before


def test_signed_out_existing_profile_returns_to_feedback(browsers, eve):
    character_id = next(_character_ids)
    original = browsers()
    state, _ = _start(original, "/auth/login")
    _finish(original, eve, character_id, state)
    profile_id = _profile(original)
    returning = browsers()
    state, _ = _start(returning)
    response, _ = _finish(returning, eve, character_id, state)
    assert urlparse(response.headers["location"]).path == "/feedback"
    assert _profile(returning) == profile_id


def test_community_login_cannot_bypass_invite_gate(browsers, eve, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_GATE", True)
    monkeypatch.setattr(config, "ALLOWED", {"character": set(), "corporation": set(), "alliance": set()})
    character_id = next(_character_ids)
    client = browsers()
    state, _ = _start(client)
    response, code = _finish(client, eve, character_id, state)
    assert response.status_code == 403
    assert "Invite" in response.text or "invite" in response.text
    assert _profile(client) is None
    assert db.get_character(character_id) is None
    assert eve.logins[code]["refresh_token"] in eve.revoked


def test_invited_community_visitor_can_return_to_feedback(browsers, eve, monkeypatch):
    character_id = next(_character_ids)
    monkeypatch.setattr(config, "ACCESS_GATE", True)
    monkeypatch.setattr(config, "ALLOWED", {"character": {character_id}, "corporation": set(), "alliance": set()})
    client = browsers()
    state, _ = _start(client)
    response, _ = _finish(client, eve, character_id, state)
    assert response.status_code == 303
    assert urlparse(response.headers["location"]).path == "/feedback"
    assert _profile(client) is not None


@pytest.mark.parametrize("destination", ["https://example.com/steal", "//example.com/steal", "/\\example.com/steal", "/profile"])
def test_login_rejects_unapproved_return_destinations(browsers, eve, destination):
    client = browsers()
    response = client.get("/auth/login", params={"next": destination}, follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    completed, _ = _finish(client, eve, next(_character_ids), state)
    assert completed.headers["location"] == "/welcome"


def test_callback_revalidates_stored_return_destination(browsers, eve):
    client = browsers()
    state, _ = _start(client)
    with db.session() as connection:
        connection.execute("UPDATE sso_states SET data_json=? WHERE state=?",
                           (json.dumps({"next": "https://example.com/steal"}), state))
    response, _ = _finish(client, eve, next(_character_ids), state)
    assert response.headers["location"] == "/welcome"


@pytest.mark.parametrize("invalid_state", ["expired", "different-browser", "cancelled"])
def test_invalid_community_state_is_consumed_before_token_exchange(browsers, eve, invalid_state):
    client = browsers()
    state, _ = _start(client)
    callback_client = client
    params = {"code": eve.prepare(next(_character_ids)), "state": state}
    if invalid_state == "expired":
        with db.session() as connection:
            connection.execute("UPDATE sso_states SET created_at=? WHERE state=?",
                               (time.time() - auth.STATE_TTL - 1, state))
    elif invalid_state == "different-browser":
        callback_client = browsers()
    else:
        params["error"] = "access_denied"
    response = callback_client.get("/auth/callback", params=params, follow_redirects=False)
    assert response.status_code == 303
    assert urlparse(response.headers["location"]).path == "/"
    assert eve.exchanged == []
    assert _profile(callback_client) is None
    with db.session() as connection:
        assert connection.execute("SELECT 1 FROM sso_states WHERE state=?", (state,)).fetchone() is None


def test_successful_community_state_cannot_be_replayed(browsers, eve):
    client = browsers()
    state, _ = _start(client)
    response, code = _finish(client, eve, next(_character_ids), state)
    assert urlparse(response.headers["location"]).path == "/feedback"
    profile_id = _profile(client)
    replay = client.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert urlparse(replay.headers["location"]).path == "/"
    assert eve.exchanged == [code]
    assert _profile(client) == profile_id
