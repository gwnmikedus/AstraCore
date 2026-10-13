"""Synthetic PI recipes and HTTP responses only; never contact Fuzzwork or ESI."""
import asyncio
import copy

import httpx
import pytest

from astracore.modules.pi.static_data import sde_loader as sde

SCHEMS = "schematicID,schematicName,cycleTime\n1,Fictional refining,1800\n"
MAPPING = "schematicID,typeID,quantity,isInput\n1,10,3000,1\n1,20,40,0\n"


@pytest.fixture
def source(monkeypatch, tmp_path):
    state = {"cache": None, "now": 1_000_000.0, "calls": [], "texts": {
        "planetSchematics": SCHEMS, "planetSchematicsTypeMap": MAPPING}, "mode": "etag", "enrich": 0}
    monkeypatch.setattr(sde.db, "kv_get", lambda key: copy.deepcopy(state["cache"]))
    monkeypatch.setattr(sde.db, "kv_set", lambda key, value: state.update(cache=copy.deepcopy(value)))
    monkeypatch.setattr(sde.time, "time", lambda: state["now"])
    monkeypatch.setattr(sde, "SDE_DIR", tmp_path)
    async def enrich(esi, data):
        state["enrich"] += 1
        for tid, item in data.items.items():
            item["name"] = f"Fictional item {tid}"
        data._index()
    monkeypatch.setattr(sde, "_enrich", enrich)
    async def respond(request):
        await asyncio.sleep(0)  # Concurrent callers must wait for the shared refresh.
        name = request.url.path.rsplit("/", 1)[1][:-4]
        state["calls"].append((name, dict(request.headers)))
        if state["mode"] == "outage":
            raise httpx.ConnectError("synthetic outage", request=request)
        text = state["texts"][name]
        etag = '"' + str(hash(text)) + '"'
        headers = {"etag": etag, "last-modified": "Mon, 12 Oct 2026 11:37:59 GMT"} if state["mode"] == "etag" else {}
        if headers and request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers=headers)
        if state["mode"] == "changing" and len(state["calls"]) % 4 == 3:
            text = text.replace("1800", "3600")
        return httpx.Response(200, text=text, headers=headers)
    client = httpx.AsyncClient
    monkeypatch.setattr(sde.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    return state


def load(force=False):
    return asyncio.run(sde.load(None, force=force))


def test_initial_load_publishes_tables_metadata_and_derived_data_together(source):
    data = load()
    assert data.recipe(20).output_qty == 40
    assert len(source["calls"]) == 4
    assert source["enrich"] == 1
    info = sde.source_info()
    assert not info["stale"] and not info["error"]
    assert info["checked_at"] == source["now"] == info["loaded_at"]
    assert info["content_id"]
    assert set(info["tables"]) == set(sde.TABLES)
    assert all("text" not in table and table["sha256"] for table in info["tables"].values())
    assert sde.cached().name(20) == "Fictional item 20"


def test_fresh_cache_has_no_requests_and_daily_304_keeps_content_id(source):
    load()
    stamp = sde.stamp()
    source["calls"].clear()
    load()
    assert source["calls"] == []
    source["now"] += sde.CHECK_EVERY
    assert sde.stamp() != stamp and sde.source_info()["stale"]
    load()
    assert len(source["calls"]) == 4
    assert all(headers.get("if-none-match") and headers.get("if-modified-since") for _, headers in source["calls"])
    assert sde.stamp() == stamp
    assert source["enrich"] == 1


def test_changed_recipe_changes_planner_and_displayed_result_fingerprints(source, monkeypatch):
    from astracore.modules.pi import service, routes
    from astracore.modules.pi.settings import Settings
    load()
    monkeypatch.setattr(service.db, "list_characters", lambda pid: [])
    monkeypatch.setattr(service.store, "planet_overrides", lambda pid: {})
    monkeypatch.setattr(service.store, "admin_defaults", lambda: {})
    monkeypatch.setattr(service.prices, "cached", lambda: {"at": 1})
    monkeypatch.setattr(service.prices, "history_cached", lambda: {"at": 1})
    monkeypatch.setattr(service.voc, "routes_info", lambda: {"at": 1})
    monkeypatch.setattr(routes, "_profile_result_stamp", lambda pid: "same-profile")
    key, result = service.plan_key(1, Settings()), routes._result_stamp(1)
    source["now"] += sde.CHECK_EVERY
    source["texts"]["planetSchematicsTypeMap"] = MAPPING.replace("20,40", "20,80")
    assert load().recipe(20).output_qty == 80
    assert service.plan_key(1, Settings()) != key
    assert routes._result_stamp(1) != result


def test_force_requests_source_even_when_fresh_and_skips_conditional_first_pass(source):
    load()
    source["calls"].clear()
    source["texts"]["planetSchematicsTypeMap"] = MAPPING.replace("20,40", "20,80")
    assert load(force=True).recipe(20).output_qty == 80
    assert len(source["calls"]) == 4
    assert all("if-none-match" not in headers and "if-modified-since" not in headers for _, headers in source["calls"][:2])


@pytest.mark.parametrize("bad", ["", "<html>unavailable</html>", MAPPING.replace("1,20,40", "999,20,40"),
                                     MAPPING.replace("20,40", "20,0"), MAPPING + "1,30,5,0\n"])
def test_invalid_second_table_keeps_whole_known_good_snapshot(source, bad):
    load()
    previous = copy.deepcopy(source["cache"])
    source["now"] += sde.CHECK_EVERY
    source["texts"]["planetSchematics"] = SCHEMS.replace("1800", "3600")
    source["texts"]["planetSchematicsTypeMap"] = bad
    assert load().recipe(20).cycle == 1800
    assert source["cache"]["source"]["tables"] == previous["source"]["tables"]
    assert source["cache"]["source"]["checked_at"] == previous["source"]["checked_at"]
    assert sde.source_info()["stale"] and sde.source_info()["error"]


def test_outage_retains_old_data_bounds_retry_and_force_can_retry(source):
    load()
    source["now"] += sde.CHECK_EVERY
    source["mode"] = "outage"
    assert load().name(20) == "Fictional item 20"
    attempted = sde.source_info()["attempted_at"]
    calls = len(source["calls"])
    source["now"] += sde.RETRY_EVERY - 1
    load()
    assert len(source["calls"]) == calls and sde.source_info()["attempted_at"] == attempted
    load(force=True)
    assert len(source["calls"]) == calls + 1
    source["now"] += sde.RETRY_EVERY
    source["mode"] = "etag"
    load()
    assert not sde.source_info()["error"] and not sde.source_info()["stale"]


def test_missing_validators_are_content_confirmed_and_changing_source_rejected(source):
    source["mode"] = "no-validators"
    load()
    previous = copy.deepcopy(source["cache"])
    assert len(source["calls"]) == 4
    source["calls"].clear()
    source["mode"] = "changing"
    source["now"] += sde.CHECK_EVERY
    assert load().recipe(20).cycle == 1800
    assert source["cache"]["source"]["tables"] == previous["source"]["tables"]
    assert "changed during refresh" in sde.source_info()["error"]


def test_legacy_derived_cache_is_refreshed_and_retained_on_outage(source):
    load()
    source["cache"].pop("source")
    source["calls"].clear()
    source["mode"] = "outage"
    assert load().recipe(20).output_qty == 40
    assert len(source["calls"]) == 1
    assert sde.source_info()["stale"] and "checked_at" not in sde.source_info()
    source["mode"] = "etag"
    load(force=True)
    assert not sde.source_info()["stale"]


def test_legacy_csv_pair_is_validated_only_as_unknown_age_fallback(source):
    for name, text in source["texts"].items():
        (sde.SDE_DIR / f"{name}.csv").write_text(text)
    source["mode"] = "outage"
    assert load().recipe(20).output_qty == 40
    assert sde.source_info()["stale"] and "checked_at" not in sde.source_info()


def test_first_install_failure_without_valid_fallback_raises(source):
    source["mode"] = "outage"
    with pytest.raises(httpx.ConnectError):
        load()
    assert source["cache"] is None


def test_enrichment_failure_does_not_publish_new_recipes_or_sources(source, monkeypatch):
    load()
    previous = copy.deepcopy(source["cache"])
    source["texts"]["planetSchematicsTypeMap"] = MAPPING.replace("20,40", "20,80")
    async def failed(esi, data):
        raise sde.ESIError("synthetic name lookup failure")
    monkeypatch.setattr(sde, "_enrich", failed)
    assert load(force=True).recipe(20).output_qty == 40
    assert source["cache"]["source"]["tables"] == previous["source"]["tables"]
    assert sde.source_info()["stale"]


def test_invalid_legacy_csv_pair_is_never_published(source):
    for name, text in source["texts"].items():
        (sde.SDE_DIR / f"{name}.csv").write_text(text if name == sde.TABLES[0] else "broken")
    source["mode"] = "outage"
    with pytest.raises(ValueError):
        load()
    assert source["cache"] is None


def test_concurrent_callers_share_one_refresh(source):
    async def both():
        return await asyncio.gather(sde.load(None), sde.load(None))
    first, second = asyncio.run(both())
    assert first.to_json() == second.to_json() and len(source["calls"]) == 4
