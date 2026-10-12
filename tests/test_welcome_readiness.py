"""Welcome shows read skill levels, and never invents them when ESI failed."""
from html import unescape

import pytest

from astracore import db
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401


@pytest.mark.parametrize('level,label,advice', [
    (0, "Can't be planned yet", 'Train Command Center Upgrades to 2'),
    (2, 'Most factories only', 'Train Command Center Upgrades to 4'),
    (3, 'Factories only', 'Train Command Center Upgrades to 4'),
    (4, 'Nullsec miners and factories', ''),
    (5, 'OK for every template', ''),
])
def test_welcome_reuses_template_skill_readiness(browser, eve, level, label, advice):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, 'Synthetic skill pilot')
    db.set_character(cid, ccu_level=level, slots=3, synced_at=12345)
    html = unescape(c.get('/welcome').text)
    assert label in html
    assert f'Command Center Upgrades {level} · 3 colony slots' in html
    if advice:
        assert advice in html
    assert 'Switch account' in html
    assert 'href="/profile#acc-h"' in html
    assert 'Group by EVE account' not in html and 'action="/profile/accounts"' not in html
    assert 'Plan my operation' in html and 'Skip for now' in html


def test_welcome_does_not_treat_unread_skills_as_untrained(browser, eve):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, 'Synthetic unread pilot')
    db.set_character(cid, ccu_level=0, slots=0, synced_at=None)
    html = unescape(c.get('/welcome').text)
    assert 'PI skills have not been read yet' in html
    assert f'href="/profile#char-{cid}"' in html
    assert "Can't be planned yet" not in html and 'Train Command Center Upgrades' not in html
    assert 'Command Center Upgrades 0' not in html


def test_welcome_points_expired_login_to_the_character_upgrade(browser, eve):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, 'Synthetic expired pilot')
    db.set_character(cid, status='needs_login')
    html = unescape(c.get('/welcome').text)
    assert 'Log in again to read PI skills' in html
    assert f'href="/auth/upgrade/{cid}"' in html
    assert db.character_profile(cid) == me(c)
