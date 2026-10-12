"""The public VOC reference reads shared cached assumptions without changing pilot settings."""
import time

from astracore import db
from astracore.modules.pi import service, store
from astracore.modules.pi.static_data import voc
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401


def test_public_reference_uses_admin_terms_and_fallback_without_refresh(browser, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('A reference page must not request outside data')
    monkeypatch.setattr(voc, 'refresh_routes', forbidden)
    db.kv_set(voc.ROUTES_KEY, {})        # no cached tariff, whatever earlier tests left behind
    client = browser()
    store.save_admin_settings({'buyback_pct': 87, 'buyback_pct_p1': 0})
    page = client.get('/voc-hauling')
    assert page.status_code == 200
    assert '87%' in page.text and 'refused' in page.text
    assert 'Fallback values recorded on 10 October 2026' in page.text
    assert voc.CORP_NAME in page.text and voc.SITE in page.text and voc.BUYBACK_SITE in page.text
    assert 'Courier fees and contract limits' in page.text


def test_public_reference_shows_cached_tariff_without_substituting_defaults(browser):
    client = browser()
    db.kv_set(voc.ROUTES_KEY, {'at': time.time(), 'routes': [
        {'origin': 'Fictional pickup', 'dest': 'Fictional destination', 'min_fee': 4560000,
         'per_m3': 234, 'collateral_pct': 1.5, 'max_m3': 60000}]})
    page = client.get('/voc-hauling').text
    assert 'Cached from' in page and 'Viewing this page does not refresh' in page
    assert 'Fictional pickup' in page and 'Fictional destination' in page and '234' in page
    assert 'Fallback values recorded' not in page


def test_pilot_settings_links_reference_and_preserves_stored_assumptions(browser, eve, monkeypatch):
    client = browser()
    sso_login(client, eve, new_id(), 'Fictional settings pilot')
    pid = me(client)
    monkeypatch.setattr(service, 'planning_characters', lambda profile: [])
    before = store.load_settings(pid).to_json()
    page = client.get('/pi/settings').text
    assert 'href="/voc-hauling"' in page
    assert 'VOC courier tariff' not in page and 'VOC buyback pays' not in page
    assert 'taxes_from_skills' in page and 'stack_yield_pct' in page
    client.get('/voc-hauling')
    assert store.load_settings(pid).to_json() == before
