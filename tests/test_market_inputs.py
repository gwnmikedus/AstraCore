"""Plans with inputs bought on the market (#225): offline, fictional planets and synthetic prices."""
import json
from pathlib import Path

from astracore.modules.pi.planner import optimizer, selling
from astracore.modules.pi.settings import Settings
from astracore.modules.pi.static_data import voc
from astracore.modules.pi.static_data.sde_loader import PIData

METADATA = json.loads((Path(__file__).parent / 'fixtures/sterile_conduits_metadata.json').read_text())
PI = PIData.from_json(METADATA['pi'])
P4 = METADATA['target']                    # Sterile Conduits: 6 Smartfab Units + 6 Vaccines + 40 Water
SMARTFAB, VACCINES, WATER = 2351, 28974, 3645
INPUT_COST = {SMARTFAB: {'jita': 100_000.0}, VACCINES: {'jita': 100_000.0}, WATER: {'jita': 500.0}}


def scenario(n_chars=1, **settings):
    kinds = ['Barren', 'Temperate', 'Gas', 'Ice', 'Lava', 'Oceanic', 'Plasma', 'Storm']
    planets = [{'planet_id': 100 + i, 'name': f'Fictional planet {i}', 'type': kinds[i % 8]} for i in range(10)]
    systems = {1: {'system_id': 1, 'name': 'Fictional system 1', 'security': -0.5, 'planets': planets,
                   'neighbours': []}}
    area = {'systems': {'1': systems[1]}}
    chars = [{'character_id': i + 1, 'name': f'Fictional pilot {i + 1}', 'slots': 6, 'ccu_level': 5,
              'colonies': []} for i in range(n_chars)]
    s = Settings(max_tier=4, effort=100, hour_isk=0, per_planet=1, cycle_days=1, max_jumps=1, max_systems=1,
                 hub_system='Fictional system 1', **settings)
    return s, area, systems, chars


def solve(p4_value, buy=INPUT_COST, n_chars=1, **settings):
    s, area, systems, chars = scenario(n_chars, **settings)
    return optimizer.plan(PI, s, area, systems, chars, {P4: p4_value}, METADATA['templates'], head_yield=3000,
                          buy=buy)


def p4_rows(res):
    return [c for c in res['colonies'] if c['product_id'] == P4]


def test_factory_only_p4_plan_on_one_character_when_bought_inputs_pay():
    res = solve(2_000_000.0)
    assert 'error' not in res
    assert p4_rows(res), res['totals']
    bought = {r['type_id']: r for r in res['bought']}
    assert {SMARTFAB, VACCINES} <= set(bought)
    # what the factory eats at its utilisation is exactly what's bought (nothing of its own feeds it)
    eaten = sum(c['in_per_day'].get('Smartfab Units', 0) for c in p4_rows(res))
    assert eaten > 0 and abs(bought[SMARTFAB]['units_per_day'] - eaten) < 1
    assert all(c['kind'] == 'factory' or c['tier'] == 1 for c in res['colonies'])
    assert abs(res['totals']['buy_isk_per_day'] - sum(r['isk_per_day'] for r in res['bought'])) <= len(bought)
    assert res['totals']['capital_isk'] == round(res['totals']['buy_isk_per_day'] * optimizer.capital_days(
        scenario()[0]))
    assert res['totals']['isk_per_day'] > 0
    assert not res['transfers']


def test_no_p4_when_bought_inputs_cost_more_than_it_sells_for():
    res = solve(1_000_000.0)
    assert not p4_rows(res)
    assert not res['bought']


def test_own_production_only_never_buys():
    res = solve(2_000_000.0, buy={})
    assert not res['bought'] and res['totals']['buy_isk_per_day'] == 0
    assert not p4_rows(res)   # a self-fed P4 chain doesn't fit one character's six slots


def test_budget_caps_the_capital_tied_up_in_inputs():
    free = solve(2_000_000.0)
    budget = free['totals']['capital_isk'] / 4
    capped = solve(2_000_000.0, input_budget_isk=budget)
    assert 0 < capped['totals']['capital_isk'] <= budget * 1.01
    assert capped['totals']['isk_per_day'] < free['totals']['isk_per_day']


def test_inputs_are_never_bought_to_resell():
    # selling Smartfab Units is worth more than buying them, but the planner only buys what factories use
    s, area, systems, chars = scenario()
    res = optimizer.plan(PI, s, area, systems, chars, {P4: 2_000_000.0, SMARTFAB: 500_000.0},
                         METADATA['templates'], head_yield=3000, buy=INPUT_COST)
    sold = {r['type_id']: r['units_per_day'] for r in res['sold']}
    assert sold.get(SMARTFAB, 0) <= sum(c['out_per_day'].get('Smartfab Units', 0) for c in res['colonies']) + 0.5


def test_cross_character_plans_also_draw_on_bought_inputs():
    res = solve(2_000_000.0, n_chars=2, cross_character=True)
    assert p4_rows(res) and res['bought']


def books():
    return {SMARTFAB: {'jita_sell': 100_000.0, 'jita_buy': 90_000.0, 'amarr_sell': 120_000.0,
                       'delve_sell': 130_000.0, 'delve_buy': 80_000.0}}


ROUTES = [{'origin': voc.JITA, 'dest': '7G-QIG', 'min_fee': 10e6, 'per_m3': 1000, 'collateral_pct': 1.0,
           'max_m3': 165_000}]


def test_buy_channels_price_instant_buys_inbound_courier_and_delve():
    s = Settings(use_sell_orders=False)
    ch = selling.buy_channels(PI, s, books(), SMARTFAB, '7G-QIG', ROUTES, local=True)
    courier = PI.volume(SMARTFAB) * 1000 + 100_000.0 * 0.01
    assert ch == {'jita': 100_000.0 + courier, 'local': 130_000.0}   # no inbound route from Amarr
    s.use_local = False
    assert 'local' not in selling.buy_channels(PI, s, books(), SMARTFAB, '7G-QIG', ROUTES, local=True)


def test_buy_orders_only_for_pilots_who_trade_with_orders():
    s = Settings(use_sell_orders=True, broker_fee_pct=3.0, use_local=False, use_amarr=False)
    ch = selling.buy_channels(PI, s, books(), SMARTFAB, '7G-QIG', ROUTES, local=True)
    assert abs(ch['jita_order'] - (90_000.0 * 1.03 + PI.volume(SMARTFAB) * 1000 + 92_700.0 * 0.01)) < 0.01


def test_self_haul_prices_the_goods_only():
    s = Settings(use_self_haul=True, use_local=False)
    ch = selling.buy_channels(PI, s, books(), SMARTFAB, 'Fictional system 1', [], local=False)
    assert ch == {'jita_self': 100_000.0, 'amarr_self': 120_000.0}


def test_buy_costs_list_every_market_and_respect_own_production_only():
    s = Settings()
    assert s.buy_inputs is True             # the maintainer's default: buy when it pays (#225)
    costs = selling.buy_costs(PI, s, books(), '7G-QIG', local=True)
    assert costs[SMARTFAB] == selling.buy_channels(PI, s, books(), SMARTFAB, '7G-QIG', voc.routes_cached(), True)
    assert P4 not in costs                  # only P1-P3 are bought
    s.buy_inputs = False
    assert selling.buy_costs(PI, s, books(), '7G-QIG', local=True) == {}


def test_buying_stays_within_what_the_market_can_supply():
    s, area, systems, chars = scenario()
    res = optimizer.plan(PI, s, area, systems, chars, {P4: 2_000_000.0}, METADATA['templates'], head_yield=3000,
                         buy=INPUT_COST, buy_cap={SMARTFAB: {'jita': 600.0}})
    bought = {r['type_id']: r['units_per_day'] for r in res['bought']}
    assert 0 < bought[SMARTFAB] <= 600.5
    assert bought[VACCINES] <= bought[SMARTFAB] + 0.5   # the recipe needs both in step, so no extra Vaccines


def test_buy_limits_use_a_modest_share_of_traded_volume_or_the_visible_sell_orders():
    from astracore.modules.pi.planner import demand
    history = {'jita': {SMARTFAB: {'avg_volume': 10_000}}, 'amarr': {SMARTFAB: {'avg_volume': 2_000}},
               'delve': {SMARTFAB: {'avg_volume': 1_000}}}
    book = {VACCINES: {'jita_sell_depth': [[100.0, 300], [101.0, 300]], 'delve_sell_depth': [[90.0, 400]]}}
    s = Settings()
    caps = demand.buy_limits(PI, s, book, history, local=True, days=10)
    share = demand.BUY_INPUT_SHARE
    assert caps[SMARTFAB] == {'jita': share * 10_000, 'amarr': share * 2_000, 'delve': share * 1_000}
    assert caps[VACCINES] == {'jita': 60.0, 'amarr': 0.0, 'delve': 40.0}   # visible units over 10 days
    assert P4 not in caps
    far = demand.buy_limits(PI, s, book, history, local=False, days=10)
    assert 'delve' not in far[SMARTFAB]


def test_each_market_supplies_only_its_own_share():
    # Delve is cheaper but trades little: the rest comes from Jita at Jita's price
    s, area, systems, chars = scenario()
    cost = {**INPUT_COST, SMARTFAB: {'local': 80_000.0, 'jita': 100_000.0}}
    res = optimizer.plan(PI, s, area, systems, chars, {P4: 2_000_000.0}, METADATA['templates'], head_yield=3000,
                         buy=cost, buy_cap={SMARTFAB: {'delve': 100.0, 'jita': 1e9}})
    row = next(r for r in res['bought'] if r['type_id'] == SMARTFAB)
    split = {src['channel']: src['units_per_day'] for src in row['sources']}
    assert split['local'] <= 100.5 and split['jita'] > 0
    assert abs(sum(split.values()) - row['units_per_day']) < 1
    assert 80_000 < row['isk_per_unit'] < 100_000


def test_settings_saved_before_the_buying_question_keep_their_wizard_position():
    from astracore.modules.pi.settings import BUY_STEP
    old = Settings.from_json(json.dumps({'guide_step': 8, 'answered': ['goal', 'sell']}))
    assert old.guide_step == 9 and old.buy_inputs is True
    early = Settings.from_json(json.dumps({'guide_step': BUY_STEP - 1}))
    assert early.guide_step == BUY_STEP - 1
    new = Settings.from_json(json.dumps({'guide_step': 8, 'buy_inputs': False}))
    assert new.guide_step == 8 and new.buy_inputs is False


def test_the_buying_question_sits_where_the_settings_migration_expects_it():
    import re
    from astracore.modules.pi.settings import BUY_STEP
    html = (Path(__file__).parents[1] / 'src/astracore/modules/pi/templates/pi/guide.html').read_text()
    steps = html[html.index('const STEPS = ['):html.index('const OPTIONAL_IDS')]
    ids = re.findall(r"^  \{id: '([a-z]+)'", steps, re.M)
    assert ids.index('buy') == BUY_STEP
    assert ids[BUY_STEP - 1] == 'tier' and ids[-1] == 'plan'


def test_buying_rounds_add_to_the_time_estimate():
    from astracore.modules.pi.planner import compare
    totals = {'colonies': 4, 'factories': 4, 'restarts_per_week': 0, 'systems': 1, 'm3_per_week': 0}
    s = Settings(cycle_days=1)
    plain = compare.effort_minutes(totals, s, 1)
    buying = compare.effort_minutes({**totals, 'buy_isk_per_day': 1e6}, s, 1)
    assert buying - plain == 7 * compare.MIN_PER_PURCHASE


def test_factory_rows_say_which_inputs_are_bought():
    res = solve(2_000_000.0)
    p4 = p4_rows(res)[0]
    assert p4['bought_per_day']['Smartfab Units'] == p4['in_per_day']['Smartfab Units']


def test_operate_lists_one_restock_round_of_bought_inputs(monkeypatch):
    from astracore.modules.pi import service
    monkeypatch.setattr(voc, 'routes_cached', lambda: ROUTES)
    res = solve(2_000_000.0)
    active = {'result': {**res, 'hub': '7G-QIG'}, 'settings': {'cycle_days': 2, 'input_budget_isk': 0}}
    ctx = {'pi': PI, 'books': {SMARTFAB: {'jita_sell': 100_000.0}, VACCINES: {'jita_sell': 90_000.0},
                               WATER: {'jita_sell': 400.0}}, 'area': None}
    out = service.restock_purchases(ctx, active)
    rows = {r['item']: r for r in out['rows']}
    smart = next(r for r in res['bought'] if r['type_id'] == SMARTFAB)
    assert rows['Smartfab Units']['qty'] == int(-(-smart['units_per_day'] * 2 // 1))
    assert out['cycle_days'] == 2 and 'Smartfab Units\t' in out['multibuy']
    assert out['capital_isk'] == res['totals']['capital_isk']
    assert service.restock_purchases(ctx, {'result': {**res, 'bought': []}, 'settings': {}}) is None
