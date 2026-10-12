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
# Wizard bookkeeping: saved with the settings, but no plan depends on it.
UI_FIELDS = ("guide_step", "answered")
# Server-side limits for free text a profile can store (issue #92): generous for real use, small enough
# that a crafted request can't fill the database. Longer values are cut, extra list entries dropped.
TEXT_LIMITS = {"extra_area": 500, "hub_system": 100}
TEXT_MAX = 200          # any other text field
LIST_MAX = 200          # entries in a list setting (constellations, excluded products, answered questions)
LIST_ITEM_MAX = 100     # characters per text entry


@dataclass
class Settings:
    """Everything the planner can be tuned with. Persisted as JSON in the DB."""

    # --- Space (step 2) ----------------------------------------------------------
    extra_area: str = ""                         # extra names (region/constellation/system)
    selected_constellations: List[int] = field(default_factory=list)
    hub_system: str = ""                         # drop-off / hub; empty = auto (prefers a VOC location)

    # --- Live sliders (step 3) ----------------------------------------------------
    effort: int = 30            # the goal: 0 = set and forget, 50 = balanced, 100 = max ISK
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
    hour_isk: float = -1.0          # what an hour of your time is worth (drives the planner); -1 = the goal's default
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

    def solve_json(self) -> str:
        """The settings a plan depends on, for cache keys: without where the guided setup was left."""
        data = asdict(self)
        for name in UI_FIELDS:
            data.pop(name, None)
        return json.dumps(data, sort_keys=True)

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

    # Sensible bounds for numbers a pilot can type: out-of-range values are clamped, not stored as is.
    LIMITS = {
        "effort": (0, 100), "max_tier": (1, 4), "max_systems": (0, 50), "max_jumps": (0, 20),
        "cycle_days": (1, 30), "per_planet": (1, 3), "ship_every_days": (1, 90), "hour_isk": (-1, 1e12),
        "buyback_pct": (0, 100), "buyback_pct_p1": (0, 100), "poco_tax_pct": (0, 100), "sales_tax_pct": (0, 100),
        "broker_fee_pct": (0, 100), "stack_yield_pct": (0, 100), "head_yield_per_hour": (1, 100000),
        "solver_time_limit": (1, 600),
    }
    def _set(self, name: str, cur, val) -> None:
        self._set_raw(name, cur, val)          # text and lists are cut to TEXT_LIMITS / LIST_MAX there
        lo_hi = self.LIMITS.get(name)
        if lo_hi:
            setattr(self, name, type(cur)(min(max(getattr(self, name), lo_hi[0]), lo_hi[1])))

    def _set_raw(self, name: str, cur, val) -> None:
        if isinstance(cur, list):
            if isinstance(val, str):
                val = [x.strip() for x in val.split(",") if x.strip()]
            val = list(val)[:LIST_MAX]
            if name == "selected_constellations":
                val = [int(x) for x in val]
            else:
                val = [str(x)[:LIST_ITEM_MAX] for x in val]
            setattr(self, name, val)
        elif isinstance(cur, int):
            setattr(self, name, int(float(str(val or 0).replace(",", "."))))
        elif isinstance(cur, float):
            setattr(self, name, float(str(val or 0).replace(",", ".")))
        else:
            setattr(self, name, str(val)[:TEXT_LIMITS.get(name, TEXT_MAX)])


# What an hour of your time is worth when you haven't set it yourself, per goal (the guided setup's
# first question). "Max ISK" values time at 0: only income counts.
HOUR_DEFAULTS = {"passive": 300e6, "balanced": 90e6, "max": 0.0}


def goal_of(effort: int) -> str:
    """The guided setup's goal for an effort value: 0 = set and forget, 50 = balanced, 100 = max ISK."""
    return "passive" if effort <= 25 else "balanced" if effort <= 75 else "max"


def hour_value(s: "Settings") -> float:
    """ISK one hour of the pilot's time is worth: their own value, or their goal's default."""
    try:
        own = float(s.hour_isk)
    except (TypeError, ValueError):
        own = -1.0
    return own if own >= 0 else HOUR_DEFAULTS[goal_of(int(s.effort))]


def time_weights(s: "Settings") -> dict:
    """Penalty weights (ISK per day) for the extra work a plan asks: hauling, systems on the pickup round
    and factory restocks. They use the same minutes as the time estimate the guided setup shows
    (planner/compare.py), valued at what an hour of the pilot's time is worth, so the planner and the
    advice weigh effort the same way. Colonies themselves aren't charged: free slots get used."""
    from .planner import compare
    per_min = hour_value(s) / 60
    return {
        "isk_per_m3": per_min * compare.MIN_PER_60K_M3 / 60000,
        "isk_per_system": per_min * compare.MIN_PER_SYSTEM_VISIT / max(1.0, float(s.ship_every_days)),
        "isk_per_factory": per_min * compare.MIN_PER_RESTOCK / max(1.0, float(s.cycle_days)),
    }
