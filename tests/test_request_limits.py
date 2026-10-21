"""Login starts and planner computations are bounded per network / profile before any work starts."""
from __future__ import annotations

from astracore import config, db
from astracore.core import auth, ratelimit
from astracore.core.ratelimit import WINDOW, RequestLimiter, client_network
from astracore.modules.pi import service

from test_core import browser, csrf, eve, new_id, sso_login  # noqa: F401


def scope(peer="127.0.0.1", headers=()):
    return {"client": (peer, 1234), "headers": [(k.encode(), v.encode()) for k, v in headers]}


def test_window_boundary_and_retry_after_without_counting_rejections():
    limiter = RequestLimiter()
    assert [limiter.check(("k",), 2, now) for now in (0, 10)] == [0, 0]
    assert limiter.check(("k",), 2, 30) == 30           # until the first request leaves the window
    assert limiter.check(("k",), 2, 59.5) == 1
    assert limiter.check(("k",), 2, WINDOW) == 0         # the first request has left the window
    assert limiter.check(("k",), 2, WINDOW + 1) == 9     # rejections never pushed the window forward
    assert limiter.check(("other",), 2, WINDOW + 1) == 0


def test_storage_is_bounded_and_drops_the_least_recently_used_bucket():
    limiter = RequestLimiter(max_keys=3)
    for n in range(3):
        limiter.check((n,), 1, 0)
    assert limiter.check((0,), 1, 1) > 0                 # touching 0 makes 1 the oldest bucket
    limiter.check((3,), 1, 2)
    assert list(limiter.buckets) == [(2,), (0,), (3,)]
    for n in range(1000):
        limiter.check(("burst", n), 5, 3)
    assert len(limiter.buckets) == 3
    assert all(len(events) <= 5 for events in limiter.buckets.values())


def test_forwarded_addresses_are_only_trusted_behind_the_production_tunnel(monkeypatch):
    spoofed = [("cf-connecting-ip", "198.51.100.9"), ("x-forwarded-for", "192.0.2.1")]
    monkeypatch.setattr(config, "PRODUCTION", False)
    assert client_network(scope("127.0.0.1", spoofed)) == "127.0.0.1"
    monkeypatch.setattr(config, "PRODUCTION", True)
    assert client_network(scope("127.0.0.1", spoofed)) == "198.51.100.9"
    assert client_network(scope("127.0.0.1", [("x-forwarded-for", "192.0.2.1")])) == "127.0.0.1"
    ambiguous = [("cf-connecting-ip", "198.51.100.9"), ("cf-connecting-ip", "198.51.100.10")]
    assert client_network(scope("127.0.0.1", ambiguous)) == "127.0.0.1"
    assert client_network(scope("127.0.0.1", [("cf-connecting-ip", "not-an-address")])) == "127.0.0.1"
    # One IPv6 connection usually owns a whole /64; a mapped IPv4 address is that IPv4 address.
    assert client_network(scope("127.0.0.1", [("cf-connecting-ip", "2001:db8:1:2::5")])) == "2001:db8:1:2::/64"
    assert client_network(scope("2001:db8:1:2:aaaa::1")) == "2001:db8:1:2::/64"
    assert client_network(scope("::ffff:203.0.113.4")) == "203.0.113.4"


def test_login_starts_are_limited_per_network_before_oauth_state(browser, eve, monkeypatch):
    monkeypatch.setattr(ratelimit, "LOGIN_LIMIT", 2)
    states = []
    new_state = auth._new_state
    monkeypatch.setattr(auth, "_new_state", lambda *a, **kw: states.append(1) or new_state(*a, **kw))
    client = browser()
    for _ in range(2):
        assert client.get("/auth/login", follow_redirects=False).status_code == 303
    with db.session() as c:
        sessions_before = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    # Locally, made-up forwarding headers don't choose another bucket.
    rejected = client.get("/auth/login", follow_redirects=False,
                          headers={"CF-Connecting-IP": "198.51.100.1", "X-Forwarded-For": "198.51.100.2"})
    assert rejected.status_code == 429
    assert 1 <= int(rejected.headers["retry-after"]) <= WINDOW
    assert rejected.headers["cache-control"] == "no-store"
    assert "Too many sign-in attempts from your network" in rejected.text and "Please wait" in rejected.text
    assert client.get("/auth/community", follow_redirects=False).status_code == 429
    assert client.get(f"/auth/upgrade/{new_id()}", follow_redirects=False).status_code == 429
    assert len(states) == 2
    with db.session() as c:
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == sessions_before
    # Callbacks, pages, assets and health checks are never limited.
    assert client.get("/auth/callback?code=x&state=y", follow_redirects=False).status_code != 429
    for path in ("/", "/about", "/healthz", "/static/css/astracore.css", "/favicon.ico"):
        assert client.get(path).status_code == 200, path
    # Another network has its own allowance.
    from starlette.testclient import TestClient
    from astracore.app import app
    with TestClient(app, client=("203.0.113.7", 50000)) as other:
        assert other.get("/auth/login", follow_redirects=False).status_code == 303


def test_planner_computations_are_limited_per_profile_before_solving(browser, eve, monkeypatch):
    monkeypatch.setattr(ratelimit, "PLANNER_LIMIT", 2)
    solves = []

    async def solve(profile_id, settings):
        solves.append(profile_id)
        return {"totals": {"isk_per_day": 1, "colonies": 0}, "warnings": [], "characters": [], "colonies": []}

    monkeypatch.setattr(service, "solve", solve)
    first, second = browser(), browser()
    sso_login(first, eve, new_id(), "Fictional limit pilot")
    sso_login(second, eve, new_id(), "Fictional other pilot")
    token = csrf(first)
    for _ in range(2):
        assert first.post("/pi/api/suggest", json={}, headers={"X-CSRF-Token": token}).status_code == 200
    rejected = first.post("/pi/api/suggest", json={}, headers={"X-CSRF-Token": token})
    assert rejected.status_code == 429
    body = rejected.json()
    assert body["error"].startswith("Too many planning requests") and body["retry_after"] >= 1
    assert rejected.headers["retry-after"] == str(body["retry_after"])
    assert first.post("/pi/api/whatif", json={"options": []}, headers={"X-CSRF-Token": token}).status_code == 429
    assert len(solves) == 2
    # Saving answers and normal pages aren't computations.
    assert first.post("/pi/api/save", json={"guide_step": 1}, headers={"X-CSRF-Token": token}).status_code == 200
    assert first.get("/profile").status_code == 200
    # Another profile plans independently.
    assert second.post("/pi/api/suggest", json={}, headers={"X-CSRF-Token": csrf(second)}).status_code == 200
    assert len(solves) == 3


def test_signed_out_planner_requests_are_not_counted(browser):
    client = browser()
    for _ in range(ratelimit.PLANNER_LIMIT + 1):
        assert client.post("/pi/api/suggest", json={}).status_code != 429
    assert not ratelimit.LIMITER.buckets
