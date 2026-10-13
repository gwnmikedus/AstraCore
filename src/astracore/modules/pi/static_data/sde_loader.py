"""Loads PI schematics from the Fuzzwork SDE dump plus item names/volumes from ESI.

The two source tables and their derived data are published as one validated cache.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import time
import weakref
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

from astracore import db
from astracore.config import STATIC_DIR
from astracore.esi import public
from astracore.esi.client import ESIClient, ESIError
from . import pi_rules

FUZZWORK = "https://www.fuzzwork.co.uk/dump/latest/csv/{}.csv"
SDE_DIR = STATIC_DIR / "sde"
CACHE_KEY = "pi_data_v1"
CHECK_EVERY = 24 * 3600
RETRY_EVERY = 3600
TABLES = ("planetSchematics", "planetSchematicsTypeMap")
_refresh_locks = weakref.WeakKeyDictionary()
log = logging.getLogger("astracore")


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


async def _download(client: httpx.AsyncClient, name: str, previous: dict, force: bool) -> dict:
    headers = {}
    if not force and previous.get("text"):
        if previous.get("etag"):
            headers["If-None-Match"] = previous["etag"]
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = previous["last_modified"]
    response = await client.get(FUZZWORK.format(name), headers=headers)
    if response.status_code == 304:
        if not headers:
            raise ValueError("SDE returned 304 without a cached table")
        return previous
    response.raise_for_status()
    text = response.text.lstrip("﻿")
    return {"text": text, "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _validated(tables: dict) -> PIData:
    schems = _read_csv(tables[TABLES[0]]["text"])
    mappings = _read_csv(tables[TABLES[1]]["text"])
    if not schems or not mappings:
        raise ValueError("SDE tables are empty")
    ids = set()
    for row in schems:
        sid = int(row["schematicID"])
        if sid <= 0 or sid in ids or not row["schematicName"] or int(row["cycleTime"]) <= 0:
            raise ValueError("Invalid SDE schematic")
        ids.add(sid)
    seen, outputs, inputs = set(), set(), set()
    for row in mappings:
        sid, tid, qty = int(row["schematicID"]), int(row["typeID"]), int(row["quantity"])
        flag = row["isInput"]
        if (sid not in ids or tid <= 0 or qty <= 0 or (sid, tid) in seen
                or flag not in ("0", "1", "False", "True", "false", "true")):
            raise ValueError("Invalid SDE type mapping")
        seen.add((sid, tid))
        if flag in ("1", "True", "true"):
            inputs.add(sid)
        else:
            if sid in outputs:
                raise ValueError("Multiple outputs for an SDE schematic")
            outputs.add(sid)
    if inputs != ids or outputs != ids:
        raise ValueError("Incomplete SDE recipes")
    data = build_from_rows(schems, mappings)
    if any(s.output not in data.items or any(t not in data.items for t in s.inputs)
           for s in data.schematics.values()):
        raise ValueError("Unresolved SDE recipe tiers")
    return data


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


async def _enrich(esi: ESIClient, data: PIData) -> None:
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


async def load(esi: ESIClient, force: bool = False) -> PIData:
    loop = asyncio.get_running_loop()
    if loop not in _refresh_locks:
        _refresh_locks[loop] = asyncio.Lock()
    async with _refresh_locks[loop]:
        previous = db.kv_get(CACHE_KEY)
        source = (previous or {}).get("source") or {}
        now = time.time()
        if previous and not force and not _due(source, now):
            return PIData.from_json(previous)
        try:
            old_tables = source.get("tables") or {}
            async with httpx.AsyncClient(timeout=60) as client:
                tables = {name: await _download(client, name, old_tables.get(name) or {}, force)
                          for name in TABLES}
                data = _validated(tables)
                # Revalidate both small tables before publishing: latest/ may change between requests.
                # Sources without validators are compared by content on this second pass instead.
                for name in TABLES:
                    confirmed = await _download(client, name, tables[name], False)
                    if confirmed["sha256"] != tables[name]["sha256"]:
                        raise ValueError("SDE changed during refresh; keeping the previous snapshot")
            unchanged = previous and all(tables[n]["sha256"] == old_tables.get(n, {}).get("sha256")
                                         for n in TABLES)
            if unchanged:
                payload = dict(previous)
            else:
                await _enrich(esi, data)
                payload = data.to_json()
            derived = {k: v for k, v in payload.items() if k != "source"}
            content_id = hashlib.sha256(json.dumps(derived, sort_keys=True).encode("utf-8")).hexdigest()
            payload["source"] = {"url": FUZZWORK, "tables": tables, "checked_at": now, "content_id": content_id,
                                 "attempted_at": now, "loaded_at": source.get("loaded_at") if unchanged else now,
                                 "error": None}
            # One SQLite write publishes both source tables, provenance and derived recipes together.
            db.kv_set(CACHE_KEY, payload)
            return PIData.from_json(payload)
        except (httpx.HTTPError, ESIError, ValueError, KeyError, TypeError, csv.Error) as exc:
            if previous is None:
                # Older installs can have downloaded CSVs but no assembled cache yet.
                tables = {name: {"text": (SDE_DIR / f"{name}.csv").read_text(encoding="utf-8-sig")}
                          for name in TABLES if (SDE_DIR / f"{name}.csv").exists()}
                if len(tables) != len(TABLES):
                    raise
                data = _validated(tables)
                await _enrich(esi, data)
                previous = data.to_json()
            log.warning("PI SDE refresh failed; using last good recipes: %s", exc)
            previous["source"] = {**source, "attempted_at": now, "error": str(exc)}
            db.kv_set(CACHE_KEY, previous)
            return PIData.from_json(previous)


def source_info() -> dict:
    """Refresh/provenance for diagnostics; an old or failed source is never marked fresh."""
    source = (db.kv_get(CACHE_KEY) or {}).get("source") or {}
    return {k: v for k, v in source.items() if k != "tables"} | {
        "stale": bool(source.get("error")) or time.time() - source.get("checked_at", 0) >= CHECK_EVERY,
        "tables": {n: {k: v for k, v in table.items() if k != "text"}
                   for n, table in (source.get("tables") or {}).items()},
    }


def _due(source: dict, now: float) -> bool:
    wait = RETRY_EVERY if source.get("error") else CHECK_EVERY
    return now - source.get("attempted_at", 0) >= wait


def stamp() -> tuple:
    """Existing plan/comparison caches change on new recipes, or when a source check becomes due."""
    source = (db.kv_get(CACHE_KEY) or {}).get("source") or {}
    return source.get("content_id"), _due(source, time.time())


def cached() -> Optional[PIData]:
    raw = db.kv_get(CACHE_KEY)
    return PIData.from_json(raw) if raw else None
