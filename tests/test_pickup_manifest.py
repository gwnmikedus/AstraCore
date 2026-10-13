"""Cached pickup exports: synthetic profiles and stock; no ESI or planning calls."""
import csv
import io

import pytest

from astracore import db
from astracore.modules.pi import service
from astracore.modules.pi.planner import operate
from astracore.modules.pi.static_data import sde_loader
from astracore.modules.pi.static_data.sde_loader import PIData, Schematic
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401


@pytest.fixture()
def metadata(monkeypatch):
    pi = PIData({1: {"name": "Biofuels", "tier": 1, "volume": .38},
                 2: {"name": "Reactive Metals", "tier": 1, "volume": .38},
                 3: {"name": "Water", "tier": 0, "volume": .01}},
                {10: Schematic(10, "Factory", 3600, 5, 5, {2: 40})})
    monkeypatch.setattr(sde_loader, "cached", lambda: pi)

    def forbidden(*args, **kwargs):
        raise AssertionError("Export must not fetch or solve")

    monkeypatch.setattr(service, "planning_context", forbidden)
    monkeypatch.setattr(service, "load_static", forbidden)
    return pi


def colony():
    return {"planet_id": 40000001, "planet_name": "Alpha, I", "system_name": "Alpha",
            "last_update": "2026-10-01T02:03:04Z",
            "pins": [{"schematic_id": 10, "contents": [{"type_id": 1, "amount": 12},
                                                        {"type_id": 2, "amount": 40},
                                                        {"type_id": 3, "amount": 500}]},
                     {"contents": [{"type_id": 1, "amount": 3}]}]}


def rows(response):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert 'attachment;' in response.headers['content-disposition']
    return list(csv.DictReader(io.StringIO(response.text)))


def test_export_matches_operate_and_isolates_profiles_and_excluded_characters(browser, eve, metadata):
    client, other = browser(), browser()
    cid, excluded, foreign = new_id(), new_id(), new_id()
    sso_login(client, eve, cid, "Synthetic Pilot")
    sso_login(client, eve, excluded, "Excluded", path="/auth/login?intent=add")
    sso_login(other, eve, foreign, "Foreign Pilot")
    for char in (cid, excluded, foreign):
        db.set_character(char, colonies=[colony()], synced_at=1790810000)
    db.set_character(excluded, enabled=0)
    [row] = rows(client.get("/pi/export/pickup.csv"))
    assert row["character"] == "Synthetic Pilot"
    assert row["character_id"] == str(cid)
    assert (row["planet"], row["product"], row["quantity"], row["volume_m3"]) == ("Alpha, I", "Biofuels", "15", "5.7")
    assert row["colony_snapshot"] == colony()["last_update"]
    assert row["character_synced_at_utc"].endswith("Z")
    assert "customs-office access and cargo capacity are not checked" in row["limits"]
    status = operate.colonies_status(metadata, service.planning_characters(me(client)), None)
    assert status["pickups"][0]["items"] == {row["product"]: int(row["quantity"])}


def test_export_empty_without_static_metadata_and_requires_login(browser, eve, monkeypatch):
    client = browser()
    assert client.get("/pi/export/pickup.csv", follow_redirects=False).status_code == 303
    sso_login(client, eve, new_id(), "Empty Pilot")
    monkeypatch.setattr(sde_loader, "cached", lambda: None)
    response = client.get("/pi/export/pickup.csv")
    assert rows(response) == []
    assert response.text.startswith("character,character_id,")


def test_export_metadata_limits_and_missing_timestamps(browser, eve, metadata, monkeypatch):
    client, cid = browser(), new_id()
    sso_login(client, eve, cid, "=Synthetic Pilot")
    col = colony()
    del col["last_update"]
    db.set_character(cid, colonies=[col], synced_at=None)
    del metadata.items[1]["volume"]
    [row] = rows(client.get("/pi/export/pickup.csv"))
    assert row["character"] == "'=Synthetic Pilot"
    assert row["volume_m3"] == "" and row["metadata"] == "missing volume"
    assert row["colony_snapshot"] == row["character_synced_at_utc"] == ""
    del metadata.items[1]["name"]
    [row] = rows(client.get("/pi/export/pickup.csv"))
    assert row["product"] == "1" and row["metadata"] == "missing name, volume"
    col["pins"][0]["schematic_id"] = 999
    db.set_character(cid, colonies=[col])
    assert client.get("/pi/export/pickup.csv").status_code == 503
    col["pins"][0]["schematic_id"] = 10
    col["pins"][0]["contents"].append({"type_id": 9999, "amount": 2})
    db.set_character(cid, colonies=[col])
    assert client.get("/pi/export/pickup.csv").status_code == 503
    monkeypatch.setattr(sde_loader, "cached", lambda: None)
    assert client.get("/pi/export/pickup.csv").status_code == 503


def test_item_list_aggregates_cached_stock_without_pilot_details(browser, eve, metadata):
    client, other = browser(), browser()
    cid, alt, excluded, foreign = [new_id() for _ in range(4)]
    sso_login(client, eve, cid, "Synthetic Private Pilot")
    sso_login(client, eve, alt, "Synthetic Alt", path="/auth/login?intent=add")
    sso_login(client, eve, excluded, "Excluded", path="/auth/login?intent=add")
    sso_login(other, eve, foreign, "Foreign")
    for char in (cid, alt, excluded, foreign):
        db.set_character(char, colonies=[colony()])
    db.set_character(excluded, enabled=0)
    response = client.get("/pi/export/pickup.txt")
    assert response.status_code == 200
    assert response.text == "Biofuels\t30\n"
    assert response.headers["cache-control"] == "no-store"
    assert "astracore-pi-pickup-items.txt" in response.headers["content-disposition"]
    csv_rows = rows(client.get("/pi/export/pickup.csv"))
    assert sum(int(row["quantity"]) for row in csv_rows) == 30
    assert {row["character_id"] for row in csv_rows} == {str(cid), str(alt)}


def test_item_list_keeps_csv_per_colony_whole_unit_rounding(browser, eve, metadata):
    client, cid = browser(), new_id()
    sso_login(client, eve, cid, "Synthetic Pilot")
    first, second = colony(), colony()
    first["pins"][0]["contents"][0]["amount"] = 12.9
    second["pins"] = [{"contents": [{"type_id": 1, "amount": 2.2}]}]
    db.set_character(cid, colonies=[first, second])
    assert client.get("/pi/export/pickup.txt").text == "Biofuels\t17\n"
    csv_rows = rows(client.get("/pi/export/pickup.csv"))
    assert [row["quantity"] for row in csv_rows] == ["15", "2"]
    assert [row["volume_m3"] for row in csv_rows] == ["6.042", "0.836"]


def test_item_list_empty_authentication_and_missing_name(browser, eve, metadata, monkeypatch):
    client, cid = browser(), new_id()
    assert client.get("/pi/export/pickup.txt", follow_redirects=False).status_code == 303
    sso_login(client, eve, cid, "Synthetic Pilot")
    assert client.get("/pi/export/pickup.txt").text == ""
    db.set_character(cid, colonies=[colony()])
    del metadata.items[1]["volume"]
    assert client.get("/pi/export/pickup.txt").text == "Biofuels\t15\n"
    del metadata.items[1]["name"]
    assert client.get("/pi/export/pickup.txt").status_code == 503
    monkeypatch.setattr(sde_loader, "cached", lambda: None)
    assert client.get("/pi/export/pickup.txt").status_code == 503


@pytest.mark.parametrize("damage", ["unknown item", "unknown recipe", "missing quantity"])
def test_pickup_formats_refuse_incomplete_stock(browser, eve, metadata, damage):
    client, cid = browser(), new_id()
    sso_login(client, eve, cid, "Synthetic Pilot")
    col = colony()
    if damage == "unknown item":
        col["pins"][0]["contents"].append({"type_id": 9999, "amount": 2})
    elif damage == "unknown recipe":
        col["pins"][0]["schematic_id"] = 999
    else:
        del col["pins"][0]["contents"][0]["amount"]
    db.set_character(cid, colonies=[col])
    for path in ("/pi/export/pickup.txt", "/pi/export/pickup.csv"):
        assert client.get(path).status_code == 503
