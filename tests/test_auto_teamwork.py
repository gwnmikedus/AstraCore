"""Teamwork follows Up to P3/P4 until the pilot chooses it (#226): offline, fictional planets and prices."""
import json
from pathlib import Path

from astracore.modules.pi import service
from astracore.modules.pi.planner import economics as eco
from astracore.modules.pi.planner import optimizer
from astracore.modules.pi.settings import Settings, auto_teamwork
from astracore.modules.pi.static_data.sde_loader import PIData

from test_p4_chains import scenario as p4_scenario

METADATA = json.loads((Path(__file__).parent / 'fixtures/sterile_conduits_metadata.json').read_text())


def test_teamwork_turns_on_for_p3_and_p4_until_the_pilot_chooses():
    assert auto_teamwork(Settings(max_tier=3), 2) and auto_teamwork(Settings(max_tier=4), 5)
    assert not auto_teamwork(Settings(max_tier=2), 5)                          # P2 fits one character
    assert not auto_teamwork(Settings(max_tier=4), 1)                          # one character: nobody to trade with
    assert not auto_teamwork(Settings(max_tier=4, cross_character=True), 5)    # already on
    assert not auto_teamwork(Settings(max_tier=4, cross_character_set=True), 5)   # the pilot said no


def _ctx(teamwork_auto):
    pi, s, area, systems, chars, target, templates = p4_scenario()
    s.cross_character = False
    solve_s = Settings(**{**s.__dict__, 'cross_character': teamwork_auto, 'buy_inputs': False})
    return dict(pi=pi, s=solve_s, solve_s=solve_s, area=area, systems=systems, chars=chars, tpl=templates,
                overrides={}, head_yield=3000, books={}, books_at=1.0, history={}, history_at=None,
                dropoff='Fictional system 1', local=False, origin=None, origin_jumps=0, seller=None, measured={},
                manual_overrides={}, calibrated=None, values={target: 1e9}, buy={}, buy_cap={},
                teamwork_auto=teamwork_auto)


def test_a_plan_with_automatic_teamwork_says_so_and_how_to_turn_it_off():
    res = service.run_plan(_ctx(True))
    assert res['teamwork_auto'] and res['transfers']
    note = next(w for w in res['warnings'] if w['code'] == 'teamwork_auto')
    assert note['level'] == 'info' and note['steps'] == ['chain', 'tier']
    assert 'Change Teamwork to turn it off' in note['guided'] and 'transfer' in note['text']
    assert service.whatif_summary(res)['teamwork_auto'] is True


def test_no_teamwork_note_when_the_pilot_decided():
    res = service.run_plan(_ctx(False))
    assert not res.get('teamwork_auto')
    assert not any(w['code'] == 'teamwork_auto' for w in res['warnings'])


def test_step_margins_value_inputs_at_the_cheaper_of_buying_and_selling():
    pi = PIData.from_json(METADATA['pi'])
    p4, smart, vacc, water = METADATA['target'], 2351, 28974, 3645
    s = Settings()
    prices = {p4: 2_000_000.0, smart: 120_000.0, vacc: 100_000.0, water: 500.0}
    r = pi.recipe(p4)
    tax = eco.export_tax(pi, s, {p4: r.output_qty}) + eco.import_tax(pi, s, dict(r.inputs))
    own = optimizer.step_margins(pi, s, prices)['4']
    cost = 6 * 120_000 + 6 * 100_000 + 40 * 500
    assert own == {'product': 'Sterile Conduits', 'pct': round((2_000_000 - cost - tax) / cost * 100), 'buying': False}
    bought = optimizer.step_margins(pi, s, prices, {smart: {'jita': 90_000.0}})['4']
    cheaper = 6 * 90_000 + 6 * 100_000 + 40 * 500
    assert bought['pct'] == round((2_000_000 - cheaper - tax) / cheaper * 100) and bought['buying']


def test_tier_need_says_whether_the_plan_bought_and_traded():
    pi, s, area, systems, chars, target, templates = p4_scenario()
    need = optimizer.tier_need(pi, s, templates, [], {target: 1.0}, None)
    assert need['buying'] is False and need['teamwork'] is True and need['margins'] == {}
