"""#232: a wider answer card never shows less ISK than an answer it contains. #246: the result reconciles the
plan's ISK/day with what its batches pay out."""
import asyncio
import json

import pytest

from astracore.modules.pi import routes, service
from astracore.modules.pi.settings import Settings

from test_core import browser, csrf, eve, new_id, sso_login  # noqa: F401 - pytest fixtures

TIERS = [{'id': t, 'patch': {'max_tier': t}} for t in (1, 2, 3, 4)]
AREAS = [{'id': 'compact', 'patch': {'max_systems': 1, 'max_jumps': 1}},
         {'id': 'near', 'patch': {'max_systems': 3, 'max_jumps': 3}},
         {'id': 'wide', 'patch': {'max_systems': 0, 'max_jumps': 6}}]
BUYS = [{'id': 'own', 'patch': {'buy_inputs': False, 'input_budget_isk': 0}},
        {'id': 'b1', 'patch': {'buy_inputs': True, 'input_budget_isk': 1e9}},
        {'id': 'b5', 'patch': {'buy_inputs': True, 'input_budget_isk': 5e9}},
        {'id': 'free', 'patch': {'buy_inputs': True, 'input_budget_isk': 0}}]


def card(oid, isk, mix='mix'):
    return {'id': oid, 'totals': {'isk_per_day': isk, 'systems': 2}, 'mix': f'{mix} {oid}',
            'facts': {'minutes_per_week': 60}}


def test_nesting_follows_what_each_answer_allows():
    contains = service.answer_contains
    assert contains({'max_tier': 4}, {'max_tier': 3}) and not contains({'max_tier': 3}, {'max_tier': 4})
    assert not contains({'max_tier': 3}, {'max_tier': 3})
    near, wide, compact = AREAS[1]['patch'], AREAS[2]['patch'], AREAS[0]['patch']
    assert contains(wide, near) and contains(near, compact) and contains(wide, compact)
    assert not contains(compact, wide)
    assert contains({'max_systems': 3, 'max_jumps': 6}, compact)
    assert not contains({'max_systems': 5, 'max_jumps': 1}, {'max_systems': 1, 'max_jumps': 3})
    own, b1, b5, free = (o['patch'] for o in BUYS)
    assert contains(b1, own) and contains(b5, b1) and contains(free, b5) and contains(free, own)
    assert not contains(b1, b5) and not contains(own, b1) and not contains(b5, free)
    # Answers to questions that don't only widen limits never nest.
    assert not contains({'cycle_days': 1}, {'cycle_days': 3})
    assert not contains({'ship_every_days': 28}, {'ship_every_days': 7})
    assert not contains({'max_tier': 4, 'cycle_days': 1}, {'max_tier': 3, 'cycle_days': 1})


def test_wider_answer_below_a_contained_one_shows_the_best_contained_plan():
    cards = [card(1, 50e6), card(2, 80e6), card(3, 95.4e6), card(4, 89.7e6)]
    fixed = service.same_plan_cards(TIERS, cards)
    assert len(fixed) == 1
    p4 = fixed[0]
    assert p4['id'] == 4 and p4['same_as'] == 3
    assert p4['totals'] == cards[2]['totals'] and p4['mix'] == 'mix 3'
    assert cards[3]['totals']['isk_per_day'] == 89.7e6          # the originals are left alone
    # Deterministic: the same cards always give the same answer.
    assert service.same_plan_cards(TIERS, cards) == fixed


def test_the_best_of_all_contained_answers_wins_and_errors_are_skipped():
    cards = [card(1, 90e6), card(2, 70e6), {'id': 3, 'error': 'No plan'}, card(4, 60e6)]
    fixed = {c['id']: c for c in service.same_plan_cards(TIERS, cards)}
    assert fixed[2]['same_as'] == 1 and fixed[4]['same_as'] == 1
    assert 3 not in fixed


def test_nothing_changes_when_wider_answers_earn_at_least_as_much():
    assert service.same_plan_cards(TIERS, [card(1, 50e6), card(2, 50e6), card(3, 60e6), card(4, 61e6)]) == []
    assert service.same_plan_cards(AREAS, [card('compact', 10e6), card('near', 20e6), card('wide', 30e6)]) == []
    cycles = [{'id': d, 'patch': {'cycle_days': d}} for d in (1, 3)]
    assert service.same_plan_cards(cycles, [card(1, 10e6), card(3, 50e6)]) == []


def test_area_and_budget_answers_are_corrected_too():
    fixed = service.same_plan_cards(AREAS, [card('compact', 40e6), card('near', 30e6), card('wide', 35e6)])
    assert [(c['id'], c['same_as']) for c in fixed] == [('near', 'compact'), ('wide', 'compact')]
    fixed = service.same_plan_cards(BUYS, [card('own', 10e6), card('b1', 30e6), card('b5', 29e6), card('free', 40e6)])
    assert [(c['id'], c['same_as']) for c in fixed] == [('b5', 'b1')]


def test_saving_the_shown_answer_plans_the_shown_plan():
    """The page saves the contained answer for a "same plan" card: its settings, and so its cached plan,
    are exactly those of the card whose figures are shown."""
    base = Settings()
    fixed = service.same_plan_cards(TIERS, [card(1, 1), card(2, 2), card(3, 3), card(4, 2.5)])[0]
    shown = next(o for o in TIERS if o['id'] == fixed['same_as'])
    saved = routes._whatif_settings(base, shown)
    assert saved.solve_json() == routes._whatif_settings(base, TIERS[2]).solve_json()


# ----------------------------------------------------------------------------- the endpoint
@pytest.fixture
def pilot(browser, eve):  # noqa: F811
    client = browser()
    sso_login(client, eve, new_id(), 'Fictional Same Plan Pilot')
    return client, {'X-CSRF-Token': csrf(client)}


def fake_cards(monkeypatch, isk):
    async def whatif_card(pid, base, opt):
        await asyncio.sleep({1: 0.03, 2: 0.0, 3: 0.02, 4: 0.01}[opt['id']])
        return card(opt['id'], isk[opt['id']])
    monkeypatch.setattr(routes, '_whatif_card', whatif_card)


def test_streamed_comparison_corrects_a_wider_card_once_every_card_is_in(pilot, monkeypatch):
    client, headers = pilot
    fake_cards(monkeypatch, {1: 50e6, 2: 80e6, 3: 95.4e6, 4: 89.7e6})
    r = client.post('/pi/api/whatif', json={'base': {}, 'options': TIERS, 'stream': True}, headers=headers)
    events = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    cards = [e['card'] for e in events if 'card' in e]
    assert [c['id'] for c in cards] == [2, 4, 3, 1, 4]                 # each card as it's ready, then the fix
    assert 'same_as' not in cards[1] and cards[1]['totals']['isk_per_day'] == 89.7e6
    assert cards[-1]['same_as'] == 3 and cards[-1]['totals']['isk_per_day'] == 95.4e6
    assert events[-1] == {'done': True}


def test_list_comparison_returns_corrected_cards_in_order(pilot, monkeypatch):
    client, headers = pilot
    fake_cards(monkeypatch, {1: 50e6, 2: 80e6, 3: 95.4e6, 4: 89.7e6})
    rows = client.post('/pi/api/whatif', json={'base': {}, 'options': TIERS}, headers=headers).json()
    assert [r['id'] for r in rows] == [1, 2, 3, 4]
    assert rows[3]['same_as'] == 3 and rows[3]['totals']['isk_per_day'] == 95.4e6
    assert all('same_as' not in r for r in rows[:3])


# ----------------------------------------------------------------------------- #246
def plan_with_batches(paid_per_day, held=False):
    return {
        'totals': {'isk_per_day': 80_000_000, 'buy_isk_per_day': 10_000_000},
        'colonies': [{'tax_per_day': 3_000_000}, {'tax_per_day': 2_000_000}],
        'sold': [{'item': 'Fictional Gel', 'isk_per_day': 90_000_000},
                 {'item': 'Fictional Dust', 'isk_per_day': 5_000_000}],
        'selling': {'net_per_day': paid_per_day, 'batches': [
            {'items': {'Fictional Gel': 100}, 'net': 1},
            {'items': {'Fictional Dust': 10}, 'net': -1, 'hold': held}]},
    }


def test_income_check_adds_up_the_two_daily_figures():
    c = service.income_check(plan_with_batches(94_000_000, held=True))
    assert c == {'paid': 94_000_000, 'plan': 80_000_000, 'customs': 5_000_000, 'inputs': 10_000_000,
                 'held': 5_000_000, 'other': 4_000_000}
    assert c['paid'] == c['plan'] + c['customs'] + c['inputs'] - c['held'] + c['other']
    c = service.income_check(plan_with_batches(95_000_000))
    assert c['held'] == 0 and c['other'] == 0


def test_income_check_needs_a_selling_plan():
    assert service.income_check({'totals': {'isk_per_day': 1}}) is None
    assert service.income_check({'totals': {'isk_per_day': 1}, 'selling': {'batches': []}}) is None
