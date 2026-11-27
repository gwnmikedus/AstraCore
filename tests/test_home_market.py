"""The home market follows the configured home regions (Dracarys.' Paragon Soul and Esoteria by default)."""
from astracore import config
from astracore.modules.pi.planner import selling
from astracore.modules.pi.static_data import markets


def test_default_home_regions_are_paragon_soul_and_esoteria(monkeypatch):
    monkeypatch.setattr(config, "HOME_REGIONS", [])
    assert markets.home_regions() == [("Paragon Soul", 10000059), ("Esoteria", 10000039)]
    assert markets.home_label() == "Paragon Soul / Esoteria"


def test_setting_takes_known_names_and_explicit_ids_and_skips_unknown_names(monkeypatch):
    monkeypatch.setattr(config, "HOME_REGIONS", ["delve", "Somewhere:10000999", "Nowhere"])
    assert markets.home_regions() == [("Delve", 10000060), ("Somewhere", 10000999)]
    monkeypatch.setattr(config, "HOME_REGIONS", ["Nowhere"])          # nothing usable: back to the default
    assert markets.home_region_names() == ["Paragon Soul", "Esoteria"]


def test_drop_off_is_local_by_its_region(monkeypatch):
    monkeypatch.setattr(config, "HOME_REGIONS", [])
    area = {"systems": {"1": {"name": "Fictional home system", "region": "Esoteria"},
                        "2": {"name": "Fictional Delve system", "region": "Delve"}}}
    assert selling.in_home("Fictional home system", area)
    assert not selling.in_home("Fictional Delve system", area)
    # without universe data, known courier pickups still tell their region
    assert selling.in_home("O4T-Z5", None) and selling.in_home("R-ARKN", None)
    assert not selling.in_home("7G-QIG", None) and not selling.in_home("Jita", None)


def test_templates_name_the_home_regions(monkeypatch):
    from astracore.core.web import templates
    monkeypatch.setattr(config, "HOME_REGIONS", ["Esoteria"])
    assert templates.env.globals["home_market"]() == "Esoteria"
