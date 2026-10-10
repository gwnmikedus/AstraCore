"""Authenticated character data: PI skills, colonies, and everything needed to follow
products from planet to liquid ISK (assets, contracts, market orders, wallet)."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .. import db
from ..static_data import sde_loader, voc
from . import public, sso
from .client import ESIClient, ESIError

SKILL_IDS = {
    "Interplanetary Consolidation": 2495,
    "Command Center Upgrades": 2505,
    "Planetology": 2406,
    "Advanced Planetology": 2403,
    "Remote Sensing": 13279,
    "Accounting": 16622,
    "Broker Relations": 3446,
}
LOCATIONS_KEY = "locations_v1"
HISTORY_DAYS = 45


async def affiliation(esi: ESIClient, character_id: int) -> Dict:
    rows = await esi.post("/characters/affiliation/", [character_id], ttl=3600)
    row = rows[0] if rows else {}
    ids = [i for i in (row.get("corporation_id"), row.get("alliance_id")) if i]
    names = await public.ids_to_names(esi, ids) if ids else {}
    return {
        "corporation_id": row.get("corporation_id"),
        "corporation_name": names.get(row.get("corporation_id"), ""),
        "alliance_id": row.get("alliance_id"),
        "alliance_name": names.get(row.get("alliance_id"), "") if row.get("alliance_id") else "",
    }


def _recent(ts: Optional[str]) -> bool:
    if not ts:
        return True
    try:
        when = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return when > datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)


async def _safe(coro, default):
    try:
        return await coro
    except ESIError:
        return default


async def resolve_locations(esi: ESIClient, token: str, ids: List[int]) -> Dict[int, dict]:
    """Station / structure id -> {name, system_id, system}. Cached across characters."""
    known = {int(k): v for k, v in (db.kv_get(LOCATIONS_KEY) or {}).items()}
    todo = [i for i in set(ids) if i not in known]
    for lid in todo:
        info = None
        if 60_000_000 <= lid < 64_000_000:
            st = await _safe(esi.get(f"/universe/stations/{lid}/", ttl=30 * 86400), None)
            if st:
                info = {"name": st["name"], "system_id": st["system_id"]}
        elif lid > 1_000_000_000_000:
            st = await _safe(esi.get(f"/universe/structures/{lid}/", token=token, ttl=7 * 86400), None)
            if st:
                info = {"name": st["name"], "system_id": st["solar_system_id"]}
        elif 30_000_000 <= lid < 33_000_000:
            info = {"name": "In space", "system_id": lid}
        if info:
            sysn = await public.ids_to_names(esi, [info["system_id"]])
            info["system"] = sysn.get(info["system_id"], "")
        known[lid] = info or {"name": f"Location {lid}", "system_id": None, "system": ""}
    db.kv_set(LOCATIONS_KEY, {str(k): v for k, v in known.items()})
    return {i: known[i] for i in ids if i in known}


def locations() -> Dict[int, dict]:
    return {int(k): v for k, v in (db.kv_get(LOCATIONS_KEY) or {}).items()}


async def sync_character(esi: ESIClient, character_id: int) -> Dict:
    token = await sso.access_token(character_id)
    if not token:
        raise RuntimeError("No token for character; log in again.")
    cid = character_id
    pi = sde_loader.cached()
    pi_types = {t for t in pi.items} if pi else set()

    skills_raw = await esi.get(f"/characters/{cid}/skills/", token=token, force=True)
    levels = {s["skill_id"]: s.get("active_skill_level", s.get("trained_skill_level", 0))
              for s in skills_raw.get("skills", [])}
    skills = {name: int(levels.get(sid, 0)) for name, sid in SKILL_IDS.items()}

    colonies_raw: List[dict] = await esi.get(f"/characters/{cid}/planets/", token=token, force=True)
    details = await asyncio.gather(*[
        esi.get(f"/characters/{cid}/planets/{c['planet_id']}/", token=token, force=True)
        for c in colonies_raw
    ], return_exceptions=True)
    colonies = []
    for col, det in zip(colonies_raw, details):
        col = dict(col)
        if not isinstance(det, Exception):
            col["pins"] = det.get("pins", [])
        colonies.append(col)

    extra: Dict = {}
    # --- assets: PI products wherever they are (top-level location resolved) ------
    assets_raw = await _safe(esi.get(f"/characters/{cid}/assets/", token=token, force=True), None)
    if assets_raw is not None:
        by_item = {a["item_id"]: a for a in assets_raw}

        def top(a):
            seen = 0
            while a.get("location_type") == "item" and a["location_id"] in by_item and seen < 10:
                a = by_item[a["location_id"]]
                seen += 1
            return a["location_id"]
        assets = [{"type_id": a["type_id"], "qty": a["quantity"], "location_id": top(a),
                   "flag": a.get("location_flag")} for a in assets_raw if a["type_id"] in pi_types]
        await resolve_locations(esi, token, [a["location_id"] for a in assets])
        extra["assets"] = assets

    # --- contracts (keep recent ones; items for VOC / PI-relevant ones) ------------------
    contracts_raw = await _safe(esi.get(f"/characters/{cid}/contracts/", token=token, force=True), None)
    if contracts_raw is not None:
        contracts = []
        for c in contracts_raw:
            if c.get("type") not in ("courier", "item_exchange") or not _recent(c.get("date_issued")):
                continue
            row = {k: c.get(k) for k in ("contract_id", "type", "status", "assignee_id", "acceptor_id",
                                         "issuer_id", "price", "reward", "collateral", "volume",
                                         "start_location_id", "end_location_id", "date_issued",
                                         "date_accepted", "date_completed", "date_expired", "title")}
            row["voc"] = c.get("assignee_id") == voc.CORP_ID or c.get("acceptor_id") == voc.CORP_ID
            if row["voc"] or c.get("type") == "item_exchange":
                items = await _safe(esi.get(f"/characters/{cid}/contracts/{c['contract_id']}/items/",
                                            token=token, ttl=86400), [])
                row["items"] = [{"type_id": i["type_id"], "qty": i["quantity"]} for i in items
                                if i.get("is_included", True)]
                row["pi"] = any(i["type_id"] in pi_types for i in row["items"])
            contracts.append(row)
        await resolve_locations(esi, token, [x for c in contracts for x in
                                             (c["start_location_id"], c["end_location_id"]) if x])
        extra["contracts"] = contracts

    # --- market orders -------------------------------------------------------------------------
    orders_raw = await _safe(esi.get(f"/characters/{cid}/orders/", token=token, force=True), None)
    if orders_raw is not None:
        extra["orders"] = [{k: o.get(k) for k in ("order_id", "type_id", "price", "volume_remain",
                                                   "volume_total", "location_id", "region_id", "issued",
                                                   "is_buy_order", "duration")}
                           for o in orders_raw if o["type_id"] in pi_types]
        await resolve_locations(esi, token, [o["location_id"] for o in extra["orders"]])

    # --- wallet: balance + ISK that came in from PI sales / buybacks -------------------------
    balance = await _safe(esi.get(f"/characters/{cid}/wallet/", token=token, force=True), None)
    if balance is not None:
        tx = await _safe(esi.get(f"/characters/{cid}/wallet/transactions/", token=token, force=True), [])
        journal = await _safe(esi.get(f"/characters/{cid}/wallet/journal/", token=token, force=True), [])
        extra["wallet"] = {
            "balance": balance,
            "sales": [{"date": t["date"], "type_id": t["type_id"], "qty": t["quantity"],
                       "unit_price": t["unit_price"], "location_id": t["location_id"]}
                      for t in tx if not t.get("is_buy") and t["type_id"] in pi_types and _recent(t["date"])],
            "journal": [{"date": j["date"], "ref_type": j["ref_type"], "amount": j.get("amount", 0.0),
                         "context_id": j.get("context_id"), "description": j.get("description", "")}
                        for j in journal if _recent(j["date"]) and j["ref_type"] in (
                            "contract_price", "contract_reward", "contract_collateral",
                            "contract_brokers_fee", "contract_price_payment_corp",
                            "market_transaction", "transaction_tax", "brokers_fee",
                            "planetary_export_tax", "planetary_import_tax")],
        }

    # --- standings (broker fee) and customs offices the corporation owns (needs Director) ------
    standings = await _safe(esi.get(f"/characters/{cid}/standings/", token=token, ttl=86400), None)
    if standings is not None:
        extra["standings"] = standings

    aff = await affiliation(esi, cid)
    if aff.get("corporation_id"):
        offices = await _safe(esi.get(f"/corporations/{aff['corporation_id']}/customs_offices/",
                                      token=token, ttl=86400), None)
        if offices is not None:
            extra["customs_offices"] = [{**o, "owner_corporation_id": aff["corporation_id"]} for o in offices]
    db.upsert_character(
        cid, db_name(cid), "esi",
        skills=skills, colonies=colonies, synced_at=time.time(),
        slots=1 + skills["Interplanetary Consolidation"],
        ccu_level=skills["Command Center Upgrades"],
        **aff, **extra,
    )
    return {"skills": skills, "colonies": colonies, **extra}


def db_name(character_id: int) -> str:
    for c in db.list_characters():
        if c["character_id"] == character_id:
            return c["name"]
    return str(character_id)
