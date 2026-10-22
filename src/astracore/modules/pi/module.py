"""AstracorePI's entry in the module registry."""
from __future__ import annotations

from astracore.core.registry import Bundle, Module, register

PI_REQUIRED = Bundle(
    "pi.required", "AstraCore PI",
    scopes=(
        "esi-planets.manage_planets.v1",
        "esi-skills.read_skills.v1",
        "esi-assets.read_assets.v1",
        "esi-universe.read_structures.v1",
        "esi-contracts.read_character_contracts.v1",
        "esi-markets.read_character_orders.v1",
        "esi-wallet.read_character_wallet.v1",
        "esi-characters.read_standings.v1",
    ),
    why="Colonies and extractors, Command Center Upgrades and tax skills, products in your hangars and where they "
        "are, VOC contracts, sell orders, the ISK that actually came in, and standings for the broker fee.",
)
PI_CUSTOMS = Bundle(
    "pi.optional.customs", "Real customs office tax",
    scopes=("esi-planets.read_customs_offices.v1",),
    why="The real POCO tax for corporations where you're a Director. Without it the Settings value is used.",
)
PI_WAYPOINTS = Bundle(
    "pi.optional.waypoints", "Send routes to your EVE client",
    scopes=("esi-ui.write_waypoint.v1",),
    why="Adds a \"Send route to EVE\" button to your plan and pickup routes. It sets waypoints in your running client.",
    writes=True,
)


def _tile(profile):
    from .service import dashboard_tile   # late import: keeps the registry light
    return dashboard_tile(profile)


def _character_removed(profile_id: int, character_id: int) -> None:
    from .store import strip_character
    strip_character(profile_id, character_id)


def _reset(profile_id: int) -> None:
    from .store import reset_profile
    reset_profile(profile_id)


MODULE = register(Module(
    id="pi", name="AstraCore PI", short="PI", status="live",
    route_prefix="/pi", icon="static/img/modules/pi.svg",
    tagline="Plan Planetary Interaction across all your characters and systems, and run it day to day.",
    required_bundle=PI_REQUIRED,
    optional_bundles=[PI_CUSTOMS, PI_WAYPOINTS],
    # Plan setup sub-nav and menu group; Plan and Operate are also primary destinations (core/navigation.py).
    nav=[("Plan", "/pi/plan", "layers", "Build a plan around your playtime"),
         ("Area", "/pi/area", "map", "Choose the systems available to your plan"),
         ("Settings", "/pi/settings", "settings", "Fine-tune your planning assumptions")],
    dashboard_tile=_tile,
    on_character_removed=_character_removed,
    on_profile_reset=_reset,
    reset_label="Reset AstraCore PI: wipes PI settings, plans and planet overrides; keeps your characters.",
))
