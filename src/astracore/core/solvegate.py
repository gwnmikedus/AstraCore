"""Fair use of the Mac's CPU for heavy work (the PI optimiser runs CBC, a few seconds per solve).

* Global limit: at most `ASTRACORE_SOLVE_CONCURRENCY` (default 2) solves run at once.
* Per profile: one request in flight. A newer request of the same kind supersedes an older one that
  is still waiting (the older returns "superseded"; a solve already running finishes).
* Cache: results are keyed on (profile data stamp, settings), so Back/Next doesn't solve again.
* If no slot frees up within `wait_timeout` seconds the caller gets Busy: the page shows
  "Astracore is busy, your plan is queued" and retries.
"""
from __future__ import annotations

import asyncio
import json
from collections import OrderedDict, defaultdict
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Hashable, Optional, Tuple

from fastapi.concurrency import run_in_threadpool

from astracore import config


class Busy(Exception):
    """No solve slot freed up in time."""


class Superseded(Exception):
    """A newer request from the same profile replaced this one."""


class SolveGate:
    def __init__(self, concurrency: int = 2, wait_timeout: float = 45.0, cache_size: int = 400) -> None:
        self.concurrency = concurrency
        self.wait_timeout = wait_timeout
        self.cache_size = cache_size
        self._cache: "OrderedDict[Hashable, Any]" = OrderedDict()
        self._gen: Dict[Tuple[int, str], int] = defaultdict(int)
        self._loop_id: Optional[int] = None
        self._sem: Optional[asyncio.Semaphore] = None
        self._locks: Dict[int, asyncio.Lock] = {}
        self.running = 0
        self.waiting = 0

    def _bind(self) -> None:
        """asyncio primitives belong to one event loop; (re)create them for the running loop."""
        lid = id(asyncio.get_running_loop())
        if lid != self._loop_id:
            self._loop_id = lid
            self._sem = asyncio.Semaphore(self.concurrency)
            self._locks = {}

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
            yield
        finally:
            lock.release()

    # ---------------------------------------------------------------- global CPU slots
    async def run(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking solve in a worker thread once a global slot is free."""
        self._bind()
        self.waiting += 1
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self.wait_timeout)
        except asyncio.TimeoutError:
            raise Busy() from None
        finally:
            self.waiting -= 1
        self.running += 1
        try:
            return await run_in_threadpool(fn, *args, **kwargs)
        finally:
            self.running -= 1
            self._sem.release()

    async def cached(self, key: Hashable, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        res = await self.run(fn, *args, **kwargs)
        self._cache[key] = res
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return res

    def clear(self) -> None:
        self._cache.clear()


def cache_key(stamp: Any, settings_json: str, extra: Any = None) -> str:
    return json.dumps([stamp, json.loads(settings_json), extra], sort_keys=True, default=str)


GATE = SolveGate(concurrency=config.SOLVE_CONCURRENCY)
