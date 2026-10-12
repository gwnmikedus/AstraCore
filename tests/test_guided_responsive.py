"""The guided setup stays responsive with many pilots (#85): CPU-based solve slots, shared solves, background
warming of the next question that never delays a pilot, queue positions and answer cards streamed one by one."""
import asyncio
import json
import time

import pytest

import astracore.app  # noqa: F401 - imported before any asyncio.run(): Python 3.9 creates module-level locks
from astracore import config
from astracore.core import solvegate
from astracore.core.solvegate import SolveGate, Skipped, Superseded
from astracore.modules.pi import routes, service
from astracore.modules.pi.settings import Settings

from test_core import browser, csrf, eve, new_id, sso_login  # noqa: F401


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), timeout=2)


# ----------------------------------------------------------------------------- solve slots
@pytest.mark.parametrize('cpus, slots', [(None, 2), (1, 2), (2, 2), (4, 2), (6, 3), (8, 4), (16, 4), (64, 4)])
def test_default_concurrency_is_half_the_cores_between_two_and_four(cpus, slots):
    assert config.default_solve_concurrency(cpus) == slots


def test_concurrency_setting_overrides_the_default():
    assert config.solve_concurrency('', 16) == 4
    assert config.solve_concurrency('  ', 2) == 2
    assert config.solve_concurrency('6', 2) == 6
    assert config.solve_concurrency('0', 16) == 1


# ----------------------------------------------------------------------------- the gate
def test_two_callers_of_the_same_plan_share_one_solve():
    gate = SolveGate(concurrency=2, wait_timeout=2)
    calls = []

    def solve():
        calls.append(1)
        time.sleep(0.05)
        return 'plan'

    async def main():
        return await asyncio.gather(gate.cached('k', solve), gate.cached('k', solve))

    assert asyncio.run(main()) == ['plan', 'plan']
    assert calls == [1] and gate._inflight == {} and gate.running == 0


def test_a_shared_solve_whose_owner_was_superseded_is_solved_by_the_other_caller():
    gate = SolveGate(concurrency=1, wait_timeout=2)
    calls = []

    async def main():
        gate._bind()
        await gate._sem.acquire()                      # the planner is full: both wait

        async def owner():
            try:
                async with gate.request(1, 'whatif'):
                    return await gate.cached('k', lambda: calls.append('owner') or 'plan')
            except Superseded:
                return 'superseded'

        first = asyncio.create_task(owner())
        await until(lambda: 'k' in gate._inflight)
        joiner = asyncio.create_task(gate.cached('k', lambda: calls.append('joiner') or 'plan'))
        await asyncio.sleep(0)
        gate.supersede(1, 'whatif')                    # the owner's pilot moved on
        gate._sem.release()
        return await asyncio.gather(first, joiner)

    assert asyncio.run(main()) == ['superseded', 'plan']
    assert calls == ['joiner']


def test_background_work_leaves_a_slot_free_and_never_jumps_the_queue():
    gate = SolveGate(concurrency=2, wait_timeout=2)
    calls = []

    async def main():
        gate._bind()
        assert gate.idle()
        assert await gate.warm('a', lambda: calls.append('a') or 'A') is True
        assert await gate.warm('a', lambda: calls.append('again')) is False    # cached: nothing to do
        await gate._sem.acquire()                      # one pilot solving: the last slot is the reserve
        assert not gate.idle()
        with pytest.raises(Skipped):
            await gate.warm('b', lambda: calls.append('b'))
        gate._sem.release()
        gate.waiting = 1                               # a pilot waiting (for any slot or lock)
        with pytest.raises(Skipped):
            await gate.warm('c', lambda: calls.append('c'))
        gate.waiting = 0
        assert 'b' not in gate._inflight and 'c' not in gate._inflight

    asyncio.run(main())
    assert calls == ['a']


def test_single_slot_planner_still_warms_when_nobody_waits():
    gate = SolveGate(concurrency=1)
    assert gate.reserve == 0
    assert asyncio.run(gate.warm('k', lambda: 'plan')) is True


def test_queue_position_counts_other_pilots_ahead_and_estimates_the_wait(monkeypatch):
    gate = SolveGate(concurrency=1, wait_timeout=2)
    gate.solve_seconds = 2.0

    async def main():
        started, finish = asyncio.Event(), asyncio.Event()

        async def worker(fn, *a, **k):
            started.set()
            await finish.wait()
            return fn()

        monkeypatch.setattr(solvegate, 'run_in_threadpool', worker)

        async def pilot(pid):
            async with gate.request(pid, 'whatif'):
                return await gate.run(lambda: pid)

        tasks = [asyncio.create_task(pilot(1))]
        await started.wait()
        tasks += [asyncio.create_task(pilot(2)), asyncio.create_task(pilot(3))]
        await until(lambda: len(gate._queue) == 2)
        assert gate.position(1) is None                       # solving, not waiting
        assert gate.position(2) == {'ahead': 1, 'solves': 1, 'eta': 4}
        assert gate.position(3) == {'ahead': 2, 'solves': 2, 'eta': 6}
        assert gate.position(99) is None
        finish.set()
        assert await asyncio.gather(*tasks) == [1, 2, 3]
        assert not gate._queue and not gate._busy_by

    asyncio.run(main())


# ----------------------------------------------------------------------------- warming the next question
@pytest.fixture
def warm_gate(monkeypatch):
    gate = SolveGate(concurrency=2, wait_timeout=2)
    solved = []

    async def context(pid, s, persist_default):
        assert persist_default is False
        return {'s': s}

    def run_plan(ctx):
        solved.append(ctx['s'].cycle_days)
        return {'cycle_days': ctx['s'].cycle_days}

    monkeypatch.setattr(routes, 'GATE', gate)
    monkeypatch.setattr(service, 'planning_context', context)
    monkeypatch.setattr(service, 'run_plan', run_plan)
    monkeypatch.setattr(service, 'plan_key', lambda pid, s: f'{pid}:{int(s.cycle_days)}')
    monkeypatch.setattr(routes, 'PREFETCH_POLL', 0.01)
    return gate, solved


OPTIONS = [{'id': d, 'patch': {'cycle_days': d}} for d in (1, 2, 3)]


def test_prefetch_plans_the_next_cards_into_the_shared_cache(warm_gate):
    gate, solved = warm_gate

    async def main():
        await routes._prefetch(7, Settings(), OPTIONS, gate.supersede(7, 'prefetch'))

    asyncio.run(main())
    assert solved == [1, 2, 3]
    assert set(gate._cache) == {'7:1', '7:2', '7:3'}


def test_superseded_prefetch_does_not_solve(warm_gate):
    gate, solved = warm_gate

    async def main():
        old = gate.supersede(7, 'prefetch')
        gate.supersede(7, 'prefetch')                  # the pilot picked another answer meanwhile
        await routes._prefetch(7, Settings(), OPTIONS, old)

    asyncio.run(main())
    assert solved == [] and not gate._cache


def test_prefetch_stops_between_cards_when_a_newer_one_arrives(warm_gate, monkeypatch):
    gate, solved = warm_gate

    def run_plan(ctx):
        solved.append(ctx['s'].cycle_days)
        gate.supersede(7, 'prefetch')
        return {}

    monkeypatch.setattr(service, 'run_plan', run_plan)

    async def main():
        await routes._prefetch(7, Settings(), OPTIONS, gate.supersede(7, 'prefetch'))

    asyncio.run(main())
    assert solved == [1]


def test_prefetch_waits_for_pilots_and_gives_up_on_a_busy_planner(warm_gate, monkeypatch):
    gate, solved = warm_gate
    monkeypatch.setattr(routes, 'PREFETCH_PATIENCE', 0.05)

    async def main():
        gate._bind()
        gate.waiting = 1                               # pilots are queued the whole time
        started = time.monotonic()
        await routes._prefetch(7, Settings(), OPTIONS, gate.supersede(7, 'prefetch'))
        return time.monotonic() - started

    assert asyncio.run(main()) < 1
    assert solved == []


def test_prefetch_errors_stay_in_the_background(warm_gate, monkeypatch):
    gate, _ = warm_gate

    async def broken(pid, s, persist_default):
        raise RuntimeError('ESI down')

    monkeypatch.setattr(service, 'planning_context', broken)
    asyncio.run(routes._prefetch(7, Settings(), OPTIONS, gate.supersede(7, 'prefetch')))


# ----------------------------------------------------------------------------- the endpoint
@pytest.fixture
def pilot(browser, eve):  # noqa: F811
    client = browser()
    sso_login(client, eve, new_id(), 'Fictional Streaming Pilot')
    return client, {'X-CSRF-Token': csrf(client)}


def lines(response):
    return [json.loads(x) for x in response.text.splitlines() if x.strip()]


def test_prefetch_request_returns_at_once_without_the_profile_slot(pilot, monkeypatch):
    client, headers = pilot
    seen = []

    async def prefetch(pid, base, options, generation):
        seen.append((base.cycle_days, [o['id'] for o in options], routes.GATE.is_current(pid, 'prefetch', generation)))

    monkeypatch.setattr(routes, '_prefetch', prefetch)
    r = client.post('/pi/api/whatif', json={'base': {'cycle_days': 2}, 'options': OPTIONS, 'prefetch': True},
                    headers=headers)
    assert r.status_code == 202 and r.json() == {'queued': 3}
    deadline = time.monotonic() + 2
    while not seen and time.monotonic() < deadline:    # it runs in the background, after the reply
        time.sleep(0.01)
    assert seen == [(2, [1, 2, 3], True)]


def test_streamed_cards_arrive_one_by_one_then_done(pilot, monkeypatch):
    client, headers = pilot
    order = []

    async def card(pid, base, opt):
        await asyncio.sleep({1: 0.06, 2: 0.0, 3: 0.03}[opt['id']])
        order.append(opt['id'])
        return {'id': opt['id'], 'totals': {'isk_per_day': opt['id']}}

    monkeypatch.setattr(routes, '_whatif_card', card)
    r = client.post('/pi/api/whatif', json={'base': {}, 'options': OPTIONS, 'stream': True}, headers=headers)
    assert r.status_code == 200 and r.headers['content-type'].startswith('application/x-ndjson')
    events = lines(r)
    assert [e['card']['id'] for e in events if 'card' in e] == order == [2, 3, 1]
    assert events[-1] == {'done': True}


def test_streamed_comparison_reports_queue_position_while_waiting(pilot, monkeypatch):
    client, headers = pilot
    monkeypatch.setattr(routes, 'QUEUE_UPDATE', 0.01)
    waiting = {'now': True}
    monkeypatch.setattr(routes.GATE, 'position',
                        lambda pid: {'ahead': 2, 'solves': 3, 'eta': 9} if waiting['now'] else None)

    async def card(pid, base, opt):
        await asyncio.sleep(0.08)
        waiting['now'] = False
        return {'id': opt['id']}

    monkeypatch.setattr(routes, '_whatif_card', card)
    events = lines(client.post('/pi/api/whatif', json={'base': {}, 'options': OPTIONS[:1], 'stream': True},
                               headers=headers))
    assert events[0] == {'queue': {'ahead': 2, 'solves': 3, 'eta': 9}}
    assert events.count({'queue': {'ahead': 2, 'solves': 3, 'eta': 9}}) == 1    # only changes are sent
    assert {'queue': {'ahead': 0, 'solves': 0, 'eta': 0}} in events             # and the all-clear
    assert events[-2:] == [{'card': {'id': 1}}, {'done': True}]


def test_streamed_comparison_ends_superseded_or_busy(pilot, monkeypatch):
    client, headers = pilot
    for error, final in [(Superseded, {'superseded': True}), (solvegate.Busy, {'busy': True, 'retry_after': 3})]:
        async def card(pid, base, opt, error=error):
            raise error()
        monkeypatch.setattr(routes, '_whatif_card', card)
        events = lines(client.post('/pi/api/whatif', json={'base': {}, 'options': OPTIONS, 'stream': True},
                                   headers=headers))
        assert events == [final]


def test_list_comparison_is_unchanged(pilot, monkeypatch):
    client, headers = pilot

    async def card(pid, base, opt):
        return {'id': opt['id']}

    monkeypatch.setattr(routes, '_whatif_card', card)
    r = client.post('/pi/api/whatif', json={'base': {}, 'options': OPTIONS}, headers=headers)
    assert r.status_code == 200 and r.json() == [{'id': 1}, {'id': 2}, {'id': 3}]
