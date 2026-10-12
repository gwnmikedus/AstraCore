"""Core: migration, login flows, scopes, sessions/CSRF, isolation between profiles, revocation, the solve gate.

EVE SSO and ESI are faked: `exchange_code` returns prepared logins, `revoke` records what it was asked
to revoke, the post-login ESI sync is a no-op.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from astracore import db
from astracore.core import accounts, auth, crypto, registry, sessions
from astracore.core.solvegate import Busy, SolveGate, Superseded
from astracore.esi import sso

PI_SCOPES = " ".join(registry.get("pi").required_bundle.scopes)
CUSTOMS = "esi-planets.read_customs_offices.v1"
WAYPOINT = "esi-ui.write_waypoint.v1"
_ids = iter(range(91_000_000, 92_000_000))


def new_id() -> int:
    return next(_ids)


# --------------------------------------------------------------------------- fakes
class FakeEVE:
    def __init__(self):
        self.logins = {}
        self.revoked = []
        self.affiliation = {}
        self.n = 0

    def login(self, cid, name, scopes=PI_SCOPES, owner="owner-1") -> str:
        self.n += 1
        code = f"code-{self.n}"
        self.logins[code] = {"character_id": cid, "name": name, "owner": owner, "scopes": scopes,
                             "refresh_token": f"rt-{cid}-{self.n}", "access_token": f"at-{cid}-{self.n}",
                             "expires_in": 1199}
        return code


@pytest.fixture()
def eve(monkeypatch):
    fake = FakeEVE()

    async def exchange_code(code):
        return dict(fake.logins[code])

    async def revoke(rt):
        fake.revoked.append(rt)
        return True

    async def no_sync(cid):
        return ""

    async def affiliation(cid):
        return dict(fake.affiliation.get(cid, {}))

    monkeypatch.setattr(sso, "exchange_code", exchange_code)
    monkeypatch.setattr(sso, "revoke", revoke)
    monkeypatch.setattr(auth, "_refresh_character", no_sync)
    monkeypatch.setattr(auth, "_affiliation", affiliation)
    return fake


@pytest.fixture()
def browser():
    from astracore.app import app
    clients = []

    def make():
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c
    yield make
    for c in clients:
        c.__exit__(None, None, None)


def sso_login(client, eve, cid, name, path="/auth/login", **kw):
    """Run one EVE SSO round trip. Returns (callback response, authorize URL)."""
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303, r.text
    url = r.headers["location"]
    state = parse_qs(urlparse(url).query)["state"][0]
    code = eve.login(cid, name, **kw)
    cb = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    return cb, url


def csrf(client) -> str:
    html = client.get("/profile").text
    return re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)


def me(client):
    sess = client.cookies.get(sessions.COOKIE)
    s = sessions._load(sess)
    return s["profile_id"] if s else None


def scopes_in(url: str) -> set:
    return set(parse_qs(urlparse(url).query).get("scope", [""])[0].split())


# --------------------------------------------------------------------------- migration
def _mvp_db(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA_V1)
    db._migrate_v1(c)
    c.execute("INSERT INTO characters(character_id, name, source, slots, ccu_level, enabled) VALUES(2001,'Alpha','esi',6,5,1)")
    c.execute("INSERT INTO characters(character_id, name, source, slots, ccu_level, enabled) VALUES(2002,'Beta','esi',5,4,0)")
    c.execute("INSERT INTO tokens(character_id, refresh_token, access_token, expires_at, scopes) VALUES(2001,'rt-a','at-a',1,'x y')")
    c.execute("INSERT INTO tokens(character_id, refresh_token, access_token, expires_at, scopes) VALUES(2002,'rt-b',NULL,0,'x')")
    c.execute("INSERT INTO kv(key, value) VALUES('settings', ?)", (json.dumps({"effort": 77, "hub_system": "7G-QIG"}),))
    c.execute("INSERT INTO kv(key, value) VALUES('price_books_v1', '{}')")
    c.execute("INSERT INTO plan_runs(created, label, settings_json, result_json) VALUES(1, 'old', '{}', '{\"totals\": {}}')")
    c.execute("INSERT INTO planet_overrides VALUES(40000001, 1.3)")
    c.commit()
    c.close()


def test_migration_from_mvp_database(tmp_path, monkeypatch):
    path = tmp_path / "mvp.sqlite3"
    _mvp_db(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    assert db.migrate() == len(db.MIGRATIONS)
    assert db.migrate() == len(db.MIGRATIONS)          # idempotent
    with db.session() as c:
        profiles = c.execute("SELECT * FROM profiles").fetchall()
        assert len(profiles) == 1
        pid = profiles[0]["id"]
        rows = c.execute("SELECT character_id, profile_id, enabled, eve_account_id FROM characters ORDER BY character_id").fetchall()
        assert [(r[0], r[1], r[2], r[3]) for r in rows] == [(2001, pid, 1, None), (2002, pid, 0, None)]
        raw = c.execute("SELECT refresh_token_enc FROM tokens WHERE character_id=2001").fetchone()[0]
        assert raw != "rt-a"                                      # encrypted at rest
        assert c.execute("SELECT profile_id FROM plan_runs").fetchone()[0] == pid
        assert c.execute("SELECT profile_id, planet_id FROM planet_overrides").fetchone()[:] == (pid, 40000001)
        assert c.execute("SELECT value FROM kv WHERE key='settings'").fetchone() is None
        assert c.execute("SELECT value FROM kv WHERE key='price_books_v1'").fetchone() is not None   # shared caches stay
    assert db.get_token(2001)["refresh_token"] == "rt-a"
    assert db.module_settings(pid, "pi")["effort"] == 77
    p = db.get_profile(pid)
    assert p["display_name"] == "Alpha" and p["main_character_id"] == 2001


def test_crypto_round_trip():
    tok = crypto.encrypt("secret-refresh-token")
    assert tok and "secret" not in tok
    assert crypto.decrypt(tok) == "secret-refresh-token"
    assert crypto.decrypt("garbage") is None


# --------------------------------------------------------------------------- login flows (§4.1)
def test_fresh_signin_requests_exactly_pi_required(browser, eve):
    c = browser()
    r = c.get("/auth/login", follow_redirects=False)
    assert scopes_in(r.headers["location"]) == set(PI_SCOPES.split())


def test_signed_out_unknown_creates_profile_and_onboards(browser, eve):
    c = browser()
    cid = new_id()
    r, _ = sso_login(c, eve, cid, "Newbie")
    assert r.status_code == 303 and r.headers["location"] == "/welcome"
    pid = me(c)
    assert pid and db.get_profile(pid)["display_name"] == "Newbie"
    assert db.character_profile(cid) == pid
    assert db.get_token(cid)["refresh_token"].startswith(f"rt-{cid}")
    cookie = [h for h in r.headers.get_list("set-cookie") if h.startswith("ac_session=")][-1]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Secure" not in cookie            # local mode is plain http


def test_new_pilot_can_choose_home_without_completing_welcome(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "New navigator")
    assert not db.get_profile(me(c))["onboarded"]
    response = c.get("/", follow_redirects=False)
    assert response.status_code == 200 and "Choose your operating area" in response.text
    assert c.get("/welcome").status_code == 200


def test_visiting_pi_completes_welcome_and_uses_setup_entry(browser, eve, monkeypatch):
    from astracore.modules.pi import service
    c = browser()
    sso_login(c, eve, new_id(), "Setup navigator")
    pid = me(c)
    assert not db.get_profile(pid)["onboarded"]
    monkeypatch.setattr(service, "entry_state", lambda profile_id: "area")
    response = c.get("/pi", follow_redirects=False)
    assert response.headers["location"] == "/pi/area"
    assert db.get_profile(pid)["onboarded"]
    assert c.get("/", follow_redirects=False).status_code == 200


def test_signed_out_known_character_signs_into_its_profile(browser, eve):
    a, b = new_id(), new_id()
    c1 = browser()
    sso_login(c1, eve, a, "Main")
    pid = me(c1)
    sso_login(c1, eve, b, "Alt", path="/auth/login?intent=add")
    c2 = browser()                                   # another browser, log in with the *alt*
    r, _ = sso_login(c2, eve, b, "Alt")
    assert r.headers["location"].startswith("/") and me(c2) == pid


def test_add_unknown_character_links_to_current_profile(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "One")
    pid = me(c)
    other = new_id()
    r, _ = sso_login(c, eve, other, "Two", path="/auth/login?intent=add")
    assert "Added" in r.headers["location"] or "Added" in parse_qs(urlparse(r.headers["location"]).query)["msg"][0]
    assert db.character_profile(other) == pid


def test_add_character_already_in_profile_refreshes_token(browser, eve):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Same")
    old = db.get_token(cid)["refresh_token"]
    r, _ = sso_login(c, eve, cid, "Same", path="/auth/login?intent=add")
    msg = parse_qs(urlparse(r.headers["location"]).query)["msg"][0]
    assert "updated" in msg
    assert db.get_token(cid)["refresh_token"] != old
    assert old in eve.revoked                                     # the replaced token is revoked


def test_add_character_of_other_profile_move(browser, eve):
    x, y = new_id(), new_id()
    c1, c2 = browser(), browser()
    sso_login(c1, eve, x, "Owner1")
    sso_login(c1, eve, y, "Shared", path="/auth/login?intent=add")
    p1 = me(c1)
    sso_login(c2, eve, new_id(), "Owner2")
    p2 = me(c2)
    r, _ = sso_login(c2, eve, y, "Shared", path="/auth/login?intent=add")
    assert r.headers["location"] == "/auth/choose"
    assert "Move Shared to this profile" in c2.get("/auth/choose").text
    assert db.character_profile(y) == p1                        # nothing moved before the choice
    c2.post("/auth/choose", data={"action": "move", "csrf_token": csrf(c2)})
    assert db.character_profile(y) == p2 and db.character_profile(x) == p1


def test_last_character_of_other_profile_offers_merge(browser, eve):
    lone, mine = new_id(), new_id()
    c1, c2 = browser(), browser()
    sso_login(c1, eve, lone, "Lonely")
    p1 = me(c1)
    from astracore.modules.pi import store
    from astracore.modules.pi.settings import Settings
    store.save_plan_run(p1, "their plan", Settings(), {"totals": {}})
    sso_login(c2, eve, mine, "Keeper")
    p2 = me(c2)
    store.save_settings(p2, Settings(effort=12))
    sso_login(c2, eve, lone, "Lonely", path="/auth/login?intent=add")
    page = c2.get("/auth/choose").text
    assert "Merge the two profiles" in page
    c2.post("/auth/choose", data={"action": "merge", "csrf_token": csrf(c2)})
    assert db.get_profile(p1) is None                            # folded in
    assert db.character_profile(lone) == p2
    assert [p["label"] for p in store.list_plan_runs(p2)] == ["their plan"]
    assert store.load_settings(p2).effort == 12                  # current profile's settings win
    assert me(c1) is None                                        # the old profile's sessions are gone


def test_merge_is_refused_when_the_other_profile_has_more_characters(browser, eve):
    a, b = new_id(), new_id()
    c1, c2 = browser(), browser()
    sso_login(c1, eve, a, "Stays")
    sso_login(c1, eve, b, "Shared", path="/auth/login?intent=add")
    p1 = me(c1)
    sso_login(c2, eve, new_id(), "Other")
    p2 = me(c2)
    sso_login(c2, eve, b, "Shared", path="/auth/login?intent=add")
    assert "Merge the two profiles" not in c2.get("/auth/choose").text
    c2.post("/auth/choose", data={"action": "merge", "csrf_token": csrf(c2)})   # forged choice
    assert db.get_profile(p1) is not None                        # the other profile isn't taken
    assert db.character_profile(a) == p1                         # nor its other characters
    assert db.character_profile(b) == p2                         # only the proven character moves


def test_authenticated_esi_cache_is_per_character_and_deleted_with_it():
    import httpx
    from astracore.esi.client import ESIClient

    calls = []

    def api(request):
        calls.append(request.headers["authorization"])
        return httpx.Response(200, json={"who": request.headers["authorization"]},
                              headers={"expires": "Fri, 01 Jan 2100 00:00:00 GMT"})

    async def run():
        async with ESIClient() as esi:
            esi._client = httpx.AsyncClient(transport=httpx.MockTransport(api))
            first = await esi.get("/corporations/1/customs_offices/", token="A", owner=111)
            second = await esi.get("/corporations/1/customs_offices/", token="B", owner=222)
            again = await esi.get("/corporations/1/customs_offices/", token="A2", owner=111)
            return first, second, again

    first, second, again = asyncio.run(run())
    assert first["who"] == "Bearer A" and second["who"] == "Bearer B"   # never another character's copy
    assert again["who"] == "Bearer A" and len(calls) == 2               # fresh copy reused for its owner
    with db.session() as c:
        db.forget_character_cache(c, 111)
        left = [r[0] for r in c.execute("SELECT url FROM http_cache WHERE url LIKE '%customs_offices%'")]
    assert left and all(u.endswith("#auth:222") for u in left)


def test_authenticated_esi_call_requires_its_character():
    from astracore.esi.client import ESIClient

    async def run():
        async with ESIClient() as esi:
            await esi.get("/characters/1/assets/", token="A")

    with pytest.raises(ValueError):
        asyncio.run(run())


def test_removing_a_character_deletes_its_cached_esi_data(browser, eve):
    c = browser()
    keep, gone = new_id(), new_id()
    sso_login(c, eve, keep, "Keep")
    sso_login(c, eve, gone, "Gone", path="/auth/login?intent=add")
    with db.session() as conn:
        for cid in (keep, gone):
            conn.execute("REPLACE INTO http_cache(url, body, etag, expires) VALUES(?,?,?,?)",
                         (f"https://esi/x/wallet/journal/?#auth:{cid}", "[]", None, 9e9))
    c.post(f"/profile/characters/{gone}/remove", data={"csrf_token": csrf(c)})
    with db.session() as conn:
        urls = [r[0] for r in conn.execute("SELECT url FROM http_cache WHERE url LIKE '%wallet/journal%'")]
    assert urls == [f"https://esi/x/wallet/journal/?#auth:{keep}"]


def test_cancel_move_revokes_the_fresh_token(browser, eve):
    a, b = new_id(), new_id()
    c1, c2 = browser(), browser()
    sso_login(c1, eve, a, "A")
    sso_login(c1, eve, b, "B", path="/auth/login?intent=add")
    sso_login(c2, eve, new_id(), "C")
    sso_login(c2, eve, b, "B", path="/auth/login?intent=add")
    fresh = list(eve.logins.values())[-1]["refresh_token"]
    c2.post("/auth/choose", data={"action": "cancel", "csrf_token": csrf(c2)})
    assert db.character_profile(b) == me(c1) and fresh in eve.revoked


def test_upgrade_returning_other_character_is_handled_as_add(browser, eve):
    a, other = new_id(), new_id()
    c = browser()
    sso_login(c, eve, a, "Picked")
    r, _ = sso_login(c, eve, other, "Surprise", path=f"/auth/upgrade/{a}")
    msg = parse_qs(urlparse(r.headers["location"]).query)["msg"][0]
    assert "You authorised Surprise" in msg and "Picked" in msg
    assert db.character_profile(other) == me(c)


def test_state_is_single_use_and_bound_to_the_browser(browser, eve):
    c1, c2 = browser(), browser()
    url = c1.get("/auth/login", follow_redirects=False).headers["location"]
    state = parse_qs(urlparse(url).query)["state"][0]
    code = eve.login(new_id(), "Stolen")
    r = c2.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)   # other browser
    assert me(c2) is None and "cancelled or expired" in parse_qs(urlparse(r.headers["location"]).query)["msg"][0]
    r = c1.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)   # already consumed
    assert me(c1) is None


# --------------------------------------------------------------------------- optional bundles
def test_opt_in_and_opt_out_round_trip(browser, eve):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Director")
    r, url = sso_login(c, eve, cid, "Director", path=f"/auth/upgrade/{cid}?bundle=pi.optional.customs&action=on",
                       scopes=PI_SCOPES + " " + CUSTOMS)
    assert scopes_in(url) == set(PI_SCOPES.split()) | {CUSTOMS}
    ch = db.get_character(cid)
    assert auth.bundle_active(ch, "pi.optional.customs")
    # a plain sign-in later must not silently drop the opted-in bundle
    sso_login(browser(), eve, cid, "Director")
    assert auth.bundle_active(db.get_character(cid), "pi.optional.customs")
    # pause without a login: granted but unused
    c.post(f"/profile/characters/{cid}/bundles/pi.optional.customs/pause", data={"csrf_token": csrf(c)})
    ch = db.get_character(cid)
    assert CUSTOMS in ch["scopes"] and not auth.bundle_active(ch, "pi.optional.customs")
    assert "Off in AstraCore" in c.get("/profile").text
    # opt out with a new login asking for the smaller set
    r, url = sso_login(c, eve, cid, "Director", path=f"/auth/upgrade/{cid}?bundle=pi.optional.customs&action=off")
    assert CUSTOMS not in scopes_in(url)
    ch = db.get_character(cid)
    assert CUSTOMS not in ch["scopes"] and not auth.bundle_active(ch, "pi.optional.customs")


def test_upgrade_keeps_other_optional_bundles(browser, eve):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "Pilot")
    sso_login(c, eve, cid, "Pilot", path=f"/auth/upgrade/{cid}?bundle=pi.optional.waypoints&action=on",
              scopes=PI_SCOPES + " " + WAYPOINT)
    _, url = c.get(f"/auth/upgrade/{cid}?bundle=pi.optional.customs&action=on", follow_redirects=False), None
    url = c.get(f"/auth/upgrade/{cid}?bundle=pi.optional.customs&action=on", follow_redirects=False).headers["location"]
    assert scopes_in(url) == set(PI_SCOPES.split()) | {WAYPOINT, CUSTOMS}


# --------------------------------------------------------------------------- remove / reset
def test_remove_character_revokes_and_deletes(browser, eve):
    c = browser()
    a, b = new_id(), new_id()
    sso_login(c, eve, a, "Keep")
    sso_login(c, eve, b, "Drop", path="/auth/login?intent=add")
    rt = db.get_token(b)["refresh_token"]
    c.post(f"/profile/characters/{b}/remove", data={"csrf_token": csrf(c)})
    assert rt in eve.revoked
    assert db.get_character(b) is None and db.get_token(b) is None
    assert me(c) is not None                                   # still signed in


def test_removing_the_last_character_requires_reset(browser, eve):
    c = browser()
    a = new_id()
    sso_login(c, eve, a, "Only")
    r = c.post(f"/profile/characters/{a}/remove", data={"csrf_token": csrf(c)}, follow_redirects=False)
    assert r.headers["location"].startswith("/profile/reset") and db.get_character(a)


def test_reset_profile_revokes_everything_and_leaves_no_rows(browser, eve):
    from astracore.modules.pi import store
    from astracore.modules.pi.settings import Settings
    c = browser()
    a, b = new_id(), new_id()
    sso_login(c, eve, a, "Gone")
    sso_login(c, eve, b, "Also", path="/auth/login?intent=add")
    pid = me(c)
    acc = db.create_account(pid, "Main")
    db.assign_account(pid, a, acc)
    store.save_settings(pid, Settings(effort=5))
    store.save_plan_run(pid, "p", Settings(), {"totals": {}})
    store.set_planet_override(pid, 40000002, 1.1)
    tokens = [db.get_token(x)["refresh_token"] for x in (a, b)]
    token = csrf(c)
    r = c.post("/profile/reset", data={"csrf_token": token, "confirm": "wrong"}, follow_redirects=False)
    assert db.get_profile(pid)                                 # type-to-confirm
    c.post("/profile/reset", data={"csrf_token": token, "confirm": "Gone"})
    assert set(tokens) <= set(eve.revoked)
    with db.session() as conn:
        for table in ("characters", "eve_accounts", "module_settings", "plan_runs", "planet_overrides", "sessions"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE profile_id=?", (pid,)).fetchone()[0] == 0, table
        assert conn.execute("SELECT COUNT(*) FROM tokens WHERE character_id IN (?,?)", (a, b)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM profiles WHERE id=?", (pid,)).fetchone()[0] == 0
    assert me(c) is None


def test_reset_only_pi_keeps_characters(browser, eve):
    from astracore.modules.pi import store
    from astracore.modules.pi.settings import Settings
    c = browser()
    a = new_id()
    sso_login(c, eve, a, "Planner")
    pid = me(c)
    store.save_settings(pid, Settings(effort=9))
    store.save_plan_run(pid, "p", Settings(), {"totals": {}})
    token = csrf(c)
    assert "Type <strong>Planner</strong> to confirm" in c.get("/pi/reset").text
    for confirm in (None, "wrong"):
        data = {"csrf_token": token}
        if confirm is not None:
            data["confirm"] = confirm
        response = c.post("/pi/reset", data=data, follow_redirects=False)
        assert response.headers["location"].startswith("/pi/reset")
        assert store.list_plan_runs(pid) and store.has_settings(pid)
    c.post("/pi/reset", data={"csrf_token": token, "confirm": "Planner"})
    assert not store.list_plan_runs(pid) and not store.has_settings(pid)
    assert db.character_profile(a) == pid


# --------------------------------------------------------------------------- token lifecycle
def test_owner_hash_change_on_refresh_unlinks(browser, eve, monkeypatch):
    c = browser()
    a, b = new_id(), new_id()
    sso_login(c, eve, a, "Seller", owner="owner-A")
    sso_login(c, eve, b, "Sold", owner="owner-B", path="/auth/login?intent=add")
    pid = me(c)
    with db.session() as conn:
        conn.execute("UPDATE tokens SET expires_at=0 WHERE character_id=?", (b,))

    class Resp:
        status_code = 200

        def json(self):
            return {"access_token": "new", "refresh_token": "rt-new", "expires_in": 1199}

    async def token_request(data):
        return Resp()

    async def validate(tok):
        return {"sub": f"CHARACTER:EVE:{b}", "owner": "someone-else", "scp": PI_SCOPES.split()}

    monkeypatch.setattr(sso, "_token_request", token_request)
    monkeypatch.setattr(sso, "validate", validate)
    with pytest.raises(sso.Transferred):
        asyncio.run(sso.access_token(b))
    assert db.get_character(b) is None and db.get_token(b) is None
    assert any("transferred" in n["text"] for n in db.pop_notices(pid))


def test_invalid_grant_marks_needs_login_and_keeps_data(browser, eve, monkeypatch):
    c = browser()
    a = new_id()
    sso_login(c, eve, a, "Revoked")
    db.set_character(a, colonies=[{"planet_id": 1}])
    with db.session() as conn:
        conn.execute("UPDATE tokens SET expires_at=0 WHERE character_id=?", (a,))

    class Resp:
        status_code = 400

        def json(self):
            return {"error": "invalid_grant"}

    async def token_request(data):
        return Resp()

    monkeypatch.setattr(sso, "_token_request", token_request)
    with pytest.raises(sso.NeedsLogin):
        asyncio.run(sso.access_token(a))
    ch = db.get_character(a)
    assert ch["status"] == "needs_login" and ch["colonies"] == [{"planet_id": 1}]
    db.update_profile(me(c), onboarded=1)
    assert "needs a new EVE login" in c.get("/").text


def test_login_with_new_owner_hash_takes_character_from_old_profile(browser, eve):
    c1, c2 = browser(), browser()
    a, keep = new_id(), new_id()
    sso_login(c1, eve, keep, "Stays", owner="o-keep")
    sso_login(c1, eve, a, "Bought", owner="old-owner", path="/auth/login?intent=add")
    p1 = me(c1)
    r, _ = sso_login(c2, eve, a, "Bought", owner="new-owner")
    assert r.headers["location"] == "/welcome"
    assert db.character_profile(a) == me(c2) != p1


# --------------------------------------------------------------------------- JWT validation
def test_jwt_validation_checks_signature_issuer_audience_expiry(monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="JWT-Signature-Key", alg="RS256")

    async def fake_jwks(force=False):
        return {"keys": [jwk]}

    monkeypatch.setattr(sso, "jwks", fake_jwks)

    def token(**over):
        claims = {"sub": "CHARACTER:EVE:123", "name": "Pilot", "owner": "abc", "scp": ["a"],
                  "iss": "https://login.eveonline.com", "aud": ["test-client", "EVE Online"],
                  "exp": int(time.time()) + 600}
        claims.update(over)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "JWT-Signature-Key"})

    assert asyncio.run(sso.validate(token()))["owner"] == "abc"
    for bad in (token(aud=["someone-else", "EVE Online"]), token(iss="https://evil.example"),
                token(exp=int(time.time()) - 600)):
        with pytest.raises(sso.SSOError):
            asyncio.run(sso.validate(bad))
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"sub": "CHARACTER:EVE:1", "iss": "https://login.eveonline.com", "aud": "test-client",
                         "exp": int(time.time()) + 600}, other, algorithm="RS256", headers={"kid": "JWT-Signature-Key"})
    with pytest.raises(sso.SSOError):
        asyncio.run(sso.validate(forged))


# --------------------------------------------------------------------------- invite gate
def test_invite_gate_blocks_unlisted_and_passes_listed_corp(browser, eve, monkeypatch):
    from astracore import config
    monkeypatch.setattr(config, "ACCESS_GATE", True)
    c = browser()
    stranger = new_id()
    r, _ = sso_login(c, eve, stranger, "Stranger")
    assert r.status_code == 403 and "invite-only" in r.text
    assert db.get_character(stranger) is None and me(c) is None
    assert list(eve.logins.values())[-1]["refresh_token"] in eve.revoked
    friend = new_id()
    eve.affiliation[friend] = {"corporation_id": 98000123, "corporation_name": "Friends", "alliance_id": None}
    db.access_add("corporation", 98000123, "Friends")
    r, _ = sso_login(browser(), eve, friend, "Friend")
    assert r.headers["location"] == "/welcome" and db.get_character(friend)["corporation_id"] == 98000123


# --------------------------------------------------------------------------- CSRF + sessions
def test_csrf_required_on_post(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Careful")
    assert c.post("/profile/accounts", data={"name": "X"}).status_code == 403
    assert c.post("/pi/api/save", json={"effort": 1}).status_code == 403
    assert c.post("/pi/api/save", json={"effort": 1}, headers={"X-CSRF-Token": "nope"}).status_code == 403
    assert c.post("/pi/api/save", json={"effort": 1}, headers={"X-CSRF-Token": csrf(c)}).status_code == 200
    assert c.post("/profile/accounts", data={"name": "X", "csrf_token": csrf(c)}, follow_redirects=False).status_code == 303


def test_sign_in_rotates_the_session_and_sign_out_everywhere(browser, eve):
    c = browser()
    c.get("/auth/login", follow_redirects=False)
    before = c.cookies.get(sessions.COOKIE)
    a = new_id()
    sso_login(c, eve, a, "Rotator")
    assert c.cookies.get(sessions.COOKIE) != before            # no session fixation
    c2 = browser()
    sso_login(c2, eve, a, "Rotator")
    assert me(c) == me(c2)
    c.post("/auth/logout-everywhere", data={"csrf_token": csrf(c)})
    assert me(c) is None and me(c2) is None


def test_flash_messages_cannot_be_forged(browser):
    c = browser()
    assert "Send ISK to" not in c.get("/?msg=Send+ISK+to+scammer").text


# --------------------------------------------------------------------------- isolation between profiles
def test_profiles_cannot_touch_each_other(browser, eve):
    from astracore.modules.pi import store
    from astracore.modules.pi.settings import Settings
    ca, cb = browser(), browser()
    a1, a2, b1 = new_id(), new_id(), new_id()
    sso_login(ca, eve, a1, "Alice")
    sso_login(ca, eve, a2, "AliceAlt", path="/auth/login?intent=add")
    sso_login(cb, eve, b1, "Bob")
    pa, pb = me(ca), me(cb)
    acc = db.create_account(pa, "Alice main")
    db.assign_account(pa, a1, acc)
    store.save_settings(pa, Settings(effort=33))
    run = store.save_plan_run(pa, "alice plan", Settings(), {"totals": {}, "characters": []}, active=True)
    store.set_planet_override(pa, 40000009, 1.4)
    a_session = sessions.list_sessions(pa)[0]["id_hash"]
    before = (db.list_characters(pa), db.list_accounts(pa), store.list_plan_runs(pa), store.planet_overrides(pa),
              store.load_settings(pa).to_json(), db.get_profile(pa)["main_character_id"])
    t = csrf(cb)
    attempts = [
        ("post", f"/pi/characters/{a1}/toggle", {}),
        ("post", f"/profile/characters/{a2}/remove", {}),
        ("post", f"/profile/characters/{a1}/account", {"account_id": ""}),
        ("post", f"/profile/characters/{b1}/account", {"account_id": str(acc)}),
        ("post", f"/profile/accounts/{acc}/rename", {"name": "pwned"}),
        ("post", f"/profile/accounts/{acc}/delete", {}),
        ("post", "/profile/main", {"character_id": str(a1)}),
        ("post", f"/profile/characters/{a1}/bundles/pi.optional.customs/pause", {}),
        ("post", f"/profile/sessions/{a_session}/end", {}),
        ("post", f"/pi/plans/{run}/activate", {}),
        ("post", f"/pi/plans/{run}/delete", {}),
        ("post", "/profile/refresh", {"character_id": str(a1)}),
    ]
    for method, path, data in attempts:
        getattr(cb, method)(path, data={**data, "csrf_token": t}, follow_redirects=False)
    assert cb.post(f"/pi/api/plans/{run}/activate", headers={"X-CSRF-Token": t}).status_code == 404
    r = cb.post("/pi/api/waypoints", json={"character_id": a1, "systems": ["Jita"]}, headers={"X-CSRF-Token": t})
    assert r.status_code == 403
    assert cb.get(f"/auth/upgrade/{a1}", follow_redirects=False).headers["location"].startswith("/profile")
    for path in (f"/pi/export/plan.csv?plan={run}", f"/pi/export/plan.md?plan={run}",
                 f"/pi/export/templates.zip?plan={run}"):
        r = cb.get(path)
        assert r.status_code == 404 and "alice" not in r.text.lower()   # someone else's plan: not found, no solve
    export = cb.get("/profile/export.json").json()
    assert {c["character_id"] for c in export["characters"]} == {b1}
    assert "Alice" not in cb.get("/profile").text
    after = (db.list_characters(pa), db.list_accounts(pa), store.list_plan_runs(pa), store.planet_overrides(pa),
             store.load_settings(pa).to_json(), db.get_profile(pa)["main_character_id"])
    assert after == before
    assert a_session in {s["id_hash"] for s in sessions.list_sessions(pa)}
    assert db.character_profile(b1) == pb and db.get_character(b1)["eve_account_id"] is None


def test_admin_page_only_for_admin(browser, eve, monkeypatch):
    from astracore import config
    c = browser()
    sso_login(c, eve, new_id(), "Pleb")
    assert c.get("/admin").status_code == 404
    admin_id = next(iter(config.ADMIN_CHARACTER_IDS))
    if db.get_character(admin_id) is None:
        sso_login(c, eve, admin_id, "Boss", path="/auth/login?intent=add")
        assert c.get("/admin").status_code == 200


def test_eve_account_holds_at_most_three(browser, eve):
    c = browser()
    ids = [new_id() for _ in range(4)]
    sso_login(c, eve, ids[0], "One")
    for i, cid in enumerate(ids[1:]):
        sso_login(c, eve, cid, f"N{i}", path="/auth/login?intent=add")
    pid = me(c)
    acc = db.create_account(pid, "Full")
    assert [db.assign_account(pid, x, acc) for x in ids[:3]] == ["", "", ""]
    assert "already has 3" in db.assign_account(pid, ids[3], acc)


# --------------------------------------------------------------------------- solve gate
def test_solve_gate_limits_concurrency():
    gate = SolveGate(concurrency=2, wait_timeout=5)
    running, peak = [0], [0]

    def work():
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        time.sleep(0.15)
        running[0] -= 1
        return 1

    async def main():
        return await asyncio.gather(*[gate.run(work) for _ in range(6)])

    assert asyncio.run(main()) == [1] * 6
    assert peak[0] == 2


def test_solve_gate_cache_avoids_resolving():
    gate = SolveGate(concurrency=1)
    calls = []

    def work(x):
        calls.append(x)
        return x * 2

    async def main():
        a = await gate.cached("k1", work, 3)
        b = await gate.cached("k1", work, 3)
        c = await gate.cached("k2", work, 4)
        return a, b, c

    assert asyncio.run(main()) == (6, 6, 8)
    assert calls == [3, 4]


def test_solve_gate_newer_request_supersedes_waiting_one():
    gate = SolveGate(concurrency=1, wait_timeout=5)
    out = []

    async def req(name, hold):
        try:
            async with gate.request(1, "whatif"):
                await asyncio.sleep(hold)
                out.append(name)
        except Superseded:
            out.append(name + ":superseded")

    async def main():
        first = asyncio.create_task(req("first", 0.2))
        await asyncio.sleep(0.02)
        second = asyncio.create_task(req("second", 0))
        await asyncio.sleep(0.02)
        third = asyncio.create_task(req("third", 0))
        await asyncio.gather(first, second, third)

    asyncio.run(main())
    assert out == ["first", "second:superseded", "third"]


def test_solve_gate_reports_busy():
    gate = SolveGate(concurrency=1, wait_timeout=0.1)

    async def main():
        blocker = asyncio.create_task(gate.run(time.sleep, 0.5))
        await asyncio.sleep(0.05)
        with pytest.raises(Busy):
            await gate.run(time.sleep, 0)
        await blocker

    asyncio.run(main())


def test_whatif_returns_busy_503_when_gate_full(browser, eve, monkeypatch):
    from astracore.core import solvegate

    class Full:
        _cache = {}

        def request(self, *a, **k):
            raise Busy()

    import astracore.modules.pi.routes as pi_routes
    monkeypatch.setattr(pi_routes, "GATE", Full())
    c = browser()
    sso_login(c, eve, new_id(), "Queued")
    r = c.post("/pi/api/whatif", json={"base": {}, "options": []}, headers={"X-CSRF-Token": csrf(c)})
    assert r.status_code == 503 and r.json()["busy"] is True


def test_alliance_members_pass_the_gate(browser, eve, monkeypatch):
    from astracore import config
    monkeypatch.setattr(config, "ACCESS_GATE", True)
    monkeypatch.setitem(config.ALLOWED, "alliance", {99013537})
    pilot = new_id()
    eve.affiliation[pilot] = {"corporation_id": 98000999, "corporation_name": "Some corp", "alliance_id": 99013537}
    r, _ = sso_login(browser(), eve, pilot, "Ally")
    assert r.headers["location"] == "/welcome"


def test_admin_can_remove_people_but_not_admins(browser, eve):
    from astracore import config
    admin_id = next(iter(config.ADMIN_CHARACTER_IDS))
    ca = browser()
    if db.get_character(admin_id):
        sso_login(ca, eve, admin_id, "Boss")
    else:
        sso_login(ca, eve, new_id(), "Boss main")
        sso_login(ca, eve, admin_id, "Boss", path="/auth/login?intent=add")
    admin_pid = me(ca)
    cu = browser()
    user = new_id()
    sso_login(cu, eve, user, "Guest")
    guest_pid = me(cu)
    page = ca.get("/admin").text
    assert "People" in page and "Guest" in page
    t = csrf(ca)
    ca.post(f"/admin/people/{admin_pid}/remove", data={"csrf_token": t})
    assert db.get_profile(admin_pid)
    ca.post(f"/admin/people/{guest_pid}/remove", data={"csrf_token": t})
    assert db.get_profile(guest_pid) is None and db.get_character(user) is None
    assert me(cu) is None
    # non-admins can't
    other = browser()
    sso_login(other, eve, new_id(), "Nope")
    assert other.post(f"/admin/people/{admin_pid}/remove", data={"csrf_token": csrf(other)},
                      follow_redirects=False).status_code == 303 and db.get_profile(admin_pid)


def test_footer_credits_the_app_not_ccp_and_credits_page():
    from astracore.app import app
    with TestClient(app) as c:
        home = c.get("/").text
        assert "AstraCore</strong> © 2026" in home and 'href="/credits"' in home
        assert "used under the EVE Developer License: © 2014 CCP hf." in home
        page = c.get("/credits").text
        assert "DalShooth" in page and "Barlow" in page and "Fuzzwork" in page
