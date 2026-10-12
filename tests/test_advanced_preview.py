"""Advanced experiments preserve confirmed wizard answers until explicit application."""
import copy

import pytest

from astracore import db
from astracore.modules.pi import service, store
from test_plan_save import plan_client, suggest, save  # noqa: F401
from test_core import browser, csrf, eve  # noqa: F401


def post(client, endpoint, **body):
    return client.post('/pi/api/' + endpoint, json=body, headers={'X-CSRF-Token': csrf(client)})


def test_preview_preserves_saved_answers_and_guided_snapshot(plan_client):
    client, pid, _, _, _ = plan_client
    s = store.load_settings(pid)
    s.answered = ['goal', 'cycle']
    s.guide_step = 4
    store.save_settings(pid, s)
    guided = suggest(client)
    original = store.load_settings(pid).to_json()
    preview = post(client, 'preview', settings={'effort': 100, 'cycle_days': 7, 'answered': [], 'guide_step': 0})
    assert preview.status_code == 200
    assert preview.json()['preview'] and 'result_id' not in preview.json()
    assert store.load_settings(pid).to_json() == original
    assert save(client, guided['result_id']).status_code == 200


def test_apply_uses_explicit_baseline_and_preserves_latest_navigation(plan_client, monkeypatch):
    client, pid, _, result, _ = plan_client
    preview = post(client, 'preview', settings={'effort': 100}).json()
    async def solve(pid, s):
        latest = store.load_settings(pid)
        latest.answered = ['goal', 'cycle']
        latest.guide_step = 5
        store.save_settings(pid, latest)
        return result
    monkeypatch.setattr(service, 'solve', solve)
    response = post(client, 'apply', baseline=preview['baseline'], settings={'effort': 100, 'answered': [], 'guide_step': 0})
    assert response.status_code == 200 and not response.json()['preview']
    s = store.load_settings(pid)
    assert s.effort == 100 and s.answered == ['goal', 'cycle'] and s.guide_step == 5
    assert save(client, response.json()['result_id']).status_code == 200


@pytest.mark.parametrize('mode', ['preview', 'apply'])
def test_changed_settings_during_solve_reject_stale_result(plan_client, monkeypatch, mode):
    client, pid, _, result, _ = plan_client
    baseline = store.plan_settings(store.load_settings(pid))
    async def solve(pid, s):
        latest = store.load_settings(pid)
        latest.cycle_days = 7
        store.save_settings(pid, latest)
        return result
    monkeypatch.setattr(service, 'solve', solve)
    response = post(client, mode, baseline=baseline, settings={'effort': 100})
    assert response.status_code == 409 and response.json()['stale']
    assert store.load_settings(pid).effort == baseline['effort']


def test_apply_rejects_changed_baseline_before_solving(plan_client):
    client, pid, _, _, calls = plan_client
    preview = post(client, 'preview', settings={'effort': 100}).json()
    s = store.load_settings(pid)
    s.cycle_days = 7
    store.save_settings(pid, s)
    assert post(client, 'apply', baseline=preview['baseline'], settings={'effort': 100}).status_code == 409
    assert len(calls) == 1
    assert post(client, 'apply', settings={'effort': 100}).status_code == 409


def test_alternatives_and_sensitivity_use_unsaved_preview_base(plan_client, monkeypatch):
    from astracore.modules.pi import routes
    client, pid, _, _, _ = plan_client
    seen = []
    async def context(pid, s, persist_default):
        seen.append((copy.deepcopy(s), persist_default))
        return {'solve_s': s, 'pi': None, 'area': None, 'systems': {}, 'chars': [], 'values': {}, 'tpl': None,
                'overrides': {}, 'head_yield': 1, 'calibrated': False}
    async def cached(*args):
        return []
    monkeypatch.setattr(service, 'planning_context', context)
    monkeypatch.setattr(routes.GATE, 'cached', cached)
    original = store.load_settings(pid).to_json()
    for mode in ['alternatives', 'sensitivity']:
        assert post(client, mode, base={'effort': 100, 'cycle_days': 7}).status_code == 200
    assert all(s.effort == 100 and s.cycle_days == 7 and not persist for s, persist in seen)
    assert store.load_settings(pid).to_json() == original
