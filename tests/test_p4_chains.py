"""Offline higher-tier regression using public SDE and DalShooth structure-count metadata."""
import json
from pathlib import Path

from astracore.modules.pi.planner import optimizer
from astracore.modules.pi.settings import Settings
from astracore.modules.pi.static_data.sde_loader import PIData


def scenario():
    metadata = json.loads((Path(__file__).parent / 'fixtures/sterile_conduits_metadata.json').read_text())
    pi = PIData.from_json(metadata['pi'])
    kinds = ['Barren', 'Temperate', 'Gas', 'Ice', 'Lava', 'Oceanic', 'Plasma', 'Storm']
    planets = [{'planet_id': 100 + i, 'name': f'Fictional planet {i}', 'type': kinds[i % 8]} for i in range(30)]
    systems = {i + 1: {'system_id': i + 1, 'name': f'Fictional system {i + 1}', 'security': -0.5,
                      'planets': planets[i * 10:(i + 1) * 10],
                      'neighbours': [j for j in range(1, 4) if j != i + 1]} for i in range(3)}
    area = {'systems': {str(k): v for k, v in systems.items()}}
    chars = [{'character_id': i + 1, 'name': f'Fictional pilot {i + 1}', 'slots': 6,
              'ccu_level': 5, 'colonies': []} for i in range(5)]
    s = Settings(max_tier=4, effort=100, hour_isk=0, cross_character=True, per_planet=1, cycle_days=1,
                 max_jumps=3, max_systems=3, hub_system='Fictional system 1')
    return pi, s, area, systems, chars, metadata['target'], metadata['templates']


def test_higher_tiers_offer_every_usable_factory_site_but_keep_p2_search_small():
    system = {'planets': [{'planet_id': i, 'type': kind} for i, kind in
                         enumerate(['Barren', 'Temperate', 'Gas', 'Lava', 'Shattered', 'Unknown'])]}
    assert optimizer._factory_planets(system, 2) == {1, 3}
    for tier in (3, 4):
        assert optimizer._factory_planets(system, tier) == {0, 1, 2, 3}


def test_self_supplied_p4_chain_fits_within_thirty_slots():
    pi, settings, area, systems, chars, target, templates = scenario()
    # Deliberately make this P4 valuable: this tests feasibility, not a market-profit promise.
    result = optimizer.plan(pi, settings, area, systems, chars, {target: 1e9}, templates, head_yield=3000)
    assert 'error' not in result
    p4 = [c for c in result['colonies'] if c['product_id'] == target]
    assert p4 and 0.02 <= p4[0]['utilisation'] <= 1
    assert result['totals']['colonies'] <= 30
    assert result['totals']['max_tier_used'] == 4
    assert {2, 3, 4} <= {c['tier'] for c in result['colonies']}
    assert sum(c['kind'] == 'factory' for c in result['colonies']) > 6
