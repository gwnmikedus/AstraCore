"""In-context quick feedback (#301): private notes, their context, CSRF, the admin list and promotion. No network."""
from __future__ import annotations

import asyncio
import json
import re
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from astracore import db
from astracore.core import accounts, community
from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401

ADMIN = 90000001


@pytest.fixture(autouse=True)
def clean_notes():
    def clean():
        with db.session() as c:
            c.execute("DELETE FROM community_notes")
    clean()
    yield
    clean()


def pilot(browser, eve, name="Quick Noter"):
    client = browser()
    cid = new_id()
    sso_login(client, eve, cid, name)
    return client, cid


def admin(browser, eve):
    client = browser()
    sso_login(client, eve, ADMIN, "Admin")
    return client


def note(client, kind="confusing", body="The buying step confuses me.", context=None, token=None):
    return client.post("/community/notes", json={"kind": kind, "body": body, "context": context or {}},
                       headers={"X-CSRF-Token": token or csrf(client)})


def rows():
    with db.session() as c:
        return [dict(r) for r in c.execute("SELECT * FROM community_notes ORDER BY created_at")]


def test_migration_adds_only_the_notes_table():
    assert db.MIGRATIONS[10].__name__ == "_migrate_v11"
    with db.session() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
        assert db.migrate(c) == len(db.MIGRATIONS)   # idempotent
    assert {"community_notes", "community_notes_state", "community_notes_profile"} <= names


def test_panel_on_signed_in_pages_only(browser, eve):
    anonymous = browser()
    assert "data-qf-panel" not in anonymous.get("/community").text
    client, _ = pilot(browser, eve)
    page = client.get("/community").text
    assert "data-qf-panel" in page and "quick-feedback.js" in page and "quick-feedback.css" in page
    assert 'href="/feedback">More detail? Use the full form' in page
    assert '<input type="hidden" name="path" value="/community">' in page
    assert "Never your character names, wallet or locations" in page
    # The full form keeps working and doesn't stack a second form on top of itself.
    full = client.get("/feedback").text
    assert "data-feedback-form" in full and "data-qf-panel" not in full


def test_note_is_private_and_keeps_only_cleaned_context(browser, eve):
    client, cid = pilot(browser, eve, "Secret Capsuleer")
    with db.session() as c:
        c.execute("UPDATE characters SET corporation_name='Hidden Holdings', alliance_name='Quiet Alliance' "
                  "WHERE character_id=?", (cid,))
    context = {"path": f"/pi/plans/{cid}/edit?char={cid}&wallet=123#x", "step": "Step 3 · Buying",
               "viewport": "1280x720", "theme": "light", "wallet": "9.9B ISK", "character_id": cid,
               "location": "Jita IV - Moon 4", "version": "spoofed",
               "target": {"selector": "section#q > div.options > button:nth-of-type(2)",
                          "label": "Secret Capsuleer pays 1,250,000 ISK", "extra": "x"}}
    r = note(client, body="secret capsuleer and Hidden Holdings can't find the buy list", context=context)
    assert r.status_code == 200 and r.json()["ok"]
    [saved] = rows()
    stored = json.dumps(saved)
    for private in ("Secret Capsuleer", "secret capsuleer", "Hidden Holdings", "Quiet Alliance", str(cid), "9.9B",
                    "Jita", "1,250,000", "spoofed", "wallet"):
        assert private not in stored, private
    ctx = json.loads(saved["context_json"])
    assert ctx == {"path": "/pi/plans/:n/edit", "step": "Step # · Buying", "viewport": "1280x720", "theme": "light",
                   "version": community.current_version(),
                   "target": {"selector": "section#q > div.options > button:nth-of-type(2)",
                              "label": "[name] pays #,###,### ISK"}}
    assert saved["body"] == "[name] and [name] can't find the buy list"
    # Never queued for GitHub.
    with db.session() as c:
        assert c.execute("SELECT COUNT(*) FROM community_feedback WHERE profile_id=?", (me(client),)).fetchone()[0] == 0


def test_unsafe_selectors_and_paths_are_dropped():
    ctx = community.clean_context({"path": "https://evil.example/x", "viewport": "huge", "theme": "neon",
                                   "target": {"selector": "a[href='javascript:x']", "label": "x"}}, "1.0")
    assert ctx == {"version": "1.0"}
    assert community.clean_context("not a dict", "1.0") == {"version": "1.0"}


def test_notes_never_reach_github(browser, eve, monkeypatch):
    client, _ = pilot(browser, eve)
    assert note(client).status_code == 200
    monkeypatch.setenv("ASTRACORE_GITHUB_TOKEN", "test-token")
    sent = []

    def handler(request):
        sent.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json=[])

    asyncio.run(community.sync_once(force=True, transport=httpx.MockTransport(handler)))
    assert sent and all(method == "GET" for method, _, _ in sent)
    assert not any(b"buying step" in body for _, _, body in sent)


def test_notes_need_a_signed_in_pilot_and_csrf(browser, eve):
    anonymous = browser()
    r = anonymous.post("/community/notes", json={"kind": "idea", "body": "hello there"})
    assert r.status_code == 403   # no session, so no CSRF token either
    client, _ = pilot(browser, eve)
    assert client.post("/community/notes", json={"kind": "idea", "body": "hello there"}).status_code == 403
    assert note(client, token="forged-token").status_code == 403
    form = client.post("/community/notes", data={"kind": "idea", "body": "hello there", "csrf_token": "forged"})
    assert form.status_code == 403
    assert rows() == []


def test_validation_and_hourly_limit(browser, eve):
    client, _ = pilot(browser, eve)
    token = csrf(client)
    assert note(client, kind="praise", token=token).json()["error"] == "Choose confusing, idea or bug."
    assert note(client, body=" a ", token=token).status_code == 400
    assert note(client, body="x" * 2001, token=token).status_code == 400
    assert note(client, kind="clear", body="", token=token).json()["error"] == "This page can't take a rating."
    bad = client.post("/community/notes", content="[]", headers={"X-CSRF-Token": token, "Content-Type": "application/json"})
    assert bad.status_code == 400
    for _ in range(community.NOTES_PER_HOUR):
        assert note(client, token=token).status_code == 200
    assert "this hour" in note(client, token=token).json()["error"]


def test_form_post_without_javascript_returns_to_the_page(browser, eve):
    client, _ = pilot(browser, eve)
    token = csrf(client)
    r = client.post("/community/notes", data={"kind": "bug", "body": "Button does nothing", "path": "/pi/plan",
                                              "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pi/plan?msg=")
    assert json.loads(rows()[0]["context_json"])["path"] == "/pi/plan"
    r = client.post("/community/notes", data={"kind": "bug", "body": "x", "path": "//evil.example/",
                                              "csrf_token": token}, follow_redirects=False)
    assert r.headers["location"].startswith("/?msg=") and "kind=warn" in r.headers["location"]


def test_ratings_replace_a_quick_change_of_mind_and_are_tallied(browser, eve):
    client, _ = pilot(browser, eve)
    token = csrf(client)
    assert note(client, kind="clear", body="", context={"surface": "plan-result"}, token=token).status_code == 200
    assert note(client, kind="unclear", body="", context={"surface": "plan-result"}, token=token).status_code == 200
    assert note(client, kind="clear", body="", context={"surface": "operate"}, token=token).status_code == 200
    assert [r["kind"] for r in rows()] == ["unclear", "clear"]
    tally = {t["surface"]: t for t in community.rating_tally()}
    assert (tally["plan-result"]["up"], tally["plan-result"]["down"]) == (0, 1)
    assert tally["operate"]["up"] == 1
    assert community.quick_notes() == []   # ratings without words don't fill the notes list


def test_admin_reads_and_archives_notes_without_identity(browser, eve):
    client, cid = pilot(browser, eve, "Anonymous Reporter")
    note(client, body="Where do I see pickups?", context={"path": "/pi/operate", "step": "Selling"})
    note_id = rows()[0]["id"]
    assert client.get("/community/admin").status_code == 403
    token = csrf(client)
    assert client.post(f"/community/admin/notes/{note_id}/state", data={"state": "archived", "csrf_token": token},
                       follow_redirects=False).status_code == 403
    boss = admin(browser, eve)
    page = boss.get("/community/admin").text
    assert "Quick notes" in page and "Where do I see pickups?" in page and "/pi/operate" in page
    assert "Anonymous Reporter" not in page and str(cid) not in page
    assert "Operate</strong>, was it clear? 👍 0 · 👎 0" in page
    assert f'href="/feedback?note={note_id}">Promote to issue' in page
    boss_token = csrf(boss)
    assert boss.post(f"/community/admin/notes/{note_id}/state", data={"state": "archived"}).status_code == 403
    r = boss.post(f"/community/admin/notes/{note_id}/state", data={"state": "archived", "csrf_token": boss_token},
                  follow_redirects=False)
    assert r.status_code == 303 and rows()[0]["state"] == "archived"
    assert "Where do I see pickups?" not in boss.get("/community/admin").text
    assert "Where do I see pickups?" in boss.get("/community/admin?notes=archived").text
    assert boss.post("/community/admin/notes/nope/state", data={"csrf_token": boss_token}).status_code == 404


def test_promote_prefills_the_consent_flow_with_the_text_only(browser, eve):
    client, _ = pilot(browser, eve)
    body = "The Selling step doesn't say which hub is cheapest.\nMaybe show the courier fee next to it."
    note(client, kind="idea", body=body, context={"path": "/pi/plan", "step": "Selling"})
    note_id = rows()[0]["id"]
    # A pilot can't open someone's note through the form.
    assert "doesn't say which hub" not in client.get(f"/feedback?note={note_id}").text
    boss = admin(browser, eve)
    form = boss.get(f"/feedback?note={note_id}").text
    assert "You're promoting a private quick note" in form
    assert f'name="note_id" value="{note_id}"' in form
    assert "The Selling step doesn&#39;t say which hub is cheapest." in form
    token = csrf(boss)
    fields = {"kind": "idea", "title": "Show the cheapest selling hub", "csrf_token": token, "note_id": note_id,
              "description": "The Selling step could show which hub is cheapest, with the courier fee.",
              "steps": "", "expected": "", "actual": ""}
    preview = boss.post("/feedback/preview", data=fields)
    assert preview.status_code == 200 and f'name="note_id" value="{note_id}"' in preview.text
    assert "/pi/plan" not in re.search(r'<pre class="community-public-body">(.*?)</pre>', preview.text, re.S).group(1)
    hidden = dict(re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)"', preview.text))
    hidden.update(public_confirm="yes")
    r = boss.post("/feedback", data=hidden, follow_redirects=False)
    assert r.status_code == 303
    feedback_id = r.headers["location"].split("/")[-1].split("?")[0]
    saved = rows()[0]
    assert (saved["state"], saved["feedback_id"]) == ("promoted", feedback_id)
    with db.session() as c:
        report = c.execute("SELECT * FROM community_feedback WHERE id=?", (feedback_id,)).fetchone()
    assert report["profile_id"] == me(boss) and "/pi/plan" not in report["body"]
    # Archive no longer applies to a promoted note.
    assert boss.post(f"/community/admin/notes/{note_id}/state", data={"state": "archived", "csrf_token": token}
                     ).status_code == 404


def test_a_pilot_cannot_promote_through_a_forged_note_id(browser, eve):
    client, _ = pilot(browser, eve)
    note(client)
    note_id = rows()[0]["id"]
    assert community._promotable({"id": 1, "is_admin": False}, note_id) is None
    assert community._promotable({"id": 1, "is_admin": True}, note_id)["id"] == note_id
    assert community._promotable({"id": 1, "is_admin": True}, "") is None


def test_export_merge_and_reset_cover_notes(browser, eve):
    client, _ = pilot(browser, eve)
    note(client)
    pid = me(client)
    exported = accounts.export_profile(pid)["quick_notes"]
    assert [n["body"] for n in exported] == ["The buying step confuses me."]
    db.delete_profile(pid)
    assert rows() == []


def test_rating_hook_on_the_guide(browser, eve, monkeypatch):
    from astracore.modules.pi import service
    from astracore.modules.pi.settings import Settings

    client, _ = pilot(browser, eve)

    async def context(pid, **kw):
        return {"s": Settings(), "chars": [{"character_id": 1, "name": "Ready", "slots": 6, "ccu_level": 5}],
                "systems": {}, "area": {}, "calibrated": False, "head_yield": 1500, "dropoff": None, "seller": None}

    monkeypatch.setattr(service, "planning_context", context)
    page = client.get("/pi/plan").text
    assert 'data-qf-rate="plan-result" data-qf-rate-when="result"' in page and "Was this plan clear?" in page
    assert "data-qf-rate=" not in client.get("/community").text


def test_time_window_for_rating_replacement(browser, eve):
    client, _ = pilot(browser, eve)
    note(client, kind="clear", body="", context={"surface": "operate"})
    with db.session() as c:
        c.execute("UPDATE community_notes SET created_at=?", (time.time() - 3600,))
    note(client, kind="clear", body="", context={"surface": "operate"})
    assert len(rows()) == 2   # a later visit counts again


def test_note_thanks_redirect_is_signed(browser, eve):
    client, _ = pilot(browser, eve)
    r = client.post("/community/notes", data={"kind": "idea", "body": "More colours", "path": "/community",
                                              "csrf_token": csrf(client)}, follow_redirects=False)
    query = parse_qs(urlparse(r.headers["location"]).query)
    assert query["msg"] == [community.NOTE_THANKS] and query["kind"] == ["ok"]
