"""The home market: the null-sec regions whose buy and sell orders count as "local" for plans.

AstraCore prices three markets: Jita 4-4, Amarr VIII and the home market, the region-wide order books of the
regions in ``ASTRACORE_HOME_REGIONS`` (comma-separated region names, or ``Name:region_id`` for a region not
in ``KNOWN``). The default follows the alliance the site is run for (Dracarys.: Paragon Soul and Esoteria);
when the alliance moves, change the setting, not the code. A drop-off counts as local when its region is one
of these.
"""
from __future__ import annotations

from typing import List, Tuple

from astracore import config

# Null-sec regions AstraCore knows by name (EVE region ids).
KNOWN = {
    "Paragon Soul": 10000059, "Esoteria": 10000039, "Period Basis": 10000063, "Delve": 10000060,
    "Querious": 10000050, "Fountain": 10000058, "Cloud Ring": 10000051, "Insmother": 10000009,
    "Impass": 10000031, "Feythabolis": 10000056, "Omist": 10000062, "Tenerifis": 10000061,
    "Immensea": 10000025, "Detorid": 10000005, "Wicked Creek": 10000006, "Scalding Pass": 10000008,
    "Catch": 10000014, "Providence": 10000047, "Stain": 10000022,
}
DEFAULT = ("Paragon Soul", "Esoteria")


def _parse(entry: str) -> Tuple[str, int]:
    name, _, rid = entry.partition(":")
    name = name.strip()
    if rid.strip().isdigit():
        return name, int(rid)
    for known, region_id in KNOWN.items():
        if known.lower() == name.lower():
            return known, region_id
    return name, 0


def home_regions() -> List[Tuple[str, int]]:
    """(name, region id) of every home region; unknown names without an id are left out."""
    entries = config.HOME_REGIONS or list(DEFAULT)
    out = [_parse(e) for e in entries]
    return [(n, r) for n, r in out if n and r] or [(n, KNOWN[n]) for n in DEFAULT]


def home_region_ids() -> List[int]:
    return [r for _, r in home_regions()]


def home_region_names() -> List[str]:
    return [n for n, _ in home_regions()]


def home_label() -> str:
    """How the home market is named in running text ("Paragon Soul / Esoteria")."""
    return " / ".join(home_region_names())


def is_home_region(name: str) -> bool:
    return bool(name) and name.lower() in {n.lower() for n in home_region_names()}
