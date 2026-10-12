"""Fair use of the Mac's CPU for heavy work (the PI optimiser runs CBC, about a second per solve).

* Global limit: at most `ASTRACORE_SOLVE_CONCURRENCY` solves run at once (default: half the CPU cores,
  2 to 4; see `config.default_solve_concurrency`).
* Per profile: one request in flight. A newer request of the same kind supersedes an older one that
  is still waiting (the older returns "superseded"; a solve already running finishes).
* Cache: results are keyed on (profile data stamp, settings), so Back/Next doesn't solve again. Two callers
  asking for the same key while it is being solved share that one solve.
* Background work (`warm`) only takes a slot nobody is waiting for and leaves `reserve` slots free, so it
  never delays a pilot's own request by more than the solve already running.
* `position(profile)`: how many other pilots' solves are ahead in the queue, and a rough wait, from the
  measured solve times.
* If no slot frees up within `wait_timeout` seconds the caller gets Busy: the page shows
  "Astracore is busy, your plan is queued" and retries.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import math
import time
from collections import Counter, OrderedDict, defaultdict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Hashable, Optional, Tuple

from fastapi.concurrency import run_in_threadpool

from astracore import config


class Busy(Exception):
    """No solve slot freed up in time."""


class Superseded(Exception):
    """A newer request from the same profile replaced this one."""


class Skipped(Exception):
    """Background work found the planner busy and didn't start."""


class SolveGate:
    def __init__(self, concurrency: int = 2, wait_timeout: float = 45.0, cache_size: int = 400) -> None:
        self.concurrency = concurrency
        self.wait_timeout = wait_timeout
        self.cache_size = cache_size
        self._cache: "OrderedDict[Hashable, Any]" = OrderedDict()
        self._gen: Dict[Tuple[int, str], int] = defaultdict(int)
        self._request: ContextVar[Optional[Tuple[Tuple[int, str], int]]] = ContextVar(
            "solve_request", default=None)
        self._loop_id: Optional[int] = None
        self._sem: Optional[asyncio.Semaphore] = None
        self._locks: Dict[int, asyncio.Lock] = {}
        self._inflight: Dict[Hashable, "asyncio.Future"] = {}
        self._tickets = itertools.count()
        self._queue: "OrderedDict[int, Optional[int]]" = OrderedDict()   # ticket -> profile waiting for a slot
        self._busy_by: Counter = Counter()                                # profile -> solves running
        self.solve_seconds = 1.5     # moving average of recent solves, for the queue estimate
        self.reserve = 1 if concurrency > 1 else 0   # slots background work leaves free for pilots
        self.running = 0
        self.waiting = 0

    def _bind(self) -> None:
        """asyncio primitives belong to one event loop; (re)create them for the running loop."""
        lid = id(asyncio.get_running_loop())
        if lid != self._loop_id:
            self._loop_id = lid
            self._sem = asyncio.Semaphore(self.concurrency)
            self._locks = {}
            self._inflight = {}
            self._queue.clear()
            self._busy_by.clear()

    # ---------------------------------------------------------------- per-profile request slot
    @asynccontextmanager
    async def request(self, profile_id: int, kind: str):
        """One request per profile at a time; a newer one of the same kind supersedes a waiting one."""
        self._bind()
        key = (profile_id, kind)
        self._gen[key] += 1
        mine = self._gen[key]
        lock = self._locks.setdefault(profile_id, asyncio.Lock())
        self.waiting += 1
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self.wait_timeout)
        except asyncio.TimeoutError:
            raise Busy() from None
        finally:
            self.waiting -= 1
        try:
            if self._gen[key] != mine:
                raise Superseded()
            token = self._request.set((key, mine))
            try:
                yield
            finally:
                self._request.reset(token)
        finally:
            lock.release()

    def _check_current(self) -> None:
        request = self._request.get()
        if request is not None:
            key, generation = request
            if self._gen[key] != generation:
                raise Superseded()

    def supersede(self, profile_id: int, kind: str) -> int:
        """Start a new generation of `kind` work for the profile (older work of that kind stops)."""
        self._gen[(profile_id, kind)] += 1
        return self._gen[(profile_id, kind)]

    def is_current(self, profile_id: int, kind: str, generation: int) -> bool:
        return self._gen[(profile_id, kind)] == generation

    # ---------------------------------------------------------------- global CPU slots
    async def run(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking solve in a worker thread once a global slot is free."""
        self._bind()
        self._check_current()
        request = self._request.get()
        profile = request[0][0] if request else None
        ticket = next(self._tickets)
        self._queue[ticket] = profile
        self.waiting += 1
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self.wait_timeout)
        except asyncio.TimeoutError:
            raise Busy() from None
        finally:
            self.waiting -= 1
            self._queue.pop(ticket, None)
        try:
            self._check_current()
            return await self._solve(profile, fn, *args, **kwargs)
        finally:
            self._sem.release()

    async def _solve(self, profile: Optional[int], fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """In a held slot: run `fn` in a worker thread and time it."""
        self.running += 1
        self._busy_by[profile] += 1
        started = time.monotonic()
        try:
            return await run_in_threadpool(fn, *args, **kwargs)
        finally:
            took = time.monotonic() - started
            self.solve_seconds = 0.8 * self.solve_seconds + 0.2 * min(took, 30.0)
            self.running -= 1
            self._busy_by[profile] -= 1
            if self._busy_by[profile] <= 0:
                del self._busy_by[profile]

    def idle(self) -> bool:
        """Nobody waits and more than `reserve` slots are free: background work may start a solve."""
        self._bind()
        return self.waiting == 0 and self._sem._value > self.reserve

    async def run_low(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Background work: runs only in a slot that is free right now (raises Skipped otherwise)."""
        if not self.idle():
            raise Skipped()
        await self._sem.acquire()     # a slot is free and nobody waits: this doesn't suspend
        try:
            return await self._solve(None, fn, *args, **kwargs)
        finally:
            self._sem.release()

    def position(self, profile_id: int) -> Optional[dict]:
        """Where the profile's first waiting solve stands: other pilots ahead and a rough wait in seconds.
        None while it has no solve waiting for a slot."""
        mine = next((t for t, p in self._queue.items() if p == profile_id), None)
        if mine is None:
            return None
        before = [p for t, p in self._queue.items() if t < mine]
        pilots = {p for p in before if p != profile_id} | {p for p in self._busy_by if p not in (profile_id, None)}
        solves = len(before) + self.running
        eta = math.ceil((solves / max(1, self.concurrency) + 1) * self.solve_seconds)
        return {"ahead": len(pilots), "solves": solves, "eta": eta}

    async def cached(self, key: Hashable, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        return await self._cached(key, self.run, fn, args, kwargs)

    async def warm(self, key: Hashable, fn: Callable, *args: Any, **kwargs: Any) -> bool:
        """Low priority: solve `key` into the cache if a slot is free. False if it was there already."""
        if key in self._cache or key in self._inflight:
            return False
        await self._cached(key, self.run_low, fn, args, kwargs)
        return True

    async def _cached(self, key: Hashable, runner: Callable, fn: Callable, args: tuple, kwargs: dict) -> Any:
        while True:
            self._check_current()
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            pending = self._inflight.get(key)
            if pending is None:
                break
            try:   # someone is solving exactly this: wait for their result instead of solving it twice
                return await asyncio.shield(pending)
            except asyncio.CancelledError:
                if not pending.cancelled():
                    raise          # this caller was cancelled
            except (Busy, Superseded, Skipped):
                pass               # that caller gave up before solving: solve it here
        self._bind()
        future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            res = await runner(fn, *args, **kwargs)
        except BaseException as e:
            if isinstance(e, asyncio.CancelledError):
                future.cancel()
            else:
                future.set_exception(e)
                future.exception()     # retrieved: no "never retrieved" warning when nobody shared it
            raise
        finally:
            if self._inflight.get(key) is future:
                del self._inflight[key]
        self._cache[key] = res
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        future.set_result(res)
        return res

    def clear(self) -> None:
        self._cache.clear()


def cache_key(stamp: Any, settings_json: str, extra: Any = None) -> str:
    return json.dumps([stamp, json.loads(settings_json), extra], sort_keys=True, default=str)


GATE = SolveGate(concurrency=config.SOLVE_CONCURRENCY)
