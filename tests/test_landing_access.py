"""Landing page trust basics, the invite-only page, the connect page and the empty Area page (#110, #81)."""
from __future__ import annotations

import html
import re

from astracore import config, db
from astracore.core import accounts, eveimg, registry
from astracore.modules.pi import service

from test_core import PI_SCOPES, browser, eve, new_id, sso_login  # noqa: F401 (fixtures)

GROUPS = {"alliance": {"id": 99000001, "name": "Example Alliance."},
          "corporation": {"id": 98000001, "name": "Example Corp", "alliance_id": 99000001}}


def _text(page: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))


def _gate(monkeypatch, on=True):
    monkeypatch.setattr(config, "ACCESS_GATE", on)
    monkeypatch.setitem(config.ALLOWED, "corporation", {98000001})
    monkeypatch.setitem(config.ALLOWED, "alliance", {99000001})
    monkeypatch.setattr(eveimg, "home_groups", lambda: GROUPS)


def test_member_names_drop_a_trailing_full_stop_in_running_text(monkeypatch):
    _gate(monkeypatch)
    groups = accounts.member_groups()
    assert groups["alliance"]["name"] == "Example Alliance."          # the exact EVE name is kept
    assert groups["alliance"]["label"] == "Example Alliance"
    assert groups["phrase"] == "Example Corp and Example Alliance"


def test_landing_states_free_invite_only_read_only_and_creator(browser, monkeypatch):
    _gate(monkeypatch)
    page = browser().get("/").text
    text = _text(page)
    assert "Alliance. and" not in text and "Alliance., " not in text
    row = _text(re.search(r'<ul class="assurance-row".*?</ul>', page, re.S).group(0))
    for item in ("Free", "Invite-only for Example Corp and Example Alliance", "Read-only EVE login", "Run by CosmicCarrot"):
        assert item in row
    assert 'href="/what-we-read"' in re.search(r'<ul class="assurance-row".*?</ul>', page, re.S).group(0)
    # DalShooth makes the templates; AstraCore only refers to them.
    assert "Colony templates included" not in text and "DalShooth colony templates, ready to place" in text
    assert page.count("Build my PI plan") <= 3                         # navigation, hero, closing panel
    headlines = [_text(h) for h in re.findall(r"<h[12][^>]*>.*?</h[12]>", page, re.S)]
    for line in ("All your alts.", "Your planets."):                  # each headline is used once
        assert sum(line in h for h in headlines) == 1
    # The preview announces only its title and description, not the whole panel.
    live = re.search(r'<div class="preview-live" aria-live="polite" aria-atomic="true">(.*?)</div>', page, re.S)
    assert live and "data-preview-title" in live.group(1) and "data-preview-description" in live.group(1)
    assert "production-chain" not in live.group(1)
    assert 'class="preview-output" aria-live' not in page


def test_landing_without_a_gate_does_not_claim_invite_only(browser, monkeypatch):
    _gate(monkeypatch, on=False)
    row = re.search(r'<ul class="assurance-row".*?</ul>', browser().get("/").text, re.S).group(0)
    assert "Invite-only" not in row and "Free" in row


def test_invite_only_page_names_next_step_and_what_was_kept(browser, eve, monkeypatch):
    _gate(monkeypatch)
    c = browser()
    stranger = new_id()
    r, _ = sso_login(c, eve, stranger, "Stranger")
    text = _text(r.text)
    assert r.status_code == 403
    assert "Ask in your corporation or alliance channel" in text
    assert "Members of Example Corp and Example Alliance can sign in" in text
    assert "no profile was created and no token was stored" in text and "EVE confirmed it" in text
    assert db.get_character(stranger) is None and db.get_token(stranger) is None
    assert list(eve.logins.values())[-1]["refresh_token"] in eve.revoked


def test_invite_only_page_is_honest_when_eve_does_not_confirm_the_revoke(browser, eve, monkeypatch):
    _gate(monkeypatch)
    from astracore.esi import sso

    async def unconfirmed(rt):
        return False
    monkeypatch.setattr(sso, "revoke", unconfirmed)
    r, _ = sso_login(browser(), eve, new_id(), "Unlucky")
    text = _text(r.text)
    assert "EVE confirmed it" not in text and "third-party applications" in text


def test_connect_page_explains_scopes_in_plain_words(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Newcomer", scopes="publicData")
    page = c.get("/pi", follow_redirects=False).text
    assert "<code>esi-" not in page
    assert "read-only" in _text(page).lower()
    for scope in registry.get("pi").required_bundle.scopes:
        assert registry.SCOPE_TEXT[scope] in _text(page)


def test_empty_area_shows_a_visible_search_field(browser, eve, monkeypatch):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, "No colonies")
    db.save_token(cid, "rt", "at", 1199, PI_SCOPES)

    async def nothing(chars, s, force=False):
        return None
    monkeypatch.setattr(service, "load_space", nothing)
    page = c.get("/pi/area").text
    start = re.search(r'<section class="area-start".*?</section>', page, re.S)
    assert start and 'name="extra_area"' in start.group(0)
    assert "Where do you want to do PI?" in page
    assert "<summary>Add another region" not in page
