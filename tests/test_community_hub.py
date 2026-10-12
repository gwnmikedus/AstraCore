"""Community hub (#106, #107, #108): report stages, "this would help me", opt-in credit. No network."""
from __future__ import annotations

import re
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from astracore import db
from astracore.core import community, releases
from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401

TABLES = ("community_votes", "community_credit", "community_report_seen", "community_feedback", "community_issues")


@pytest.fixture(autouse=True)
def clean_community():
    def clean():
        with db.session() as c:
            for table in TABLES:
                c.execute(f"DELETE FROM {table}")
    clean()
    yield
    clean()


def idea(**updates):
    return {"kind": "idea", "title": "Copy a shopping list", "description": "Please let me copy my required command centers.",
            "steps": "", "expected": "", "actual": "", **updates}


def publish(pid, number, *labels, **updates):
    """A saved report that GitHub confirmed as issue `number`, with the given labels/state."""
    fid = community.save_feedback(pid, idea(), secrets.token_hex(16), "0.2.0")
    community.cache_issue({"number": number, "title": f"Test idea {number}", "body": "text\n\n" + community.marker(fid),
                           "state": "open", "state_reason": None, "labels": [{"name": n} for n in ("type:idea",) + labels],
                           "updated_at": "2026-10-12T00:00:00Z", **updates})
    return fid


def restage(number, *labels, **updates):
    with db.session() as c:
        body = c.execute("SELECT body FROM community_issues WHERE number=?", (number,)).fetchone()["body"]
    community.cache_issue({"number": number, "title": f"Test idea {number}", "body": body, "state": "open",
                           "state_reason": None, "labels": [{"name": n} for n in ("type:idea",) + labels],
                           "updated_at": "2026-10-13T00:00:00Z", **updates})


def flash(response):
    return parse_qs(urlparse(response.headers["location"]).query)["msg"][0]


def test_migration_adds_only_new_tables():
    assert len(db.MIGRATIONS) == 8 and db.MIGRATIONS[-1].__name__ == "_migrate_v8"
    with db.session() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"community_votes", "community_credit", "community_report_seen"} <= names


def test_report_stage_words_follow_the_roadmap():
    def stage(labels=(), **issue):
        return community.issue_stage({"state": "open", "state_reason": None, "labels": list(labels), **issue})

    assert stage() == "review"
    assert stage(["status:planned"]) == stage(["roadmap"]) == "planned"
    assert stage(["status:in-progress"]) == "building"
    assert stage(state="closed", state_reason="completed") == "soon"
    assert stage(["status:released"], state="closed", state_reason="completed") == "live"
    assert stage(state="closed", state_reason="not_planned") == "declined"
    assert community.STAGES["declined"] == "Not planned for now"


def test_your_reports_show_stage_moved_notice_and_live_banner(browser, eve):
    client = browser()
    sso_login(client, eve, new_id(), "Reporter")
    pid = me(client)
    planned = publish(pid, 501, "status:planned")
    publish(pid, 502)
    page = client.get("/community").text
    assert "1 of your reports moved" in page and "1 of your reports moved" in page.split("</header>", 1)[0]
    assert '<span class="pill stage stage-planned">Planned</span>' in page
    assert '<span class="pill stage stage-review">Under review</span>' in page
    # Seen on this visit: the notice goes away until the next change.
    page = client.get("/community").text
    assert "of your reports moved" not in page
    restage(501, "status:released", state="closed", state_reason="completed")
    page = client.get("/community").text
    assert "1 of your reports moved" in page
    assert "is live" in page and f"/community/reports/{planned}" in page
    restage(501, state="closed", state_reason="not_planned")
    page = client.get(f"/community/reports/{planned}").text
    assert "Not planned for now" in page and "Read the reply" in page
    assert "of your reports moved" not in client.get("/about").text


def test_submit_thanks_preview_copy_and_opt_in_credit(browser, eve):
    client = browser()
    cid = new_id()
    sso_login(client, eve, cid, "Credit Pilot")
    token = csrf(client)
    preview = client.post("/feedback/preview", data={**idea(), "csrf_token": token}).text
    assert "Only you and the maintainer see who sent this." in preview
    assert ">Queue report</button>" in preview and "Confirm & submit" not in preview
    assert '<option value="" selected>Keep me anonymous</option>' in preview
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', preview))
    form = {**hidden, **idea(), "csrf_token": token, "public_confirm": "yes"}
    anonymous = client.post("/feedback", data=form, follow_redirects=False)
    assert flash(anonymous).startswith("Thanks, pilot. Your report is in.")
    with db.session() as c:
        assert c.execute("SELECT COUNT(*) FROM community_credit").fetchone()[0] == 0   # off by default

    second = client.post("/feedback/preview", data={**idea(title="Another useful idea"), "csrf_token": token}).text
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', second))
    stranger = new_id()
    db.link_character(stranger, db.create_profile("Someone else"), "Not Mine")
    refused = client.post("/feedback", data={**hidden, **idea(title="Another useful idea"), "csrf_token": token,
                                             "public_confirm": "yes", "credit_character": str(stranger)},
                          follow_redirects=False)
    fid = refused.headers["location"].split("/")[-1].split("?")[0]
    with db.session() as c:
        assert c.execute("SELECT COUNT(*) FROM community_credit").fetchone()[0] == 0   # never someone else's name
    response = client.post(f"/community/reports/{fid}/credit", data={"csrf_token": token, "credit_character": str(cid)},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "Reported by Credit Pilot" in client.get(f"/community/reports/{fid}").text
    client.post(f"/community/reports/{fid}/credit", data={"csrf_token": token, "credit_character": ""})
    assert "This report is anonymous." in client.get(f"/community/reports/{fid}").text


def test_credit_shows_on_credits_and_releases_only_when_opted_in_and_accepted(browser, eve, monkeypatch):
    client = browser()
    cid = new_id()
    sso_login(client, eve, cid, "Shaping Pilot")
    pid = me(client)
    credited = publish(pid, 601)
    publish(pid, 602, "status:planned")   # accepted, but no consent
    assert community.set_credit(pid, credited, cid)
    assert "Shaping Pilot" not in browser().get("/credits").text     # still under review
    restage(601, "status:in-progress")
    assert community.credited_pilots() == ["Shaping Pilot"]
    assert "Shaping Pilot" in browser().get("/credits").text
    assert "Shaping Pilot" in browser().get("/community").text
    release = {"references": [{"label": "Copy", "url": "https://github.com/gwnmikedus/AstraCore/issues/601"},
                              {"label": "Other", "url": "https://github.com/gwnmikedus/AstraCore/issues/602"},
                              {"label": "PRs", "url": "https://github.com/gwnmikedus/AstraCore/pulls"}]}
    assert community.release_issue_numbers(release) == [601, 602]
    assert [(c["number"], c["names"]) for c in community.release_credits(release)] == [(601, ["Shaping Pilot"])]
    entry = {**releases.history()[0], **release}
    monkeypatch.setattr(releases, "history", lambda: [entry])
    page = browser().get("/releases").text
    assert "reported by <strong>Shaping Pilot</strong>" in page
    restage(601, "status:in-progress", "platform:hidden")
    assert community.credited_pilots() == [] and community.release_credits(release) == []
    db.delete_character(cid)   # leaving the profile ends the credit
    restage(601, "status:in-progress")
    assert community.credited_pilots() == []


def test_this_would_help_me_is_one_toggled_mark_per_pilot(browser, eve):
    first, second, anonymous = browser(), browser(), browser()
    sso_login(first, eve, new_id(), "First")
    sso_login(second, eve, new_id(), "Second")
    page = anonymous.get("/community").text
    assert 'action="/community/votes"' not in page
    assert anonymous.post("/community/votes", data={"target": "direction:fittings"}).status_code in (401, 403)
    for client in (first, second):
        response = client.post("/community/votes", data={"csrf_token": csrf(client), "target": "direction:fittings"},
                               follow_redirects=False)
        assert response.headers["location"].endswith("#direction-fittings")
    page = first.get("/community").text
    assert "2 pilots would use this" in page and 'aria-pressed="true"' in page
    first.post("/community/votes", data={"csrf_token": csrf(first), "target": "direction:fittings"})
    assert "1 pilot would use this" in first.get("/community").text
    assert community.vote_counts() == {"direction:fittings": 1}
    bad = first.post("/community/votes", data={"csrf_token": csrf(first), "target": "direction:not-a-direction"},
                     follow_redirects=False)
    assert "can't take a mark" in flash(bad)


def test_marks_on_open_ideas_not_bugs_closed_or_hidden(browser, eve):
    client = browser()
    sso_login(client, eve, new_id(), "Voter")
    pid = me(client)
    publish(pid, 701)
    publish(pid, 702, "type:bug")
    publish(pid, 703, state="closed", state_reason="completed")
    publish(pid, 704, "platform:hidden")
    assert community.vote_anchor("issue:701") == "issue-701"
    assert community.vote_anchor("issue:702") is None
    assert community.vote_anchor("issue:703") is None
    assert community.vote_anchor("issue:704") is None
    assert community.vote_anchor("issue:999") is None and community.vote_anchor("drop table") is None
    client.post("/community/votes", data={"csrf_token": csrf(client), "target": "issue:701"})
    page = client.get("/community").text
    assert 'id="issue-701"' in page and "1 pilot would use this" in page
    assert "Same problem? Give it a thumbs-up or a comment on GitHub; it helps us prioritise." in page


def test_marks_follow_a_profile_merge_and_go_with_profile_deletion():
    from astracore.core import accounts
    src, dst = db.create_profile("Source"), db.create_profile("Destination")
    community.toggle_vote(src, "direction:fittings")
    community.toggle_vote(src, "direction:fleet-preparation")
    community.toggle_vote(dst, "direction:fittings")
    accounts.merge_profiles(src, dst)
    assert community.my_votes(dst) == {"direction:fittings", "direction:fleet-preparation"}
    assert community.vote_counts()["direction:fittings"] == 1
    db.delete_profile(dst)
    assert community.vote_counts() == {}


def test_shape_this_direction_prefills_the_idea_form(browser, eve):
    hub = browser().get("/community").text
    assert 'href="/feedback?direction=fittings"' in hub and 'id="direction-fittings"' in hub
    client = browser()
    sso_login(client, eve, new_id(), "Shaper")
    page = client.get("/feedback?direction=fittings").text
    assert 'value="Fittings across your alts: "' in page
    assert "/community#direction-fittings" in page and "You're shaping" in page
    plain = client.get("/feedback?direction=nope").text
    assert "You're shaping" not in plain and 'value=""' in plain


def test_hub_sections_thanks_and_copy(browser):
    page = browser().get("/community").text
    for anchor in ('id="roadmap-title"', 'id="reports-title"', 'id="whats-new-title"', 'id="thanks"',
                   'id="build"', 'id="creator"'):
        assert anchor in page
    assert page.index('id="roadmap-title"') < page.index('id="reports-title"') < page.index('id="whats-new-title"') \
        < page.index('id="thanks"') < page.index('id="build"') < page.index('id="creator"')
    for text in ("DalShooth/EVE_PI_Templates", "VOC Hauling", "Fuzzwork", "Fenris Creations", "Dutch Legions",
                 "Insidious.", "https://janice.e-351.com", "https://everef.net", "https://zkillboard.com",
                 "https://github.com/pyfa-org/Pyfa", "Support never changes access or features",
                 releases.history()[0]["title"]):
        assert text in page
    assert "Flashbang" not in page and "<strong>Light theme</strong><span>Easier in daylight.</span>" in page
    footer = page.split('<footer class="site-footer">', 1)[1]
    assert 'href="/credits#creator"' in footer and "revolut.me" not in footer
    project = browser().get("/project").text
    assert project.index("<h2>Report a bug</h2>") < project.index("Found a stowaway?")
    assert "Shape this direction" in page
    for path in ("/roadmap", "/project", "/credits", "/releases"):
        assert browser().get(path).status_code == 200
