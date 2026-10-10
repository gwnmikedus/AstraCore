"""Feedback consent/isolation and GitHub delivery under failures. No real API calls."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import time
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from astracore import config, db
from astracore.core import community
from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_community(monkeypatch):
    with db.session() as c:
        c.executescript(community.SCHEMA)
        for table in ("community_feedback", "community_issues", "community_webhooks"):
            c.execute(f"DELETE FROM {table}")
        c.execute("UPDATE community_sync SET last_success=0,next_poll_at=0,problem='' WHERE id=1")
    monkeypatch.setitem(config._ENV, "ASTRACORE_GITHUB_REPOSITORY", "gwnmikedus/AstraCore")
    for key in ("APP_ID", "INSTALLATION_ID", "PRIVATE_KEY_PATH", "TOKEN", "WEBHOOK_SECRET"):
        monkeypatch.setitem(config._ENV, f"ASTRACORE_GITHUB_{key}", "")

    async def no_background():
        await asyncio.Event().wait()

    monkeypatch.setattr(community, "run_sync_loop", no_background)
    yield
    with db.session() as c:
        for table in ("community_feedback", "community_issues", "community_webhooks"):
            c.execute(f"DELETE FROM {table}")


def idea(**updates):
    return {"kind": "idea", "title": "Copy a shopping list", "description": "Please let me copy my required command centers.",
            "steps": "", "expected": "", "actual": "", **updates}


def issue(number=1, body="", **updates):
    return {"number": number, "title": "Copy a shopping list", "body": body,
            "state": "open", "state_reason": None, "labels": [{"name": "type:idea"}],
            "updated_at": "2026-10-11T12:00:00Z", "created_at": "2026-10-11T12:00:00Z", **updates}


def create_saved(pid=None):
    pid = pid or db.create_profile("Private identity")
    fid = community.save_feedback(pid, idea(), secrets.token_hex(16), "1.1.0")
    return pid, fid


def load_saved(fid):
    with db.session() as c:
        return dict(c.execute("SELECT * FROM community_feedback WHERE id=?", (fid,)).fetchone())


def allow_github(monkeypatch):
    monkeypatch.setitem(config._ENV, "ASTRACORE_GITHUB_TOKEN", "mock-token-not-a-real-secret")


def test_public_roadmap_and_login_required_for_submit(browser):
    client = browser()
    response = client.get("/roadmap")
    assert response.status_code == 200
    assert "real market demand" in response.text
    assert "proposed directions" in response.text
    assert client.get("/feedback").status_code == 200
    assert "invitation" in client.get("/feedback").text
    # App-wide CSRF rejects anonymous mutation before route authentication.
    assert client.post("/feedback", data=idea()).status_code in (401, 403)
    assert client.get("/community/admin", follow_redirects=False).status_code in (303, 401)


def test_preview_confirmation_and_duplicate_click_are_bound_to_content(browser, eve):
    client = browser()
    sso_login(client, eve, new_id(), "Secret capsuleer name")
    token = csrf(client)
    form = {**idea(), "csrf_token": token}
    response = client.post("/feedback/preview", data=form)
    assert response.status_code == 200
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', response.text))
    # These values have no entities in this test; use the real request contents.
    submission = {**hidden, **idea(), "csrf_token": token, "public_confirm": "yes"}
    tampered = client.post("/feedback", data={**submission, "title": "A changed public title"}, follow_redirects=False)
    assert tampered.status_code == 400
    refused = client.post("/feedback", data={**submission, "public_confirm": ""}, follow_redirects=False)
    assert refused.status_code == 400
    first = client.post("/feedback", data=submission, follow_redirects=False)
    second = client.post("/feedback", data=submission, follow_redirects=False)
    assert first.status_code == second.status_code == 303
    assert first.headers["location"] == second.headers["location"]
    saved = community.feedback_for(me(client))
    assert len(saved) == 1
    assert "Secret capsuleer name" not in saved[0]["body"]
    assert saved[0]["delivery"] == "queued"
    assert not community.public_issues()
    assert "Saved and waiting" in client.get(first.headers["location"]).text


def test_report_ownership_and_admin_access(browser, eve):
    first, second, admin = browser(), browser(), browser()
    sso_login(first, eve, new_id(), "Reporter")
    sso_login(second, eve, new_id(), "Other user")
    sso_login(admin, eve, 90000001, "Admin")
    _, fid = create_saved(me(first))
    path = f"/community/reports/{fid}"
    assert first.get(path).status_code == 200
    assert second.get(path).status_code == 404
    assert admin.get(path).status_code == 200
    assert second.get("/community/admin").status_code == 403


def test_withdrawal_does_not_overwrite_a_concurrent_delivery_claim(browser, eve, monkeypatch):
    client = browser()
    sso_login(client, eve, new_id(), "Reporter")
    _, fid = create_saved(me(client))
    token = csrf(client)
    original_session = db.session

    class Snapshot:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class ConcurrentClaim:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, query, args=()):
            if query.startswith("SELECT profile_id,delivery FROM community_feedback"):
                row = self.conn.execute(query, args).fetchone()
                self.conn.execute("UPDATE community_feedback SET delivery='processing' WHERE id=?", (fid,))
                return Snapshot(row)
            return self.conn.execute(query, args)

    @contextmanager
    def claimed_session():
        with original_session() as conn:
            yield ConcurrentClaim(conn)

    monkeypatch.setattr(db, "session", claimed_session)
    response = client.post(f"/community/reports/{fid}/withdraw", data={"csrf_token": token}, follow_redirects=False)
    message = parse_qs(urlparse(response.headers["location"]).query)["msg"][0]
    assert "delivery is being checked" in message
    assert load_saved(fid)["delivery"] == "processing"


@pytest.mark.parametrize("concurrent_state", ["processing", "ambiguous", "published"])
def test_admin_retry_does_not_overwrite_concurrent_delivery(browser, eve, monkeypatch, concurrent_state):
    client = browser()
    sso_login(client, eve, 90000001, "Admin")
    _, fid = create_saved(me(client))
    token = csrf(client)
    original_session = db.session

    class Snapshot:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class ConcurrentDelivery:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, query, args=()):
            if query.startswith("SELECT * FROM community_feedback WHERE id=?"):
                row = self.conn.execute(query, args).fetchone()
                self.conn.execute("UPDATE community_feedback SET delivery=? WHERE id=?", (concurrent_state, fid))
                return Snapshot(row)
            return self.conn.execute(query, args)

    @contextmanager
    def changed_session():
        with original_session() as conn:
            yield ConcurrentDelivery(conn)

    monkeypatch.setattr(db, "session", changed_session)
    response = client.post(f"/community/admin/{fid}/retry", data={"csrf_token": token}, follow_redirects=False)
    message = parse_qs(urlparse(response.headers["location"]).query)["msg"][0]
    assert "Delivery changed" in message
    with original_session() as conn:
        assert conn.execute("SELECT delivery FROM community_feedback WHERE id=?", (fid,)).fetchone()[0] == concurrent_state


def test_bug_fields_and_profile_rate_limit():
    with pytest.raises(ValueError, match="steps to reproduce"):
        community.validate_fields(idea(kind="bug"))
    with pytest.raises(ValueError, match="6,000"):
        community.validate_fields(idea(description="x" * 6001))
    with pytest.raises(ValueError, match="tracking markers"):
        community.validate_fields(idea(description="A useful idea <!-- astracore-roadmap:practical-upkeep -->"))
    pid = db.create_profile("Rate limit")
    for _ in range(5):
        create_saved(pid)
    with pytest.raises(ValueError, match="five reports"):
        create_saved(pid)
    db.delete_profile(pid)
    assert not community.feedback_for(pid)


def test_github_failure_keeps_private_report_and_retries_without_exposing_text(monkeypatch):
    allow_github(monkeypatch)
    _, fid = create_saved()

    def api(request):
        assert request.method == "GET"
        return httpx.Response(403, json={"message": "private API detail"})

    asyncio.run(community.sync_once(transport=httpx.MockTransport(api)))
    saved = load_saved(fid)
    assert saved["delivery"] == "queued" and saved["next_attempt_at"] > time.time()
    assert "private API detail" not in saved["problem"]
    assert not community.public_issues()


def test_timeout_create_is_reconciled_and_not_posted_twice(monkeypatch):
    allow_github(monkeypatch)
    _, fid = create_saved()
    remote = []
    posts = []

    def api(request):
        if request.method == "GET":
            return httpx.Response(200, json=remote)
        payload = json.loads(request.content)
        posts.append(payload)
        remote.append(issue(17, payload["body"]))
        raise httpx.ReadTimeout("lost confirmation", request=request)

    transport = httpx.MockTransport(api)
    asyncio.run(community.sync_once(transport=transport))
    # Polling may find the accepted issue immediately after the timeout.
    assert load_saved(fid)["delivery"] in ("ambiguous", "published")
    with db.session() as c:
        c.execute("UPDATE community_feedback SET next_attempt_at=0 WHERE id=?", (fid,))
    asyncio.run(community.sync_once(transport=transport))
    assert len(posts) == 1
    assert load_saved(fid)["delivery"] == "published"
    assert load_saved(fid)["issue_number"] == 17
    assert "Private identity" not in posts[0]["body"]
    assert posts[0]["labels"] == ["type:idea", "status:under-review", "source:platform"]


def test_unconfirmed_create_without_matching_issue_never_auto_creates_again(monkeypatch):
    allow_github(monkeypatch)
    _, fid = create_saved()
    calls = []

    def api(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        raise httpx.ReadTimeout("unknown acceptance", request=request)

    transport = httpx.MockTransport(api)
    asyncio.run(community.sync_once(transport=transport))
    assert load_saved(fid)["delivery"] == "ambiguous"
    with db.session() as c:
        c.execute("UPDATE community_feedback SET next_attempt_at=0 WHERE id=?", (fid,))
    asyncio.run(community.sync_once(transport=transport))
    assert calls.count("POST") == 1
    assert load_saved(fid)["delivery"] == "ambiguous"


def test_crash_lease_reconciles_before_retry_and_withdrawn_reports_stay_private(monkeypatch):
    allow_github(monkeypatch)
    pid, fid = create_saved()
    _, withdrawn = create_saved(pid)
    with db.session() as c:
        c.execute("UPDATE community_feedback SET delivery='processing',lease_until=1 WHERE id=?", (fid,))
        c.execute("UPDATE community_feedback SET delivery='withdrawn' WHERE id=?", (withdrawn,))

    def api(request):
        assert request.method == "GET"
        return httpx.Response(200, json=[issue(20, community.marker(fid))])

    asyncio.run(community.sync_once(transport=httpx.MockTransport(api)))
    assert load_saved(fid)["delivery"] == "published"
    assert load_saved(withdrawn)["delivery"] == "withdrawn"


def test_polled_status_excludes_pull_requests_and_keeps_last_confirmed_on_failure(monkeypatch):
    allow_github(monkeypatch)
    responses = [issue(31, "<!-- astracore-roadmap:practical-upkeep -->", labels=[{"name": "roadmap"}, {"name": "status:in-progress"}]),
                 issue(32, pull_request={"url": "https://github.com/example"})]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=responses))
    asyncio.run(community.sync_once(force=True, transport=transport))
    assert len(community.public_issues()) == 1
    assert community.public_issues()[0]["status"] == "In progress"
    community.cache_issue(issue(31, state="closed", state_reason="completed", updated_at="2026-10-12T00:00:00Z"))
    community.cache_issue(responses[0])  # Old delivery must not overwrite a newer state.
    assert community.public_issues()[0]["status"] == "Completed"
    failing = httpx.MockTransport(lambda request: httpx.Response(503))
    asyncio.run(community.sync_once(force=True, transport=failing))
    assert community.public_issues()[0]["status"] == "Completed"
    assert community.sync_state()["problem"]


def webhook_payload(event_issue, action="edited", repo="gwnmikedus/AstraCore"):
    return json.dumps({"repository": {"full_name": repo}, "action": action, "issue": event_issue}).encode()


def signed_headers(body, delivery="unique-delivery", secret="test-webhook-secret"):
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
            "X-GitHub-Delivery": delivery, "X-GitHub-Event": "issues", "Content-Type": "application/json"}


def test_webhook_signature_repo_and_delivery_dedup(browser, monkeypatch):
    monkeypatch.setitem(config._ENV, "ASTRACORE_GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
    client = browser()
    path = "/api/community/github/webhook"
    body = webhook_payload(issue(42))
    assert client.post(path, content=body, headers=signed_headers(body, secret="wrong")).status_code == 403
    assert not community.public_issues()
    wrong_repo = webhook_payload(issue(42), repo="elsewhere/private")
    assert client.post(path, content=wrong_repo, headers=signed_headers(wrong_repo)).status_code == 403
    response = client.post(path, content=body, headers=signed_headers(body))
    assert response.status_code == 200
    changed = webhook_payload(issue(42, state="closed", state_reason="completed", updated_at="2026-10-12T00:00:00Z"))
    repeated = client.post(path, content=changed, headers=signed_headers(changed))
    assert repeated.json()["duplicate"] is True
    assert community.public_issues()[0]["status"] == "Under review"
    assert client.post(path, content=changed, headers=signed_headers(changed, delivery="next-delivery")).status_code == 200
    assert community.public_issues()[0]["status"] == "Completed"


def test_signed_github_app_ping_does_not_require_repository(browser, monkeypatch):
    monkeypatch.setitem(config._ENV, "ASTRACORE_GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
    client = browser()
    body = json.dumps({"zen": "Keep it logically awesome", "hook_id": 17}).encode()
    headers = {**signed_headers(body, delivery="app-ping"), "X-GitHub-Event": "ping"}
    response = client.post("/api/community/github/webhook", content=body, headers=headers)
    assert response.status_code == 200 and response.json()["ping"] is True
    headers["X-Hub-Signature-256"] = "sha256=incorrect"
    assert client.post("/api/community/github/webhook", content=body, headers=headers).status_code == 403
    assert not community.public_issues()


def test_merging_profiles_keeps_feedback_ownership():
    from astracore.core import accounts
    src, fid = create_saved()
    dst = db.create_profile("Destination")
    accounts.merge_profiles(src, dst)
    assert load_saved(fid)["profile_id"] == dst
    assert not community.feedback_for(src)
    assert community.feedback_for(dst)[0]["id"] == fid
    db.delete_profile(dst)


def test_html_report_content_is_escaped(browser, eve):
    client = browser()
    sso_login(client, eve, new_id(), "Reporter")
    response = client.post("/feedback/preview", data={**idea(description="<script>alert('private')</script> and a useful suggestion"), "csrf_token": csrf(client)})
    assert response.status_code == 200
    assert "&lt;script&gt;" in response.text
    assert "<script>alert('private')</script>" not in response.text
