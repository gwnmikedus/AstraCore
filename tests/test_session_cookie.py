"""Production uses a host-bound session cookie of its own generation; local HTTP keeps `ac_session`."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from astracore import config
from astracore.core import sessions

from test_core import eve, new_id, sso_login  # noqa: F401


def session_cookie(response, name):
    found = [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}=")]
    assert len(found) == 1, response.headers.get_list("set-cookie")
    return found[0]


def flags(header):
    return {part.split("=")[0].strip().lower() for part in header.split(";")[1:]}


def profile(client, cookie=None):
    """The profile page answers 200 when signed in and redirects to the start page otherwise."""
    return client.get("/profile", headers={"Cookie": cookie} if cookie else None, follow_redirects=False)


def signed_in(client):
    return profile(client).status_code == 200


def csrf(client):
    return sessions._load(client.cookies.get(sessions.cookie_name()))["csrf"]


@pytest.fixture
def production(monkeypatch):
    from astracore.app import app

    monkeypatch.setattr(config, "PRODUCTION", True)
    clients = []

    def make():
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return client
    yield make
    for client in clients:
        client.__exit__(None, None, None)


def local_client():
    from astracore.app import app

    return TestClient(app)


def test_local_http_keeps_ac_session(eve):
    with local_client() as client:
        response, _ = sso_login(client, eve, new_id(), "Fictional local pilot")
        cookie = session_cookie(response, "ac_session")
        assert flags(cookie) == {"path", "max-age", "httponly", "samesite"}
        assert "SameSite=Lax" in cookie and "Path=/" in cookie
        assert not [h for h in response.headers.get_list("set-cookie") if h.startswith("__Host-")]
        assert signed_in(client)


def test_production_sso_csrf_logout_and_replacement_use_the_host_cookie(production, eve):
    client = production()
    start = client.get("/auth/login", follow_redirects=False)
    first = session_cookie(start, "__Host-ac_session")
    assert flags(first) == {"path", "max-age", "httponly", "samesite", "secure"}   # never a Domain
    assert "Path=/;" in first and "SameSite=Lax" in first
    before = client.cookies.get("__Host-ac_session")
    response, _ = sso_login(client, eve, new_id(), "Fictional hosted pilot")
    assert not [h for h in response.headers.get_list("set-cookie") if h.startswith("ac_session=")]
    after = client.cookies.get("__Host-ac_session")
    assert after and after != before                       # sign-in replaces the session
    assert sessions._load(before) is None
    assert signed_in(client)
    assert client.post("/pi/api/save", json={"guide_step": 1}).status_code == 403
    assert client.post("/pi/api/save", json={"guide_step": 1}, headers={"X-CSRF-Token": csrf(client)}).status_code == 200
    out = client.post("/auth/logout", data={"csrf_token": csrf(client)}, follow_redirects=False)
    cleared = session_cookie(out, "__Host-ac_session")
    assert cleared.startswith("__Host-ac_session=;") and "Max-Age=0" in cleared and "Secure" in cleared
    assert sessions._load(after) is None and not signed_in(client)


def test_switch_signs_out_legacy_sessions_and_in_flight_sign_ins_once(production, monkeypatch, eve):
    # A session and a pending EVE login from before the switch, under the old cookie name.
    with local_client() as old:
        sso_login(old, eve, new_id(), "Fictional earlier pilot")
        legacy = old.cookies.get("ac_session")
        old.get("/auth/login", follow_redirects=False)
        pending = old.cookies.get("ac_session")
        state = old.get("/auth/login", follow_redirects=False).headers["location"].split("state=")[1].split("&")[0]
    client = production()
    response = profile(client, f"ac_session={legacy}")
    assert response.status_code == 303
    gone = session_cookie(response, "ac_session")
    assert "Max-Age=0" in gone and "Secure" in gone       # the old cookie is cleared, never read
    # The same value moved into the new name isn't a session either: the generations are separate.
    response = profile(client, f"__Host-ac_session={legacy}")
    assert response.status_code == 303
    assert "Max-Age=0" in session_cookie(response, "__Host-ac_session")
    code = eve.login(new_id(), "Fictional pending pilot")
    callback = client.get(f"/auth/callback?code={code}&state={state}", headers={"Cookie": f"ac_session={pending}"},
                          follow_redirects=False)
    assert callback.status_code == 303 and callback.headers["location"].startswith("/")
    assert not [h for h in callback.headers.get_list("set-cookie") if h.startswith("__Host-ac_session=") and "Max-Age=0" not in h]
    # Signing in again works normally.
    sso_login(client, eve, new_id(), "Fictional returning pilot")
    assert signed_in(client)


@pytest.mark.parametrize("hosted", [True, False])
def test_duplicate_session_cookies_are_rejected(production, eve, monkeypatch, hosted):
    if not hosted:
        monkeypatch.setattr(config, "PRODUCTION", False)
    name = sessions.cookie_name()
    client = production() if hosted else local_client().__enter__()
    try:
        sso_login(client, eve, new_id(), "Fictional twin pilot")
        raw = client.cookies.get(name)
        assert signed_in(client)
        for header in (f"{name}={raw}; {name}={raw}", f"{name}=other; {name}={raw}"):
            response = profile(client, header)
            assert response.status_code == 303
            assert "Max-Age=0" in session_cookie(response, name)
        assert client.post("/pi/api/save", json={"guide_step": 1}, headers={
            "Cookie": f"{name}={raw}; {name}={raw}", "X-CSRF-Token": sessions._load(raw)["csrf"]}).status_code == 403
    finally:
        if not hosted:
            client.__exit__(None, None, None)
