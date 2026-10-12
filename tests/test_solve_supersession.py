"""Queued work is discarded when a newer request replaces its step, without starting CBC."""
import asyncio

from astracore.core import solvegate
from astracore.core.solvegate import SolveGate, Superseded


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), timeout=2)


def test_superseded_request_waiting_for_cpu_never_executes_and_releases_slots():
    gate = SolveGate(concurrency=1, wait_timeout=2)
    calls = []

    async def request(name):
        try:
            async with gate.request(1, 'whatif'):
                return await gate.cached(name, lambda: calls.append(name) or name)
        except Superseded:
            # The stale token must be reset in this same task before unrelated work runs.
            assert await gate.run(lambda: 'outside') == 'outside'
            return 'superseded'

    async def main():
        gate._bind()
        await gate._sem.acquire()
        old = asyncio.create_task(request('old-step'))
        await until(lambda: gate.waiting == 1)
        new = asyncio.create_task(request('new-step'))
        await until(lambda: gate._gen[(1, 'whatif')] == 2)
        gate._sem.release()
        assert await asyncio.gather(old, new) == ['superseded', 'new-step']
        assert gate.running == gate.waiting == 0 and gate._sem._value == 1
        assert 'old-step' not in gate._cache

    asyncio.run(main())
    assert calls == ['new-step']


def test_partly_completed_batch_keeps_completed_cache_and_drops_pending_cards(monkeypatch):
    gate = SolveGate(concurrency=1, wait_timeout=2)
    calls = []

    async def main():
        started, finish = asyncio.Event(), asyncio.Event()

        async def worker(fn, *args, **kwargs):
            name = fn()
            calls.append(name)
            if name == 'completed-card':
                started.set()
                await finish.wait()
            return name

        monkeypatch.setattr(solvegate, 'run_in_threadpool', worker)

        async def old_request():
            try:
                async with gate.request(1, 'whatif'):
                    return await asyncio.gather(
                        gate.cached('completed-card', lambda: 'completed-card'),
                        gate.cached('pending-card', lambda: 'pending-card'))
            except Superseded:
                return 'superseded'

        async def new_request():
            async with gate.request(1, 'whatif'):
                return await gate.cached('current-card', lambda: 'current-card')

        old = asyncio.create_task(old_request())
        await started.wait()
        await until(lambda: gate.waiting == 1)
        new = asyncio.create_task(new_request())
        await until(lambda: gate._gen[(1, 'whatif')] == 2)
        finish.set()
        assert await asyncio.gather(old, new) == ['superseded', 'current-card']
        assert gate._cache['completed-card'] == 'completed-card'
        assert 'pending-card' not in gate._cache
        async with gate.request(1, 'whatif'):
            assert await gate.cached('completed-card', lambda: 'duplicate-solve') == 'completed-card'
        assert gate.running == gate.waiting == 0 and gate._sem._value == 1

    asyncio.run(main())
    assert calls == ['completed-card', 'current-card']


def test_different_profile_or_request_kind_does_not_supersede_queued_work():
    gate = SolveGate(concurrency=1, wait_timeout=2)
    calls = []

    async def request(pid, kind):
        async with gate.request(pid, kind):
            return await gate.run(lambda: calls.append((pid, kind)))

    async def main():
        gate._bind()
        await gate._sem.acquire()
        first = asyncio.create_task(request(1, 'whatif'))
        await until(lambda: gate.waiting == 1)
        others = [asyncio.create_task(request(1, 'suggest')), asyncio.create_task(request(2, 'whatif'))]
        await until(lambda: gate._gen[(1, 'suggest')] == gate._gen[(2, 'whatif')] == 1)
        gate._sem.release()
        await asyncio.gather(first, *others)
        assert gate.running == gate.waiting == 0

    asyncio.run(main())
    assert set(calls) == {(1, 'whatif'), (1, 'suggest'), (2, 'whatif')}
