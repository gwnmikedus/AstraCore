"""Fixed game rules for Planetary Interaction that are not (conveniently) in the SDE/ESI."""
from __future__ import annotations

PLANET_TYPES = {
    11: "Temperate",
    12: "Ice",
    13: "Gas",
    2014: "Oceanic",
    2015: "Lava",
    2016: "Barren",
    2017: "Storm",
    2063: "Plasma",
    30889: "Shattered",  # no PI possible
}
PLANET_TYPE_BY_NAME = {v.lower(): k for k, v in PLANET_TYPES.items()}

# Raw resources (P0) available on each planet type.
P0_BY_PLANET = {
    "Barren": ["Aqueous Liquids", "Base Metals", "Carbon Compounds", "Microorganisms", "Noble Metals"],
    "Gas": ["Aqueous Liquids", "Base Metals", "Ionic Solutions", "Noble Gas", "Reactive Gas"],
    "Ice": ["Aqueous Liquids", "Heavy Metals", "Microorganisms", "Noble Gas", "Planktic Colonies"],
    "Lava": ["Base Metals", "Felsic Magma", "Heavy Metals", "Non-CS Crystals", "Suspended Plasma"],
    "Oceanic": ["Aqueous Liquids", "Carbon Compounds", "Complex Organisms", "Microorganisms",
                "Planktic Colonies"],
    "Plasma": ["Base Metals", "Heavy Metals", "Noble Metals", "Non-CS Crystals", "Suspended Plasma"],
    "Storm": ["Aqueous Liquids", "Base Metals", "Ionic Solutions", "Noble Gas", "Suspended Plasma"],
    "Temperate": ["Aqueous Liquids", "Autotrophs", "Carbon Compounds", "Complex Organisms",
                  "Microorganisms"],
    "Shattered": [],
}

# High-Tech Production Plants (P4) can only be built on these planet types.
HIGH_TECH_PLANETS = {"Barren", "Temperate"}

# Command Center CPU (tf) / Powergrid (MW) by Command Center Upgrades level.
CCU_CPU = [1675, 7057, 12136, 17215, 21315, 25415]
CCU_PG = [6000, 9000, 12000, 15000, 17000, 19000]

# Structure fitting costs: (CPU, PG). Identical on every planet type.
STRUCTURES = {
    "ecu": (400, 2600),
    "head": (110, 550),
    "basic": (200, 800),
    "advanced": (500, 700),
    "hightech": (1100, 400),
    "storage": (500, 700),
    "launchpad": (3600, 700),
}
# Links cost depends on length; this is a typical short-link average.
LINK_COST = (20, 15)

MAX_HEADS_PER_ECU = 10

# Command centers are the only part of a colony bought on the market: one per planet, of the
# planet's own type (SDE type ids, 1,000 m3 each). Everything else is built in the planetary interface.
COMMAND_CENTER_TYPES = {
    "Temperate": 2254, "Barren": 2524, "Oceanic": 2525, "Ice": 2533,
    "Gas": 2534, "Lava": 2549, "Storm": 2550, "Plasma": 2551,
}
COMMAND_CENTER_M3 = 1000.0
COMMAND_CENTER_ISK_ESTIMATE = 110_000   # Jita sell was ~106k on 2026-10-11; used without cached prices

# ISK the planetary interface charges from your wallet to place a structure (not market items).
STRUCTURE_ISK = {"ecus": 45_000, "basic": 75_000, "advanced": 250_000, "hightech": 525_000,
                 "storage": 250_000, "launchpads": 900_000}
STRUCTURE_NAMES = {"ecus": "Extractor Control Unit", "basic": "Basic Industry Facility",
                   "advanced": "Advanced Industry Facility", "hightech": "High-Tech Production Plant",
                   "storage": "Storage Facility", "launchpads": "Launchpad"}
# ISK to upgrade a placed command center from level n-1 to level n (index n), paid in the
# planetary interface. The Command Center Upgrades skill caps the level.
CCU_UPGRADE_ISK = [0, 580_000, 930_000, 1_200_000, 1_500_000, 2_100_000]


def upgrade_isk(from_level: int, to_level: int) -> int:
    lo, hi = max(0, int(from_level)), min(5, int(to_level))
    return sum(CCU_UPGRADE_ISK[lo + 1:hi + 1]) if hi > lo else 0


# Customs office "base" values used for export/import tax, by tier.
POCO_BASE_VALUE = {0: 5, 1: 400, 2: 7200, 3: 60000, 4: 1200000}

# Item volumes by tier (m3) - used if ESI volume lookup fails.
DEFAULT_VOLUME = {0: 0.01, 1: 0.38, 2: 0.75, 3: 3.0, 4: 50.0}

def cycle_factor(days: float) -> float:
    """Average hourly extractor output of a `days` program relative to a 3-day one (CCP formula)."""
    from .extraction import cycle_factor as _cf
    return _cf(days)


def cost(**counts: int) -> tuple:
    cpu = pg = 0
    links = 0
    for k, n in counts.items():
        c, p = STRUCTURES[k]
        cpu += c * n
        pg += p * n
        if k != "head":
            links += n
    cpu += LINK_COST[0] * links
    pg += LINK_COST[1] * links
    return cpu, pg


def fits(ccu_level: int, **counts: int) -> bool:
    cpu, pg = cost(**counts)
    lvl = max(0, min(5, ccu_level))
    return cpu <= CCU_CPU[lvl] and pg <= CCU_PG[lvl]
