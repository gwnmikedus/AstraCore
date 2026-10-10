"""Small economic helpers shared by setups and optimiser."""
from __future__ import annotations

from typing import Dict, Optional

from ..config import Settings
from ..static_data.pi_rules import POCO_BASE_VALUE
from ..static_data.sde_loader import PIData


def export_tax(pi: PIData, s: Settings, flows: Dict[int, float], rate_pct: Optional[float] = None) -> float:
    """ISK/day customs tax for items leaving a planet (rate_pct: that system's customs rate)."""
    rate = (s.poco_tax_pct if rate_pct is None else rate_pct) / 100.0
    return sum(q * POCO_BASE_VALUE.get(pi.tier(t), 0) * rate for t, q in flows.items())


def import_tax(pi: PIData, s: Settings, flows: Dict[int, float], rate_pct: Optional[float] = None) -> float:
    rate = (s.poco_tax_pct if rate_pct is None else rate_pct) / 100.0 / 2
    return sum(q * POCO_BASE_VALUE.get(pi.tier(t), 0) * rate for t, q in flows.items())


def m3(pi: PIData, flows: Dict[int, float]) -> float:
    return sum(q * pi.volume(t) for t, q in flows.items())
