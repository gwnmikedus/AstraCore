"""Work out which space the user's characters can use, straight from their data:

* sov space of every alliance the characters are in,
* the constellations where they already have colonies,
* plus anything the user adds by name.

Then pick a sensible default selection (best constellation + ones with colonies).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from astracore.esi import public
from astracore.esi.client import ESIClient
from . import area as area_mod

SPACE_KEY_PREFIX = "space:"


async def sources_for(esi: ESIClient, characters: List[dict], extra: str = "") -> Dict[str, List[str]]:
    """Names to resolve, grouped by why they're included."""
    alliances = sorted({c["alliance_name"] for c in characters if c.get("alliance_name")})
    colony_systems = sorted({col["solar_system_id"] for c in characters for col in c.get("colonies", [])
                             if col.get("solar_system_id")})
    colony_cons: List[str] = []
    if colony_systems:
        systems = await public.many(public.system(esi, s) for s in colony_systems)
        con_ids = {s["constellation_id"] for s in systems}
        names = await public.ids_to_names(esi, con_ids)
        colony_cons = sorted(names.values())
    extra_names = [x.strip() for x in extra.split(",") if x.strip()]
    return {"alliances": alliances, "colony_constellations": colony_cons, "extra": extra_names}


def query_for(sources: Dict[str, List[str]]) -> str:
    names = sources["alliances"] + sources["colony_constellations"] + sources["extra"]
    return ", ".join(dict.fromkeys(names))


async def load(esi: ESIClient, characters: List[dict], extra: str = "", force: bool = False) -> Optional[dict]:
    src = await sources_for(esi, characters, extra)
    query = query_for(src)
    if not query:
        return None
    area = None if force else area_mod.cached(query)
    if area is None or "region" not in next(iter(area["systems"].values()), {"region": ""}):
        area = await area_mod.resolve(esi, query, force=force)
    area["sources"] = src
    return area


def colony_systems(characters: List[dict]) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = defaultdict(list)
    for c in characters:
        for col in c.get("colonies", []):
            if col.get("solar_system_id"):
                out[col["solar_system_id"]].append(c["name"])
    return out


def grouped(area: dict, characters: List[dict], overrides: Optional[dict] = None) -> List[dict]:
    """Regions -> constellations -> systems, with scores and badges, best first."""
    colonies = colony_systems(characters)
    alliance_ids = {c.get("alliance_id") for c in characters if c.get("alliance_id")}
    regions: Dict[str, dict] = {}
    for s in area["systems"].values():
        r = regions.setdefault(s.get("region") or "?", {"name": s.get("region") or "?", "constellations": {}})
        con = r["constellations"].setdefault(s["constellation_id"], {
            "id": s["constellation_id"], "name": s["constellation"], "systems": [],
        })
        con["systems"].append({
            "system_id": s["system_id"], "name": s["name"], "security": s["security"],
            "types": area_mod.type_counts(s),
            "planets": sum(1 for p in s["planets"] if p["type"] not in ("Shattered", "Unknown")),
            "score": round(area_mod.system_score(s, overrides), 1),
            "yours": s.get("sov_alliance_id") in alliance_ids,
            "owner": s.get("sov_alliance", ""),
            "colonies": colonies.get(s["system_id"], []),
        })
    out = []
    for r in regions.values():
        cons = []
        for con in r["constellations"].values():
            con["systems"].sort(key=lambda x: -x["score"])
            top = [x["score"] for x in con["systems"][:4]]
            con["score"] = round(sum(top), 1)
            con["sec_min"] = min(x["security"] for x in con["systems"])
            con["sec_max"] = max(x["security"] for x in con["systems"])
            con["has_colonies"] = any(x["colonies"] for x in con["systems"])
            con["yours"] = sum(1 for x in con["systems"] if x["yours"])
            cons.append(con)
        cons.sort(key=lambda c: -c["score"])
        out.append({"name": r["name"], "constellations": cons})
    out.sort(key=lambda r: -max(c["score"] for c in r["constellations"]))
    return out


def default_selection(groups: List[dict]) -> List[int]:
    cons = [c for r in groups for c in r["constellations"]]
    if not cons:
        return []
    best = max(cons, key=lambda c: c["score"])
    sel = {best["id"]} | {c["id"] for c in cons if c["has_colonies"]}
    return sorted(sel)


def selected_systems(area: dict, constellation_ids: List[int]) -> Dict[int, dict]:
    want = set(constellation_ids)
    return {int(k): v for k, v in area["systems"].items() if v["constellation_id"] in want}
