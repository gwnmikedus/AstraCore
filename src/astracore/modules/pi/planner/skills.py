"""Market taxes and customs rates derived from your characters (skills, standings, ESI)
instead of hand-typed settings."""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

from ..settings import Settings

BASE_SALES_TAX = 7.5      # %, reduced 11% per Accounting level
BASE_BROKER_FEE = 3.0     # %, NPC stations
MIN_BROKER_FEE = 1.0
# Station owners of the market hubs, for the standings part of the broker fee.
HUB_OWNERS = {
    "jita": {"faction_id": 500001, "corporation_id": 1000035},    # Caldari State / Caldari Navy
    "amarr": {"faction_id": 500003, "corporation_id": 1000086},   # Amarr Empire / Emperor Family
}


def sales_tax(accounting: int) -> float:
    return round(BASE_SALES_TAX * (1 - 0.11 * max(0, min(5, accounting))), 3)


def broker_fee(broker_relations: int, faction_standing: float = 0.0, corp_standing: float = 0.0) -> float:
    fee = BASE_BROKER_FEE - 0.3 * max(0, min(5, broker_relations)) \
        - 0.03 * faction_standing - 0.02 * corp_standing
    return round(max(MIN_BROKER_FEE, fee), 3)


def _standing(ch: dict, kind: str, ident: int) -> float:
    for st in ch.get("standings") or []:
        if st.get("from_type") == kind and st.get("from_id") == ident:
            return float(st.get("standing", 0.0))
    return 0.0


def character_rates(ch: dict) -> dict:
    sk = ch.get("skills") or {}
    acc, br = int(sk.get("Accounting", 0)), int(sk.get("Broker Relations", 0))
    brokers = {hub: broker_fee(br, _standing(ch, "faction", o["faction_id"]), _standing(ch, "npc_corp", o["corporation_id"]))
               for hub, o in HUB_OWNERS.items()}
    return {"character_id": ch.get("character_id"), "name": ch.get("name"), "accounting": acc,
            "broker_relations": br, "sales_tax_pct": sales_tax(acc),
            "broker_fee_pct": round(min(brokers.values()), 3), "broker_by_hub": brokers}


def best_seller(characters: List[dict]) -> Optional[dict]:
    """The character who should do the selling: lowest sales tax, then lowest broker fee."""
    rates = [character_rates(c) for c in characters if c.get("skills")]
    if not rates:
        return None
    return min(rates, key=lambda r: (r["sales_tax_pct"], r["broker_fee_pct"]))


def apply(s: Settings, seller: Optional[dict]) -> Settings:
    """Settings with sales tax / broker fee taken from the seller's skills (when enabled)."""
    if not s.taxes_from_skills or not seller:
        return s
    out = copy.copy(s)
    out.sales_tax_pct = seller["sales_tax_pct"]
    out.broker_fee_pct = seller["broker_fee_pct"]
    return out


def for_character(s: Settings, ch: dict) -> Settings:
    """Settings for selling stock that one particular character holds."""
    return apply(s, character_rates(ch)) if ch.get("skills") else s


def customs_rates(characters: List[dict]) -> Dict[int, float]:
    """system_id -> export tax % for your alliance/corp, from customs offices ESI could read
    (needs a Director of the owning corporation). Empty when none are readable."""
    out: Dict[int, float] = {}
    for ch in characters:
        for o in ch.get("customs_offices") or []:
            if not o.get("system_id"):
                continue
            same_corp = o.get("owner_corporation_id") == ch.get("corporation_id")
            if same_corp:
                rate = o.get("corporation_tax_rate")
            elif o.get("allow_alliance_access"):
                rate = o.get("alliance_tax_rate")
            else:
                rate = o.get("neutral_standing_tax_rate")
            if rate is not None:
                out[int(o["system_id"])] = round(float(rate) * 100, 2)
    return out
