"""Module registry: every Astracore tool declares itself here once.

Home cards, dashboard tiles, the module switcher, "What we read", the scopes requested at
sign-in and the reset hooks are all generated from `MODULES`. Adding a module means building
its package and calling `register()`; auth and navigation don't change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# Plain-language description of every scope any bundle can request.
SCOPE_TEXT: Dict[str, str] = {
    "esi-planets.manage_planets.v1": "Your planetary colonies: planets, structures, extractors and what is stored on them. "
                                      "Read-only, despite the scope's name: we can't change your colonies.",
    "esi-skills.read_skills.v1": "Your trained skills (only the PI and trade skills are used).",
    "esi-assets.read_assets.v1": "Your assets, to find PI products in station and structure hangars.",
    "esi-universe.read_structures.v1": "Names and locations of player structures where your products are stored.",
    "esi-contracts.read_character_contracts.v1": "Your contracts, to follow courier and buyback contracts for PI products.",
    "esi-markets.read_character_orders.v1": "Your market orders, to follow sell orders for PI products.",
    "esi-wallet.read_character_wallet.v1": "Your wallet balance, transactions and journal, to show the ISK PI actually earned.",
    "esi-characters.read_standings.v1": "Your standings, which lower the broker fee on sell orders.",
    "esi-planets.read_customs_offices.v1": "Customs offices your corporation owns (needs a Director), for the real POCO tax.",
    "esi-ui.write_waypoint.v1": "Set waypoints in your running EVE client when you press \"Send route to EVE\". "
                                "This is the only scope that writes anything.",
}


@dataclass(frozen=True)
class Bundle:
    id: str
    title: str
    scopes: Tuple[str, ...]
    why: str
    writes: bool = False     # does any scope change something in the game?


@dataclass
class Module:
    id: str
    name: str
    short: str
    status: str                          # "live" | "beta" | "coming"
    route_prefix: str
    icon: str                            # path under the site root, e.g. static/img/modules/pi.svg
    tagline: str
    required_bundle: Bundle
    optional_bundles: List[Bundle] = field(default_factory=list)
    nav: List[Tuple[str, str, str]] = field(default_factory=list)      # (label, href, icon name)
    dashboard_tile: Optional[Callable] = None        # async (profile) -> dict for templates/dashboard.html
    on_character_removed: Optional[Callable] = None  # (profile_id, character_id) -> None
    on_profile_reset: Optional[Callable] = None      # (profile_id) -> None (module data only)
    reset_label: str = ""

    @property
    def bundles(self) -> List[Bundle]:
        return [self.required_bundle] + list(self.optional_bundles)


MODULES: List[Module] = []


def register(m: Module) -> Module:
    if m.status == "coming":
        return m   # not registered in v1: the home page shows a generic "more coming" card
    if any(x.id == m.id for x in MODULES):
        raise ValueError(f"module {m.id} registered twice")
    MODULES.append(m)
    return m


def get(module_id: str) -> Optional[Module]:
    return next((m for m in MODULES if m.id == module_id), None)


def all_bundles() -> Dict[str, Bundle]:
    return {b.id: b for m in MODULES for b in m.bundles}


def bundle(bundle_id: str) -> Optional[Bundle]:
    return all_bundles().get(bundle_id)


def module_of(bundle_id: str) -> Optional[Module]:
    return next((m for m in MODULES if any(b.id == bundle_id for b in m.bundles)), None)


def signin_scopes(enabled_modules: Optional[List[str]] = None) -> List[str]:
    """Core (no scopes) + the required bundle of each enabled module. v1: just pi.required."""
    mods = [m for m in MODULES if enabled_modules is None or m.id in enabled_modules]
    out: List[str] = []
    for m in mods:
        for s in m.required_bundle.scopes:
            if s not in out:
                out.append(s)
    return out


def granted_bundles(scopes: List[str]) -> List[str]:
    have = set(scopes)
    return [b.id for b in all_bundles().values() if set(b.scopes) <= have]
