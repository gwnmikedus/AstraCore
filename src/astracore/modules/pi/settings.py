"""AstracorePI preferences: everything the planner can be tuned with.

Stored per profile in `module_settings` (module "pi"). A few instance-wide values
(VOC buyback terms, solver time limit) are admin settings: the admin edits them and
they override whatever a profile has stored.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import List, Optional

# Instance-wide values: only the admin profile may change them (kept in the `admin_settings` kv).
ADMIN_FIELDS = ("buyback_pct", "buyback_pct_p1", "solver_time_limit")


@dataclass
class Settings:
    """Everything the planner can be tuned with. Persisted as JSON in the DB."""

    # --- Space (step 2) ----------------------------------------------------------
    extra_area: str = ""                         # extra names (region/constellation/system)
    selected_constellations: List[int] = field(default_factory=list)
    hub_system: str = ""                         # drop-off / hub; empty = auto (prefers a VOC location)

    # --- Live sliders (step 3) ----------------------------------------------------
    effort: int = 30            # 0 = least effort ... 100 = max ISK
    max_tier: int = 4           # highest product tier allowed (1 = only sell P1)
    max_systems: int = 3        # 0 = unlimited
    max_jumps: int = 3          # from hub
    cycle_days: float = 3.0     # extractor program length
    per_planet: int = 1         # max of your colonies per planet
    cross_character: bool = False  # characters may supply each other's factories
    product_blacklist: List[str] = field(default_factory=list)

    # --- Turning products into ISK (live) ------------------------------------------
    use_buyback: bool = True         # VOC alliance buyback
    use_jita: bool = True            # VOC courier to Jita
    use_amarr: bool = True           # VOC courier to Amarr
    use_local: bool = True           # Delve buy orders
    use_sell_orders: bool = False    # list sell orders in Jita/Amarr (more ISK, more effort)
    ship_every_days: int = 7         # how often you ship / sell a batch

    # --- Wizard state (was browser localStorage) ----------------------------------
    hour_isk: float = -1.0          # what an hour of your time is worth; -1 = the goal's default
    guide_step: int = 0             # where the plan wizard was left
    answered: List[str] = field(default_factory=list)   # wizard questions the user has answered

    # --- Economics (settings page) ---------------------------------------------
    buyback_pct: float = 90.0        # VOC buyback, % of Jita buy for P2-P4 (appraisal 2026-10-10)
    buyback_pct_p1: float = 0.0      # VOC buyback refuses P1
    poco_tax_pct: float = 10.0       # fallback where your customs offices can't be read from ESI
    taxes_from_skills: bool = True   # sales tax / broker fee from the selling character's skills
    sales_tax_pct: float = 4.5       # used when taxes_from_skills is off
    broker_fee_pct: float = 3.0
    stack_yield_pct: float = 70.0    # yield of each extra colony extracting the same P0 on a planet
    head_yield_per_hour: float = 1000.0  # P0/hour/head at richness 1.0 on a 3-day cycle
    auto_calibrate: bool = True          # use real extractor data from ESI when available
    solver_time_limit: int = 6

    @classmethod
    def from_json(cls, raw: Optional[str]) -> "Settings":
        s = cls()
        if raw:
            data = json.loads(raw)
            for f in fields(cls):
                if f.name in data:
                    setattr(s, f.name, data[f.name])
        return s

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def update(self, data: dict) -> None:
        """Apply values from a JSON body or HTML form, coercing to each field's type."""
        bools = set(data.get("__bool_fields__", []))
        for f in fields(self):
            cur = getattr(self, f.name)
            if isinstance(cur, bool):
                if f.name in data and isinstance(data[f.name], bool):
                    setattr(self, f.name, data[f.name])
                elif f.name in bools or f.name in data:
                    setattr(self, f.name, f.name in data and data[f.name] not in ("", "0", "false", "off"))
            elif f.name in data:
                try:
                    self._set(f.name, cur, data[f.name])
                except (TypeError, ValueError):
                    continue   # a value that doesn't parse leaves the setting as it was

    def _set(self, name: str, cur, val) -> None:
        if isinstance(cur, list):
            if isinstance(val, str):
                val = [x.strip() for x in val.split(",") if x.strip()]
            if name == "selected_constellations":
                val = [int(x) for x in val]
            setattr(self, name, list(val))
        elif isinstance(cur, int):
            setattr(self, name, int(float(str(val or 0).replace(",", "."))))
        elif isinstance(cur, float):
            setattr(self, name, float(str(val or 0).replace(",", ".")))
        else:
            setattr(self, name, str(val))


def effort_weights(effort: int) -> dict:
    """Map the single effort slider (0 = least effort, 100 = max ISK) to penalty weights."""
    lazy = max(0.0, min(1.0, 1 - effort / 100.0)) ** 2
    return {
        "isk_per_m3": 400.0 * lazy,               # hauling
        "isk_per_system": 1_500_000.0 * lazy,      # each system to fly to (per day)
        "isk_per_factory": 2_000_000.0 * lazy,     # factory planets need restocking
    }
