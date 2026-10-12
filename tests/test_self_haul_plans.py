"""Own-trip plans use fictional nullsec space and synthetic market books only."""
import copy
import re

from astracore.modules.pi import service, store
from astracore.modules.pi.planner import selling, prices
from astracore.modules.pi.settings import Settings
from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401
from test_planner import pi, _area, CHARS, TEMPLATES, BOOKS  # noqa: F401


def outside_context(monkeypatch, pi):
    area = _area()
    for system in area['systems'].values():
        system['region'] = 'Fictional nullsec'
    books = copy.deepcopy(BOOKS)
    for book in books.values():
        for hub in ('jita', 'amarr'):
            book[f'{hub}_buy_depth'] = [[book[f'{hub}_buy'], 1e9]]
            book[f'{hub}_buy_orders'] = [[book[f'{hub}_buy'], 1e9, 1]]
    async def static():
        return pi, TEMPLATES
    async def space(*args, **kwargs):
        return area
    async def market(*args, **kwargs):
        return books
    monkeypatch.setattr(service, 'load_static', static)
    monkeypatch.setattr(service, 'load_space', space)
    monkeypatch.setattr(service, 'market_data', market)
    monkeypatch.setattr(service, 'planning_characters', lambda pid: copy.deepcopy(CHARS))
    monkeypatch.setattr(prices, 'cached', lambda: {'at': 123, 'books': books})
    monkeypatch.setattr(prices, 'history_cached', lambda: {'at': 123, 'markets': {}})
    monkeypatch.setattr(selling.voc, 'routes_cached', lambda: [])
    return area, books


def test_explicit_own_trip_overrides_courier_without_changing_default(pi, monkeypatch):
    routes = [{'origin': '7G-QIG', 'dest': selling.voc.JITA, 'per_m3': 1, 'collateral_pct': 1,
               'min_fee': 10e6, 'max_m3': 1e6}]
    monkeypatch.setattr(selling.voc, 'routes_cached', lambda: routes)
    normal = selling.channel_values(pi, Settings(use_amarr=False), BOOKS, 2396, '7G-QIG')
    own = selling.channel_values(pi, Settings(use_self_haul=True, use_amarr=False), BOOKS, 2396, '7G-QIG')
    assert 'jita_buy' in normal and 'jita_self' not in normal
    assert 'jita_self' in own and 'jita_buy' not in own
    plan = selling.sell_plan(pi, Settings(use_self_haul=True, use_amarr=False, use_buyback=False,
                                         use_local=False), BOOKS, '7G-QIG', {2396: 1e6})
    assert all('contract' not in batch for batch in plan['batches'])
    assert 'loss risk' in plan['batches'][0]['note']


def test_outside_plan_choice_persists_and_values_sales_demand_and_comparisons(browser, eve, pi, monkeypatch):
    outside_context(monkeypatch, pi)
    client = browser()
    sso_login(client, eve, new_id(), 'Fictional outside pilot')
    pid = me(client)
    store.save_settings(pid, Settings(effort=100, max_tier=1, max_systems=0, max_jumps=1,
                                      hub_system='HUB', selected_constellations=[1]))
    patch = {'use_self_haul': True, 'use_buyback': False, 'use_local': False,
             'use_jita': True, 'use_amarr': True, 'use_sell_orders': False}
    headers = {'X-CSRF-Token': csrf(client)}
    before = service.plan_key(pid, store.load_settings(pid))
    assert client.post('/pi/api/save', json=patch, headers=headers).json()['ok']
    saved = store.load_settings(pid)
    assert saved.use_self_haul and service.plan_key(pid, saved) != before
    comparison = client.post('/pi/api/whatif', json={'base': {}, 'options': [{'id': 'own', 'patch': patch}]},
                             headers=headers).json()[0]
    assert comparison['sell_net_per_day'] > 0
    result = client.post('/pi/api/suggest', json=patch, headers=headers).json()
    assert result['totals']['isk_per_day'] > 0 and result['self_haul']
    assert not result['selling']['unsellable']
    assert all(b['channel'].endswith('_self') and 'contract' not in b for b in result['selling']['batches'])
    assert result['demand']['rows'] and all(row['side'] == 'buy' for row in result['demand']['rows'])
    assert all(row['channel'].endswith('_self') for row in result['demand']['rows'])
    assert result['channel_labels'] and all(channel.endswith('_self') for channel in result['channel_labels'])
    assert not any(w['code'].startswith('voc_') for w in result['warnings'])
    assert any(w['code'] == 'self_haul' and 'loss risk' in w['text'] for w in result['warnings'])
    page = client.get('/pi/plan').text
    coverage = re.search(r'let SELL_COVERAGE = (.*?);', page).group(1)
    assert '"local": false' in coverage and '"courier": false' in coverage
    assert 'Haul to Jita / Amarr myself' in page and 'journey time, fuel and loss risk are not priced' in page
