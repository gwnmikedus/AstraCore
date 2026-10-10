"""Pickup route over the gate graph: nearest-neighbour tour from the hub."""
from __future__ import annotations

from typing import Dict, List

from ..intel.area import jumps_from


def pickup_route(area: dict, hub_id: int, system_ids: List[int]) -> dict:
    todo = [s for s in set(system_ids) if s != hub_id]
    dist_cache: Dict[int, Dict[int, int]] = {}

    def d(a: int, b: int) -> int:
        if a not in dist_cache:
            dist_cache[a] = jumps_from(area, a)
        return dist_cache[a].get(b, 99)

    order = [hub_id]
    total = 0
    cur = hub_id
    while todo:
        nxt = min(todo, key=lambda s: d(cur, s))
        total += d(cur, nxt)
        order.append(nxt)
        todo.remove(nxt)
        cur = nxt
    back = d(cur, hub_id) if cur != hub_id else 0
    names = [area["systems"][str(s)]["name"] for s in order]
    return {"order": names, "jumps_out": total, "jumps_back": back, "round_trip_jumps": total + back}
