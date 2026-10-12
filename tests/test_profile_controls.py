"""Profile actions stay understandable with multiple fictional characters."""
from astracore import db
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401


def test_profile_groups_old_permissions_and_keeps_export_outside_danger(browser, eve):
    c = browser()
    for name in ('Synthetic main', 'Synthetic alt'):
        cid = new_id()
        sso_login(c, eve, cid, name)
        db.save_token(cid, 'fake', 'fake', 1000, ' '.join(db.get_character(cid)['scopes']) + ' obsolete.scope')
    html = c.get('/profile').text
    assert '2 characters still hold old extra permissions' in html
    assert html.count('class="box permissions-notice"') == 1
    assert 'Update permissions for Synthetic main' in html and 'Update permissions for Synthetic alt' in html
    assert 'Your main character supplies' in html
    assert html.index('href="/profile/export.json"') < html.index('aria-labelledby="dz-h"')
    assert 'data-confirm="End every signed-in browser session' in html
    assert 'Character actions for Synthetic main' in html
    assert 'Character actions for Synthetic alt' in html
    assert html.count('role="switch"') == 4
    assert 'Pause</button>' not in html and 'Turn off</a>' not in html
    assert 'href="/pi/reset"' in html


def test_last_character_removal_goes_to_typed_confirmation(browser, eve):
    c = browser()
    cid = new_id()
    sso_login(c, eve, cid, 'Synthetic only')
    html = c.get('/profile').text
    assert 'href="/profile/reset">Remove last character…</a>' in html
    assert f'action="/profile/characters/{cid}/remove"' not in html
    assert db.character_profile(cid) == me(c)
