"""Public (unauthenticated) ESI lookups: names, sov, systems, planets, gates, markets."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List

from .client import STATIC_TTL, ESIClient, ESIError


async def resolve_names(esi: ESIClient, names: List[str]) -> Dict[str, List[dict]]:
    names = [n for n in (x.strip() for x in names) if n]
    if not names:
        return {}
    return await esi.post("/universe/ids/", names, ttl=STATIC_TTL)


async def ids_to_names(esi: ESIClient, ids: Iterable[int]) -> Dict[int, str]:
    ids = sorted(set(int(i) for i in ids))
    out: Dict[int, str] = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        rows = await esi.post("/universe/names/", chunk, ttl=STATIC_TTL)
        out.update({r["id"]: r["name"] for r in rows})
    return out


async def sov_map(esi: ESIClient, force: bool = False) -> List[dict]:
    return await esi.get("/sovereignty/map/", ttl=3600, force=force)


async def system(esi: ESIClient, system_id: int) -> dict:
    return await esi.get(f"/universe/systems/{system_id}/", ttl=STATIC_TTL)


async def planet(esi: ESIClient, planet_id: int) -> dict:
    return await esi.get(f"/universe/planets/{planet_id}/", ttl=STATIC_TTL)


async def stargate(esi: ESIClient, gate_id: int) -> dict:
    return await esi.get(f"/universe/stargates/{gate_id}/", ttl=STATIC_TTL)


async def constellation(esi: ESIClient, cid: int) -> dict:
    return await esi.get(f"/universe/constellations/{cid}/", ttl=STATIC_TTL)


async def region(esi: ESIClient, rid: int) -> dict:
    return await esi.get(f"/universe/regions/{rid}/", ttl=STATIC_TTL)


async def type_info(esi: ESIClient, type_id: int) -> dict:
    return await esi.get(f"/universe/types/{type_id}/", ttl=STATIC_TTL)


async def market_prices(esi: ESIClient, force: bool = False) -> Dict[int, dict]:
    rows = await esi.get("/markets/prices/", ttl=3600, force=force)
    return {r["type_id"]: r for r in rows}


async def region_orders(esi: ESIClient, region_id: int, type_id: int, force: bool = False) -> List[dict]:
    try:
        return await esi.get(f"/markets/{region_id}/orders/",
                             params={"order_type": "all", "type_id": type_id},
                             ttl=1800, force=force)
    except ESIError:
        return []


async def many(coros: Iterable[Any]) -> List[Any]:
    return list(await asyncio.gather(*coros))
