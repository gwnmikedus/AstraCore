"""The illustrative landing choice survives a fictional EVE sign-in, without replacing answered goals."""
import pytest

from astracore import config, db
from astracore.modules.pi import store
from astracore.modules.pi.settings import Settings
from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401


@pytest.mark.parametrize('rhythm,effort', [('passive', 0), ('balanced', 50), ('max', 100)])
def test_new_pilot_rhythm_survives_login_welcome_and_pi_entry(browser, eve, rhythm, effort):
    c = browser()
    response, _ = sso_login(c, eve, new_id(), 'Rhythm pilot', path=f'/auth/login?rhythm={rhythm}')
    assert response.headers['location'] == '/welcome'
    pid = me(c)
    assert store.load_settings(pid).effort == effort
    assert store.load_settings(pid).answered == []
    c.post('/welcome/done', data={'csrf_token': csrf(c), 'next': '/'}, follow_redirects=False)
    c.get('/pi', follow_redirects=False)
    assert store.load_settings(pid).effort == effort
    assert store.load_settings(pid).answered == []


def test_returning_pilot_preview_cannot_replace_an_answered_goal(browser, eve):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, 'Returning pilot')
    pid = me(c)
    s = Settings(effort=75, cycle_days=7, hour_isk=123_000_000, answered=['goal', 'cycle'])
    store.save_settings(pid, s)
    before = db.module_settings(pid, 'pi')
    other = browser()
    sso_login(other, eve, cid, 'Returning pilot', path='/auth/login?rhythm=passive')
    assert me(other) == pid
    assert db.module_settings(pid, 'pi') == before
    other.get('/pi?rhythm=max', follow_redirects=False)
    assert db.module_settings(pid, 'pi') == before


def test_preview_sets_only_the_unanswered_goal_and_not_other_preferences(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), 'Signed-in preview')
    pid = me(c)
    store.save_settings(pid, Settings(cycle_days=7, ship_every_days=14, hour_isk=123_000_000, answered=['cycle']))
    before = db.module_settings(pid, 'pi')
    c.get('/pi?rhythm=max', follow_redirects=False)
    assert db.module_settings(pid, 'pi') == {**before, 'effort': 100}
    sso_login(c, eve, new_id(), 'Added alt', path='/auth/login?intent=add&rhythm=passive')
    assert store.load_settings(pid).effort == 100


@pytest.mark.parametrize('rhythm', ['', '100', 'invalid', '//outside.example'])
def test_invalid_preview_values_are_ignored_and_cannot_expand_login_destinations(browser, eve, rhythm):
    c = browser()
    response, _ = sso_login(c, eve, new_id(), 'Ignored preview',
                            path=f'/auth/login?rhythm={rhythm}&next=https://outside.example')
    assert response.headers['location'] == '/welcome'
    assert db.module_settings(me(c), 'pi') is None
    c.get(f'/pi?rhythm={rhythm}', follow_redirects=False)
    assert db.module_settings(me(c), 'pi') is None


def test_refused_login_does_not_store_preview_settings(browser, eve, monkeypatch):
    monkeypatch.setattr(config, 'ACCESS_GATE', True)
    for kind in config.ALLOWED:
        monkeypatch.setitem(config.ALLOWED, kind, set())
    c = browser()
    with db.session() as connection:
        before = connection.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]
    response, _ = sso_login(c, eve, new_id(), 'Refused preview', path='/auth/login?rhythm=max')
    assert response.status_code == 403
    with db.session() as connection:
        after = connection.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]
    assert after == before and not me(c)


def test_public_and_signed_in_preview_links_have_a_no_script_starting_choice(browser, eve):
    c = browser()
    assert 'href="/auth/login?rhythm=passive" class="text-action" data-preview-start' in c.get('/').text
    sso_login(c, eve, new_id(), 'Preview visitor')
    assert 'href="/pi?rhythm=passive" class="text-action" data-preview-start' in c.get('/about').text
