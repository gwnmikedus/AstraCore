"""Loads PI schematics from the Fuzzwork SDE dump plus item names/volumes from ESI.

The result is cached in the kv table as `pi_data` so it's only built once.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

from .. import db
from ..config import DATA_DIR
from ..esi import public
from ..esi.client import ESIClient
from . import pi_rules

FUZZWORK = "https://www.fuzzwork.co.uk/dump/latest/csv/{}.csv"
SDE_DIR = DATA_DIR / "sde"
CACHE_KEY = "pi_data_v1"


@dataclass
class Schematic:
    id: int
    name: str
    cycle: int                       # seconds
    output: int                      # type id
    output_qty: int
    inputs: Dict[int, int]           # type id -> qty per cycle

    def per_hour_out(self) -> float:
        return self.output_qty * 3600 / self.cycle

    def per_hour_in(self) -> Dict[int, float]:
        return {t: q * 3600 / self.cycle for t, q in self.inputs.items()}


@dataclass
class PIData:
    items: Dict[int, dict]                       # type_id -> {name, tier, volume}
    schematics: Dict[int, Schematic]
    recipe_by_output: Dict[int, int] = field(default_factory=dict)
    p0_by_planet: Dict[str, List[int]] = field(default_factory=dict)
    by_name: Dict[str, int] = field(default_factory=dict)

    def name(self, tid: int) -> str:
        return self.items.get(tid, {}).get("name", str(tid))

    def tier(self, tid: int) -> int:
        return self.items.get(tid, {}).get("tier", -1)

    def volume(self, tid: int) -> float:
        return self.items.get(tid, {}).get("volume", 0.0)

    def recipe(self, out_tid: int) -> Optional[Schematic]:
        sid = self.recipe_by_output.get(out_tid)
        return self.schematics.get(sid) if sid is not None else None

    def of_tier(self, tier: int) -> List[int]:
        return sorted(t for t, i in self.items.items() if i["tier"] == tier)

    def to_json(self) -> dict:
        return {
            "items": {str(k): v for k, v in self.items.items()},
            "schematics": {str(s.id): dict(name=s.name, cycle=s.cycle, output=s.output,
                                           output_qty=s.output_qty,
                                           inputs={str(k): v for k, v in s.inputs.items()})
                           for s in self.schematics.values()},
            "p0_by_planet": self.p0_by_planet,
        }

    @classmethod
    def from_json(cls, d: dict) -> "PIData":
        items = {int(k): v for k, v in d["items"].items()}
        schems = {int(k): Schematic(int(k), v["name"], v["cycle"], v["output"], v["output_qty"],
                                    {int(a): b for a, b in v["inputs"].items()})
                  for k, v in d["schematics"].items()}
        data = cls(items=items, schematics=schems, p0_by_planet=d["p0_by_planet"])
        data._index()
        return data

    def _index(self) -> None:
        self.recipe_by_output = {s.output: s.id for s in self.schematics.values()}
        self.by_name = {v["name"].lower(): k for k, v in self.items.items()}


def _read_csv(text: str) -> List[dict]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


async def _download(name: str) -> str:
    SDE_DIR.mkdir(parents=True, exist_ok=True)
    path = SDE_DIR / f"{name}.csv"
    if path.exists():
        return path.read_text(encoding="utf-8-sig")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(FUZZWORK.format(name))
        r.raise_for_status()
    path.write_text(r.text, encoding="utf-8")
    return r.text.lstrip("﻿")


def build_from_rows(schem_rows: List[dict], map_rows: List[dict]) -> PIData:
    schematics: Dict[int, Schematic] = {}
    for r in schem_rows:
        sid = int(r["schematicID"])
        schematics[sid] = Schematic(sid, r["schematicName"], int(r["cycleTime"]), 0, 0, {})
    for r in map_rows:
        s = schematics.get(int(r["schematicID"]))
        if not s:
            continue
        tid, qty = int(r["typeID"]), int(r["quantity"])
        if r["isInput"] in ("1", "True", "true"):
            s.inputs[tid] = qty
        else:
            s.output, s.output_qty = tid, qty

    tiers: Dict[int, int] = {}
    for s in schematics.values():
        for t, q in s.inputs.items():
            if q >= 1000:  # P0 inputs are 3000 per cycle
                tiers[t] = 0
    changed = True
    while changed:
        changed = False
        for s in schematics.values():
            if all(t in tiers for t in s.inputs) and s.output not in tiers:
                tiers[s.output] = 1 + max(tiers[t] for t in s.inputs)
                changed = True
    items = {t: {"name": str(t), "tier": tier, "volume": pi_rules.DEFAULT_VOLUME[tier]}
             for t, tier in tiers.items()}
    data = PIData(items=items, schematics=schematics)
    data._index()
    return data


async def load(esi: ESIClient, force: bool = False) -> PIData:
    if not force:
        cached = db.kv_get(CACHE_KEY)
        if cached:
            return PIData.from_json(cached)
    schem_rows = _read_csv(await _download("planetSchematics"))
    map_rows = _read_csv(await _download("planetSchematicsTypeMap"))
    data = build_from_rows(schem_rows, map_rows)

    names = await public.ids_to_names(esi, data.items.keys())
    infos = await public.many(public.type_info(esi, t) for t in data.items)
    for tid, info in zip(list(data.items), infos):
        data.items[tid]["name"] = names.get(tid, info.get("name", str(tid)))
        vol = info.get("packaged_volume") or info.get("volume")
        if vol:
            data.items[tid]["volume"] = float(vol)
    data._index()
    data.p0_by_planet = {
        ptype: [data.by_name[n.lower()] for n in p0s if n.lower() in data.by_name]
        for ptype, p0s in pi_rules.P0_BY_PLANET.items()
    }
    db.kv_set(CACHE_KEY, data.to_json())
    return data


def cached() -> Optional[PIData]:
    raw = db.kv_get(CACHE_KEY)
    return PIData.from_json(raw) if raw else None
