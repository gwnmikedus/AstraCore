"""DalShooth/EVE_PI_Templates integration.

Downloads the community in-game PI templates (JSON), parses their structure
counts, and lets the planner link each planned colony to the template file the
player should place in game. We never author templates ourselves.

Repo layout: `PlanetaryInteractionTemplates/Miner - 00 - <P1>.json` (P0 -> P1 miners
for nullsec), `Miner - LS - ...` (lowsec) and `Factory - <product>.json` (P2/P3/P4
factories fed by imported inputs).
"""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from collections import Counter
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx

from .. import db
from ..config import DATA_DIR
from ..esi import public
from ..esi.client import ESIClient

REPO = "DalShooth/EVE_PI_Templates"
REPO_URL = f"https://github.com/{REPO}"
TREE_API = f"https://api.github.com/repos/{REPO}/git/trees/HEAD?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
TEMPLATE_DIR = DATA_DIR / "dalshooth"
CACHE_KEY = "dalshooth_index_v1"


def _classify(type_name: str) -> str:
    n = type_name.lower()
    if "extractor control unit" in n:
        return "ecu"
    if "basic industry" in n:
        return "basic"
    if "advanced industry" in n:
        return "advanced"
    if "high-tech" in n:
        return "hightech"
    if "launchpad" in n:
        return "launchpad"
    if "storage" in n:
        return "storage"
    if "command center" in n:
        return "cc"
    return "other"


def _parse_name(path: str) -> dict:
    stem = path.rsplit("/", 1)[-1][:-5]
    parts = [p.strip() for p in stem.split(" - ")]
    kind = parts[0].lower()
    sec = None
    if kind == "miner" and len(parts) >= 3:
        sec = parts[1]                       # "00" or "LS"
        product_name = parts[-1]
    else:
        product_name = parts[-1]
    product_name = product_name.replace("Stuctures", "Structures")  # repo typo
    return {"kind": kind, "sec": sec, "product_name": product_name, "file": stem + ".json",
            "path": path}


async def _fetch_all() -> Dict[str, dict]:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "pi-planner"}) as c:
        r = await c.get(TREE_API)
        r.raise_for_status()
        paths = [t["path"] for t in r.json().get("tree", [])
                 if t["path"].endswith(".json") and t["path"].startswith("PlanetaryInteractionTemplates/")]

        async def get(path: str):
            local = TEMPLATE_DIR / path.rsplit("/", 1)[-1]
            if not local.exists():
                rr = await c.get(RAW + quote(path))
                rr.raise_for_status()
                local.write_bytes(rr.content)
            return path, json.loads(local.read_text(encoding="utf-8-sig"))

        results = await asyncio.gather(*[get(p) for p in paths], return_exceptions=True)
    return {p: d for res in results if not isinstance(res, Exception) for p, d in [res]}


async def load(esi: ESIClient, by_name: Dict[str, int], force: bool = False) -> List[dict]:
    """Return parsed template index (cached)."""
    if not force:
        cached = db.kv_get(CACHE_KEY)
        if cached:
            return cached
    raw = await _fetch_all()
    pin_types = sorted({p["T"] for d in raw.values() for p in d.get("P", [])})
    names = await public.ids_to_names(esi, pin_types) if pin_types else {}
    index = []
    for path, d in sorted(raw.items()):
        meta = _parse_name(path)
        counts: Counter = Counter()
        heads = 0
        products = Counter()
        for p in d.get("P", []):
            kind = _classify(names.get(p["T"], ""))
            counts[kind] += 1
            heads += int(p.get("H") or 0)
            if p.get("S") and kind in ("basic", "advanced", "hightech"):
                products[int(p["S"])] += 1
        product_id = by_name.get(meta["product_name"].lower())
        meta.update(
            comment=d.get("Cmt"), ccu_level=d.get("CmdCtrLv"), planet_type_id=d.get("Pln"),
            ecus=counts["ecu"], heads=heads, basic=counts["basic"], advanced=counts["advanced"],
            hightech=counts["hightech"], launchpads=counts["launchpad"], storage=counts["storage"],
            links=len(d.get("L", [])), product_id=product_id,
            factory_products={str(k): v for k, v in products.items()},
        )
        index.append(meta)
    db.kv_set(CACHE_KEY, index)
    return index


def cached() -> List[dict]:
    return db.kv_get(CACHE_KEY) or []


def find(index: List[dict], kind: str, product_id: int, security: Optional[float] = None) -> Optional[dict]:
    """Best template for a planned colony. Miners prefer 00 in nullsec, LS otherwise."""
    cands = [t for t in index if t["kind"] == kind and t["product_id"] == product_id]
    if not cands:
        return None
    if kind == "miner" and security is not None:
        want = "00" if security < 0 else "LS"
        cands.sort(key=lambda t: t["sec"] != want)
    return cands[0]


def zip_pack(files: List[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(set(files)):
            local = TEMPLATE_DIR / f
            if local.exists():
                z.write(local, f)
        z.writestr("README.txt", (
            "PI templates from https://github.com/DalShooth/EVE_PI_Templates\n"
            "Copy these .json files into Documents/EVE/PlanetaryInteractionTemplates\n"
            "(or OneDrive/Documents/EVE/PlanetaryInteractionTemplates), then refresh\n"
            "the templates menu in game.\n"))
    return buf.getvalue()


def file_url(t: dict) -> str:
    return f"{REPO_URL}/blob/main/{quote(t['path'])}"


