"""Contributor snapshots stay complete, public, and available during GitHub failures."""
import asyncio
import time

import httpx
import pytest

from astracore import db
from astracore.core import contributors
from test_core import browser  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_credits():
    with db.session() as c:
        c.execute("DELETE FROM kv WHERE key=?", (contributors.CACHE_KEY,))
    yield
    with db.session() as c:
        c.execute("DELETE FROM kv WHERE key=?", (contributors.CACHE_KEY,))


def person(login="Capsuleer", user_id=123, **updates):
    return {"login": login, "id": user_id, "type": "User", **updates}


def sync(handler, **options):
    asyncio.run(contributors.sync_once(transport=httpx.MockTransport(handler), **options))


def test_paginated_snapshot_is_sorted_and_uses_only_public_identities():
    calls = []

    def github(request):
        calls.append(request)
        assert request.url.path == "/repos/gwnmikedus/AstraCore/contributors"
        assert "authorization" not in request.headers
        assert request.url.params["per_page"] == "100"
        if request.url.params["page"] == "1":
            return httpx.Response(200, json=[person("Zulu", 1)] * 98 + [
                person("worker[bot]", 2, type="Bot"),
                {"type": "Anonymous", "name": "Private name", "email": "private@example.org"},
            ])
        return httpx.Response(200, json=[person("Alpha", 3, html_url="javascript:alert(1)",
                                               avatar_url="https://untrusted.example/avatar")])

    sync(github)
    saved = contributors.snapshot()
    assert len(calls) == 2
    assert [p["login"] for p in saved["people"]] == ["Alpha", "Zulu"]
    assert saved["people"][0]["url"] == "https://github.com/Alpha"
    assert saved["people"][0]["avatar_url"] == "https://avatars.githubusercontent.com/u/3?s=128"
    assert "Private name" not in str(saved)
    assert "private@example.org" not in str(saved)
    assert saved["last_success"] > 0
    assert saved["unavailable"] is False


def test_refresh_interval_and_restart_cache_do_not_call_github_again():
    sync(lambda request: httpx.Response(200, json=[person()]))
    saved = contributors.snapshot()

    def unexpected(request):
        pytest.fail("A fresh persistent snapshot must not refetch")

    sync(unexpected)
    assert db.kv_get(contributors.CACHE_KEY) == saved


@pytest.mark.parametrize("failure", [403, 429, 503, "timeout", "malformed", "identity", "pending"])
def test_failed_refresh_preserves_last_confirmed_snapshot(failure):
    sync(lambda request: httpx.Response(200, json=[person("Original")]))
    saved = contributors.snapshot()

    def github(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("offline", request=request)
        if failure == "malformed":
            return httpx.Response(200, json={"unexpected": True})
        if failure == "identity":
            return httpx.Response(200, json=[person("../unsafe")])
        if failure == "pending":
            return httpx.Response(202)
        return httpx.Response(failure)

    sync(github, force=True)
    updated = contributors.snapshot()
    assert updated["people"] == saved["people"]
    assert updated["last_success"] == saved["last_success"]
    assert updated["unavailable"] is True
    assert updated["next_poll_at"] > time.time()


def test_failure_on_second_page_never_publishes_partial_or_deletes_existing_credits():
    sync(lambda request: httpx.Response(200, json=[person("Original")]))

    def github(request):
        if request.url.params["page"] == "1":
            return httpx.Response(200, json=[person("Replacement")] * 100)
        return httpx.Response(503)

    sync(github, force=True)
    assert [p["login"] for p in contributors.snapshot()["people"]] == ["Original"]


@pytest.mark.parametrize("status", [200, 204])
def test_confirmed_empty_repository_can_replace_previous_credits(status):
    sync(lambda request: httpx.Response(200, json=[person()]))
    sync(lambda request: httpx.Response(status, json=[] if status == 200 else None), force=True)
    assert contributors.snapshot()["people"] == []
    assert contributors.snapshot()["last_success"] > 0
    assert contributors.snapshot()["unavailable"] is False


def test_public_pages_show_contributors_before_origin_story_without_network_reads(browser, monkeypatch):
    sync(lambda request: httpx.Response(200, json=[person("FellowPilot")]))

    async def unexpected(*args, **kwargs):
        pytest.fail("Rendering public credits must not call GitHub")

    monkeypatch.setattr(httpx.AsyncClient, "get", unexpected)
    client = browser()
    for path in ("/", "/about", "/credits"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.text.index('id="contributors"') < response.text.index('id="creator"')
        assert 'href="https://github.com/FellowPilot"' in response.text
        assert "Founding capsuleer" in response.text
        assert "CosmicCarrot" in response.text
        assert "testing, and ideas" in response.text
        assert "Built by CosmicCarrot" not in response.text
        assert 'href="/credits#contributors"' in response.text
        assert "https://avatars.githubusercontent.com" in response.headers["content-security-policy"]
        if path in ("/", "/about"):
            assert response.text.index("Contribute to AstraCore") < response.text.index('id="contributors"')
            assert "Help shape AstraCore" in response.text


def test_first_sync_failure_and_stale_cache_offer_working_github_fallback(browser):
    sync(lambda request: httpx.Response(503))
    client = browser()
    response = client.get("/credits")
    assert response.status_code == 200
    assert "Meet the contributors on GitHub" in response.text
    assert 'href="https://github.com/gwnmikedus/AstraCore/graphs/contributors"' in response.text
    sync(lambda request: httpx.Response(200, json=[person("StillCredited")]), force=True)
    sync(lambda request: httpx.Response(429), force=True)
    response = client.get("/credits")
    assert "StillCredited" in response.text
    assert "Showing the last confirmed contributor list" in response.text
