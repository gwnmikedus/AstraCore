"""Resolve a free-text area (alliance / region / constellation / systems) into
systems with planets and a gate graph, using only ESI."""
from __future__ import annotations

from collections import Counter, deque
from typing import Dict, List, Optional

from .. import db
from ..esi import public
from ..esi.client import ESIClient
from ..static_data.pi_rules import PLANET_TYPES
from . import richness

AREA_KEY = "area_v1:"


async def _system_ids_for(esi: ESIClient, query: str, force: bool) -> (List[int], List[str]):
    tokens = [t.strip() for t in query.split(",") if t.strip()]
    ids = await public.resolve_names(esi, tokens)
    system_ids: List[int] = []
    found: List[str] = []
    alliances = ids.get("alliances", [])
    if alliances:
        sov = await public.sov_map(esi, force=force)
        for a in alliances:
            sys_ids = [s["system_id"] for s in sov if s.get("alliance_id") == a["id"]]
            system_ids += sys_ids
            found.append(f"alliance {a['name']} ({len(sys_ids)} sov systems)")
    for r in ids.get("regions", []):
        reg = await public.region(esi, r["id"])
        cons = await public.many(public.constellation(esi, c) for c in reg["constellations"])
        n = 0
        for c in cons:
            system_ids += c["systems"]
            n += len(c["systems"])
        found.append(f"region {r['name']} ({n} systems)")
    for c in ids.get("constellations", []):
        con = await public.constellation(esi, c["id"])
        system_ids += con["systems"]
        found.append(f"constellation {c['name']} ({len(con['systems'])} systems)")
    for s in ids.get("systems", []):
        system_ids.append(s["id"])
        found.append(f"system {s['name']}")
    matched = {x["name"].lower() for v in ids.values() for x in v}
    missing = [t for t in tokens if t.lower() not in matched]
    if missing:
        found.append("not found: " + ", ".join(missing))
    return sorted(set(system_ids)), found


async def resolve(esi: ESIClient, query: str, force: bool = False) -> dict:
    system_ids, found = await _system_ids_for(esi, query, force)
    systems_raw = await public.many(public.system(esi, s) for s in system_ids)
    planet_ids = [p["planet_id"] for s in systems_raw for p in s.get("planets", [])]
    planets_raw = await public.many(public.planet(esi, p) for p in planet_ids)
    planet_by_id = {p["planet_id"]: p for p in planets_raw}
    gate_ids = [g for s in systems_raw for g in s.get("stargates", [])]
    gates_raw = await public.many(public.stargate(esi, g) for g in gate_ids)
    con_ids = {s["constellation_id"] for s in systems_raw}
    cons = await public.many(public.constellation(esi, c) for c in con_ids)
    con_region = {c["constellation_id"]: c["region_id"] for c in cons}
    sov = {r["system_id"]: r.get("alliance_id") for r in await public.sov_map(esi)}
    owner_ids = {sov[s] for s in system_ids if sov.get(s)}
    con_names = await public.ids_to_names(
        esi, set(con_ids) | set(con_region.values()) | owner_ids) if con_ids else {}

    in_area = set(system_ids)
    neighbours: Dict[int, set] = {s: set() for s in system_ids}
    outside_names: Dict[int, set] = {s: set() for s in system_ids}
    for g in gates_raw:
        a, b = g["system_id"], g["destination"]["system_id"]
        if a in in_area and b in in_area:
            neighbours[a].add(b)
            neighbours[b].add(a)
        elif a in in_area:
            outside_names[a].add(b)

    systems = {}
    for s in systems_raw:
        planets = []
        for p in s.get("planets", []):
            pr = planet_by_id.get(p["planet_id"])
            if not pr:
                continue
            ptype = PLANET_TYPES.get(pr["type_id"], "Unknown")
            planets.append({"planet_id": pr["planet_id"], "name": pr["name"], "type": ptype,
                            "type_id": pr["type_id"]})
        systems[str(s["system_id"])] = {
            "system_id": s["system_id"],
            "name": s["name"],
            "security": round(s.get("security_status", 0.0), 2),
            "constellation_id": s["constellation_id"],
            "constellation": con_names.get(s["constellation_id"], ""),
            "region_id": con_region.get(s["constellation_id"]),
            "region": con_names.get(con_region.get(s["constellation_id"]), ""),
            "sov_alliance_id": sov.get(s["system_id"]),
            "sov_alliance": con_names.get(sov.get(s["system_id"]), "") if sov.get(s["system_id"]) else "",
            "planets": planets,
            "neighbours": sorted(neighbours[s["system_id"]]),
            "exits": len(outside_names[s["system_id"]]),
        }
    area = {"query": query, "found": found, "systems": systems}
    db.kv_set(AREA_KEY + query.lower(), area)
    return area


def cached(query: str) -> Optional[dict]:
    return db.kv_get(AREA_KEY + query.lower())


def jumps_from(area: dict, start_id: int) -> Dict[int, int]:
    dist = {start_id: 0}
    q = deque([start_id])
    systems = area["systems"]
    while q:
        cur = q.popleft()
        for n in systems[str(cur)]["neighbours"]:
            if n not in dist:
                dist[n] = dist[cur] + 1
                q.append(n)
    return dist


def system_by_name(area: dict, name: str) -> Optional[dict]:
    for s in area["systems"].values():
        if s["name"].lower() == name.strip().lower():
            return s
    return None


def system_score(sys: dict, overrides: Optional[dict] = None) -> float:
    """How good a system is for PI: richness-weighted planets + type diversity."""
    pts = 0.0
    for p in sys["planets"]:
        if p["type"] in ("Shattered", "Unknown"):
            continue
        pts += richness.richness(p["planet_id"], sys["security"], overrides)
    diversity = len({p["type"] for p in sys["planets"] if p["type"] not in ("Shattered", "Unknown")})
    return pts + 1.5 * diversity


def suggest_hub(area: dict, overrides: Optional[dict] = None, radius: int = 1) -> Optional[dict]:
    best, best_score = None, -1.0
    for s in area["systems"].values():
        dist = jumps_from(area, s["system_id"])
        score = sum(system_score(area["systems"][str(o)], overrides) / (1 + d)
                    for o, d in dist.items() if d <= radius)
        if score > best_score:
            best, best_score = s, score
    return best


def type_counts(sys: dict) -> Dict[str, int]:
    return dict(Counter(p["type"] for p in sys["planets"]))
