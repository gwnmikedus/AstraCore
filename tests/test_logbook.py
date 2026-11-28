"""Capsuleer's logbook (#289): finds, the hidden page, the opt-in ranking and the footer hint. No network."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from astracore import db
from astracore.core import logbook
from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401


@pytest.fixture(autouse=True)
def clean_logbook():
    def clean():
        with db.session() as c:
            c.execute("DELETE FROM logbook_finds")
            c.execute("DELETE FROM logbook_ranking")
    clean()
    yield
    clean()


def ts(iso: str) -> float:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()


def pilot(browser, eve, name="Egg Hunter"):
    client = browser()
    cid = new_id()
    sso_login(client, eve, cid, name)
    return client, cid, me(client)


def found(client, *eggs):
    return client.post("/logbook/found", json={"eggs": list(eggs)}, headers={"X-CSRF-Token": csrf(client)})


def test_migration_adds_only_new_tables():
    assert db.MIGRATIONS[9].__name__ == "_migrate_v10"
    with db.session() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"logbook_finds", "logbook_ranking"} <= names


def test_catalog_has_fifteen_eggs_with_hints_and_points():
    assert logbook.TOTAL == 15 and len(logbook.EGG_BY_ID) == 15
    assert all(e["hint"] and e["points"] in (1, 2, 3, 5) for e in logbook.EGGS)


def test_calendar_eggs_only_on_their_day():
    assert logbook.can_find("downtime", ts("2026-11-28T11:10:00"))
    assert not logbook.can_find("downtime", ts("2026-11-28T15:00:00"))
    assert logbook.can_find("birthday", ts("2027-05-06T12:00:00"))
    assert not logbook.can_find("birthday", ts("2027-05-08T12:00:00"))
    assert logbook.can_find("holidays", ts("2026-12-25T00:30:00"))
    assert logbook.can_find("new_year", ts("2026-12-31T23:30:00")), "an hour of slack around midnight"
    assert logbook.can_find("konami", ts("2026-11-28T15:00:00"))
    assert not logbook.can_find("not-an-egg")


def test_finds_need_a_session_and_csrf(browser):
    client = browser()
    r = client.post("/logbook/found", json={"eggs": ["o7"]})
    assert r.status_code == 403


def test_recording_finds_counts_once_and_ignores_unknown_and_off_day_eggs(browser, eve):
    client, _, pid = pilot(browser, eve)
    r = found(client, "o7", "bogus", "birthday" if not logbook.can_find("birthday") else "bogus").json()
    assert r["new"] == ["o7"] and r["count"] == 1 and r["total"] == 15 and not r["open"]
    assert found(client, "o7").json()["new"] == []
    r = found(client, "logo", "konami").json()
    assert r["count"] == 3 and r["open"] and r["opened"]
    assert found(client, "flashbang").json()["opened"] is False
    bad = client.post("/logbook/found", json={"eggs": "o7"}, headers={"X-CSRF-Token": csrf(client)})
    assert bad.status_code == 400


def test_logbook_page_is_hidden_until_three_finds(browser, eve):
    anonymous = browser()
    assert anonymous.get("/logbook").status_code == 404
    client, _, _ = pilot(browser, eve)
    found(client, "o7", "logo")
    page = client.get("/logbook")
    assert page.status_code == 404 and "Capsuleer’s logbook" not in page.text.split('<footer', 1)[0]
    found(client, "konami")
    page = client.get("/logbook")
    assert page.status_code == 200
    assert "Capsuleer’s logbook" in page.text and "Cheat code" in page.text
    assert "Unknown signal" in page.text and "Hint: The theme switch has opinions" in page.text


def test_footer_line_hints_counts_and_links_once_open(browser, eve):
    anonymous = browser().get("/about").text
    assert "Rumour has it 15 things are hidden in AstraCore." in anonymous
    client, _, _ = pilot(browser, eve)
    found(client, "o7")
    footer = client.get("/about").text.split('<footer class="site-footer">', 1)[1]
    assert "Capsuleer’s logbook: 1 of 15 found. Find 3 to open it." in footer
    assert 'data-found="o7"' in footer and "data-signed-in" in footer
    found(client, "logo", "konami")
    footer = client.get("/about").text.split('<footer class="site-footer">', 1)[1]
    assert re.search(r'<a href="/logbook">Capsuleer’s logbook: 3 of 15 found', footer)


def test_ranking_is_opt_in_with_own_character_and_stays_up_to_date(browser, eve):
    alice, alice_cid, alice_pid = pilot(browser, eve, "Alice Hunter")
    bob, bob_cid, _ = pilot(browser, eve, "Bob Private")
    found(alice, "o7", "logo", "konami")
    found(bob, "o7", "logo", "konami", "console")
    page = alice.get("/logbook").text
    assert "Nobody is on the ranking yet" in page and "2 pilots hunt in private" in page
    assert "Bob Private" not in page

    token = csrf(alice)
    r = alice.post("/logbook/ranking", data={"csrf_token": token, "character_id": str(bob_cid)}, follow_redirects=False)
    assert "own" in r.headers["location"] and logbook.ranking_choice(alice_pid) is None
    alice.post("/logbook/ranking", data={"csrf_token": token, "character_id": str(alice_cid)})
    assert logbook.ranking_choice(alice_pid) == alice_cid
    page = alice.get("/logbook").text
    assert "Alice Hunter" in page and "Bob Private" not in page and f"/characters/{alice_cid}/portrait" in page
    assert re.search(r"First found by <span class=\"eve-name\">Alice Hunter</span>", page)
    assert "#1" in page

    before = logbook.ranking()["board"][0]
    found(alice, "flashbang")
    after = logbook.ranking()["board"][0]
    assert after["eggs"] == before["eggs"] + 1 and after["points"] == before["points"] + 1

    alice.post("/logbook/ranking", data={"csrf_token": token, "character_id": ""})
    assert logbook.ranking()["board"] == []


def test_ranking_orders_by_points_then_who_got_there_first():
    pids = [db.create_profile(f"P{i}") for i in range(3)]
    cids = [new_id() for _ in pids]
    for pid, cid, name in zip(pids, cids, ("First", "Second", "Third")):
        db.link_character(cid, pid, name)
        logbook.set_ranking(pid, cid)
    logbook.record(pids[0], ["o7", "logo", "konami"], now=100)            # 4 points, done at 100
    logbook.record(pids[1], ["o7", "logo", "yc_year", "flashbang"], now=50)  # 4 points, done at 50
    logbook.record(pids[2], ["o7", "logo", "console", "konami"], now=200)   # 6 points
    board = logbook.ranking()["board"]
    assert [row["name"] for row in board] == ["Third", "Second", "First"]
    assert [row["rank"] for row in board] == [1, 2, 3]
    for pid in pids:
        db.delete_profile(pid)


def test_reset_and_character_removal_leave_no_logbook_trace(browser, eve):
    client, cid, pid = pilot(browser, eve, "Gone Hunter")
    found(client, "o7", "logo", "konami")
    logbook.set_ranking(pid, cid)
    db.delete_profile(pid)
    with db.session() as c:
        assert c.execute("SELECT COUNT(*) FROM logbook_finds WHERE profile_id=?", (pid,)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM logbook_ranking WHERE profile_id=?", (pid,)).fetchone()[0] == 0


def test_privacy_page_describes_the_logbook(browser):
    page = browser().get("/privacy").text
    assert "capsuleer’s logbook" in page and "easter eggs you found while signed out" in page


def test_tooltip_eggs_are_marked_for_the_logbook(browser):
    page = browser().get("/no-such-page").text
    assert 'data-egg-hover="not_on_overview"' in page and 'data-egg-hover="yc_year"' in page
    assert 'data-egg-hover="flashbang" data-egg-when="dark"' in page
