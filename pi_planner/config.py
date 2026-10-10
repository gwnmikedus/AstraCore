"""Paths, .env handling and the user-editable settings model."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PI_PLANNER_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "pi_planner.sqlite3"
ENV_PATH = ROOT / ".env"

HOST = "127.0.0.1"
PORT = int(os.environ.get("PI_PLANNER_PORT", "8765"))
# Every scope enabled on the EVE application, so new features never need another login.
SSO_SCOPES = [
    "publicData",
    "esi-calendar.respond_calendar_events.v1",
    "esi-calendar.read_calendar_events.v1",
    "esi-location.read_location.v1",
    "esi-location.read_ship_type.v1",
    "esi-mail.organize_mail.v1",
    "esi-mail.read_mail.v1",
    "esi-mail.send_mail.v1",
    "esi-skills.read_skills.v1",
    "esi-skills.read_skillqueue.v1",
    "esi-wallet.read_character_wallet.v1",
    "esi-wallet.read_corporation_wallet.v1",
    "esi-search.search_structures.v1",
    "esi-clones.read_clones.v1",
    "esi-characters.read_contacts.v1",
    "esi-universe.read_structures.v1",
    "esi-killmails.read_killmails.v1",
    "esi-corporations.read_corporation_membership.v1",
    "esi-assets.read_assets.v1",
    "esi-planets.manage_planets.v1",
    "esi-fleets.read_fleet.v1",
    "esi-fleets.write_fleet.v1",
    "esi-ui.open_window.v1",
    "esi-ui.write_waypoint.v1",
    "esi-characters.write_contacts.v1",
    "esi-fittings.read_fittings.v1",
    "esi-fittings.write_fittings.v1",
    "esi-markets.structure_markets.v1",
    "esi-corporations.read_structures.v1",
    "esi-characters.read_loyalty.v1",
    "esi-characters.read_chat_channels.v1",
    "esi-characters.read_medals.v1",
    "esi-characters.read_standings.v1",
    "esi-characters.read_agents_research.v1",
    "esi-industry.read_character_jobs.v1",
    "esi-markets.read_character_orders.v1",
    "esi-characters.read_blueprints.v1",
    "esi-characters.read_corporation_roles.v1",
    "esi-location.read_online.v1",
    "esi-contracts.read_character_contracts.v1",
    "esi-clones.read_implants.v1",
    "esi-characters.read_fatigue.v1",
    "esi-killmails.read_corporation_killmails.v1",
    "esi-corporations.track_members.v1",
    "esi-wallet.read_corporation_wallets.v1",
    "esi-characters.read_notifications.v1",
    "esi-corporations.read_divisions.v1",
    "esi-corporations.read_contacts.v1",
    "esi-assets.read_corporation_assets.v1",
    "esi-corporations.read_titles.v1",
    "esi-corporations.read_blueprints.v1",
    "esi-contracts.read_corporation_contracts.v1",
    "esi-corporations.read_standings.v1",
    "esi-corporations.read_starbases.v1",
    "esi-industry.read_corporation_jobs.v1",
    "esi-markets.read_corporation_orders.v1",
    "esi-corporations.read_container_logs.v1",
    "esi-industry.read_character_mining.v1",
    "esi-industry.read_corporation_mining.v1",
    "esi-planets.read_customs_offices.v1",
    "esi-corporations.read_facilities.v1",
    "esi-corporations.read_medals.v1",
    "esi-characters.read_titles.v1",
    "esi-alliances.read_contacts.v1",
    "esi-characters.read_fw_stats.v1",
    "esi-corporations.read_fw_stats.v1",
    "esi-corporations.read_projects.v1",
    "esi-corporations.read_freelance_jobs.v1",
    "esi-characters.read_freelance_jobs.v1",
    "esi-structures.read_corporation.v1",
    "esi-structures.read_character.v1",
    "esi-activities.read_character.v1",
    "esi-access.read_lists.v1",
    "esi.activity.char:read",
    "esi.cosmetic.char:read",
]
# What the tool actually uses today; characters missing these are asked to log in again.
REQUIRED_SCOPES = [
    "esi-planets.manage_planets.v1",
    "esi-skills.read_skills.v1",
    "esi-assets.read_assets.v1",
    "esi-contracts.read_character_contracts.v1",
    "esi-markets.read_character_orders.v1",
    "esi-wallet.read_character_wallet.v1",
    "esi-universe.read_structures.v1",
]


def load_env() -> dict:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"')
    return env


def save_env(updates: dict) -> None:
    env = load_env()
    env.update({k: v for k, v in updates.items() if v is not None})
    ENV_PATH.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass


def callback_url() -> str:
    """Must match the Callback URL registered on developers.eveonline.com exactly."""
    return load_env().get("EVE_CALLBACK_URL", f"http://localhost:{PORT}/auth/callback")


def sso_credentials() -> tuple:
    env = load_env()
    return env.get("EVE_CLIENT_ID", ""), env.get("EVE_CLIENT_SECRET", "")


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
                val = data[f.name]
                if isinstance(cur, list):
                    if isinstance(val, str):
                        val = [x.strip() for x in val.split(",") if x.strip()]
                    if f.name == "selected_constellations":
                        val = [int(x) for x in val]
                    setattr(self, f.name, list(val))
                elif isinstance(cur, int):
                    setattr(self, f.name, int(float(val or 0)))
                elif isinstance(cur, float):
                    setattr(self, f.name, float(val or 0))
                else:
                    setattr(self, f.name, str(val))


def effort_weights(effort: int) -> dict:
    """Map the single effort slider (0 = least effort, 100 = max ISK) to penalty weights."""
    lazy = max(0.0, min(1.0, 1 - effort / 100.0)) ** 2
    return {
        "isk_per_m3": 400.0 * lazy,               # hauling
        "isk_per_system": 1_500_000.0 * lazy,      # each system to fly to (per day)
        "isk_per_factory": 2_000_000.0 * lazy,     # factory planets need restocking
    }
