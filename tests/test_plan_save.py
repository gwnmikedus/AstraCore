"""Displayed plans are saved once, owned by the profile, without running another solve."""
from __future__ import annotations

import copy
import time

import pytest

from astracore import db
from astracore.modules.pi import service, store

from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401


@pytest.fixture
def plan_client(browser, eve, monkeypatch):
    client = browser()
    character_id = new_id()
    sso_login(client, eve, character_id, "Snapshot Pilot")
    result = {"totals": {"isk_per_day": 123456, "colonies": 1}, "hub": "Fake hub", "warnings": [],
              "characters": [{"character_id": character_id}], "colonies": [{"planet_id": 40000001,
              "character_id": character_id, "kind": "miner", "action": "build", "product": "Biofuels"}]}
    calls = []

    async def solve(profile_id, settings):
        calls.append(settings.to_json())
        return result

    monkeypatch.setattr(service, "solve", solve)
    return client, me(client), character_id, result, calls


def suggest(client):
    response = client.post("/pi/api/suggest", json={}, headers={"X-CSRF-Token": csrf(client)})
    assert response.status_code == 200, response.text
    return response.json()


def save(client, result_id, **fields):
    return client.post("/pi/api/plans", json={"result_id": result_id, **fields},
                       headers={"X-CSRF-Token": csrf(client)})


def test_save_exact_displayed_result_and_idempotent_retry(plan_client):
    client, profile_id, _, source, calls = plan_client
    displayed = suggest(client)
    expected = copy.deepcopy(displayed)
    expected.pop("result_id")
    source["totals"]["isk_per_day"] = 999999   # A fresh solve would now return something else.
    response = save(client, displayed["result_id"], label="Displayed", active=True, result={"forged": True})
    assert response.status_code == 200
    run = store.get_plan_run(profile_id, response.json()["id"])
    assert run["result"] == expected
    assert run["active"] and run["label"] == "Displayed"
    retry = save(client, displayed["result_id"], label="Duplicate", active=False)
    assert retry.json()["id"] == run["id"]
    assert len(store.list_plan_runs(profile_id)) == len(calls) == 1


def test_result_is_profile_owned_and_requires_server_handle(plan_client, browser, eve):
    client, profile_id, _, _, _ = plan_client
    displayed = suggest(client)
    other = browser()
    sso_login(other, eve, new_id(), "Other Snapshot Pilot")
    assert save(other, displayed["result_id"]).status_code == 409
    assert save(client, "invented", result=displayed).status_code == 409
    assert save(client, None, result=displayed).status_code == 409
    assert not store.list_plan_runs(profile_id)
    assert not store.list_plan_runs(me(other))


@pytest.mark.parametrize("change", ["settings", "ownership", "removed-character", "expiry", "replacement", "active", "richness"])
def test_stale_results_are_not_saved(plan_client, change):
    client, profile_id, character_id, _, _ = plan_client
    displayed = suggest(client)
    if change == "settings":
        settings = store.load_settings(profile_id)
        settings.cycle_days = 7
        store.save_settings(profile_id, settings)
    elif change == "ownership":
        db.set_character(character_id, enabled=0)
    elif change == "removed-character":
        db.delete_character(character_id)
    elif change == "expiry":
        with db.session() as connection:
            connection.execute("UPDATE plan_results SET created=? WHERE profile_id=?",
                               (time.time() - store.RESULT_MAX_AGE - 1, profile_id))
    elif change == "replacement":
        suggest(client)
    elif change == "active":
        store.save_plan_run(profile_id, "Changed in another tab", store.load_settings(profile_id),
                            {"totals": {}}, active=True)
    else:
        store.set_planet_override(profile_id, 40000001, 1.5)
    response = save(client, displayed["result_id"], active=True)
    assert response.status_code == 409 and response.json()["stale"]
    assert len(store.list_plan_runs(profile_id)) == (1 if change == "active" else 0)


def test_navigation_metadata_does_not_stale_the_result(plan_client):
    client, profile_id, _, _, _ = plan_client
    displayed = suggest(client)
    settings = store.load_settings(profile_id)
    settings.guide_step = 2
    settings.answered = ["goal", "cycle"]
    store.save_settings(profile_id, settings)
    assert save(client, displayed["result_id"]).status_code == 200


def test_existing_active_plan_is_only_replaced_explicitly(plan_client):
    client, profile_id, _, _, _ = plan_client
    original_id = store.save_plan_run(profile_id, "Original", store.load_settings(profile_id),
                                      {"totals": {}}, active=True)
    candidate = suggest(client)
    response = save(client, candidate["result_id"], active=False)
    assert response.status_code == 200 and not response.json()["active"]
    assert store.active_plan(profile_id)["id"] == original_id
    replacement = suggest(client)
    response = save(client, replacement["result_id"], active=True)
    assert response.status_code == 200 and store.active_plan(profile_id)["id"] == response.json()["id"]
    # A lost-response retry must not overwrite an active plan changed in another tab.
    assert store.set_active_plan(profile_id, original_id)
    retry = save(client, replacement["result_id"], active=True)
    assert retry.json()["id"] == response.json()["id"] and not retry.json()["active"]
    assert store.active_plan(profile_id)["id"] == original_id


def test_ownership_changes_during_solve_do_not_publish_a_saveable_result(plan_client, monkeypatch):
    client, profile_id, character_id, result, _ = plan_client

    async def changed_during_solve(pid, settings):
        db.set_character(character_id, enabled=0)
        return result

    monkeypatch.setattr(service, "solve", changed_during_solve)
    response = client.post("/pi/api/suggest", json={}, headers={"X-CSRF-Token": csrf(client)})
    assert response.status_code == 409 and "result_id" not in response.json()
    assert not store.list_plan_runs(profile_id)


def test_failed_solve_does_not_publish_a_handle(plan_client, monkeypatch):
    client, _, _, _, _ = plan_client

    async def failed(pid, settings):
        return {"error": "No usable planets"}

    monkeypatch.setattr(service, "solve", failed)
    assert "result_id" not in suggest(client)


def test_concurrent_retries_create_only_one_plan(plan_client):
    from concurrent.futures import ThreadPoolExecutor

    from astracore.modules.pi.routes import _result_stamp

    client, profile_id, _, _, calls = plan_client
    displayed = suggest(client)

    def persist():
        return store.save_plan_result(profile_id, displayed["result_id"], "Concurrent",
                                      lambda: _result_stamp(profile_id), active=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: persist(), range(2)))
    assert first["id"] == second["id"]
    assert len(store.list_plan_runs(profile_id)) == len(calls) == 1
