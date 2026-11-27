"""Courier providers: the registry, which providers plans use, and the public Couriers reference page."""
import asyncio
import json
import time

import httpx

from astracore import config, db
from astracore.modules.pi import service, store
from astracore.modules.pi.planner import operate, selling
from astracore.modules.pi.static_data import carrier
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401

HUMPBACK_ROWS = [
    {"star_system": "Fictional pickup", "end_system": "Jita", "max_value": "60000", "price_per_cubic_meter": "1250",
     "additional_collateral_rate": "1", "minimum_reward": "5000000", "freight_frequency‌": "Daily", "is_enabled": "1"},
    {"star_system": "Jita", "end_system": "Fictional pickup", "max_value": "340000", "price_per_cubic_meter": "900",
     "additional_collateral_rate": "0", "minimum_reward": "5000000", "freight_frequency‌": "Weekly", "is_enabled": "1"},
    {"star_system": "Closed pickup", "end_system": "Amarr", "max_value": "60000", "price_per_cubic_meter": "1000",
     "additional_collateral_rate": "1", "minimum_reward": "5000000", "is_enabled": "0"},
]


def _clear_tariffs():
    for p in carrier.PROVIDERS:
        db.kv_set(p.routes_key, {})


def test_defaults_plan_with_humpback_only_and_offer_no_buyback(monkeypatch):
    monkeypatch.setattr(config, "COURIERS", [])
    _clear_tariffs()
    assert [p.id for p in carrier.active_providers()] == ["humpback"]
    assert carrier.courier_origins() == ["O4T-Z5", "R-ARKN"]
    assert not carrier.has_buyback() and carrier.buyback_site() == "" and carrier.buyback_locations() == []
    r = carrier.route("O4T-Z5", carrier.JITA)
    assert r["provider"] == "humpback" and r["min_fee"] == 5_000_000 and r["max_m3"] == 60_000
    assert carrier.route("7G-QIG", carrier.JITA) is None          # VOC is inactive
    assert carrier.assignee(r) == "Humpback Whale Logistic"
    assert selling.coverage("O4T-Z5", None) == {"local": True, "buyback": False, "courier": True, "trade_hub": False}


def test_env_list_switches_a_stopped_provider_back_on(monkeypatch):
    monkeypatch.setattr(config, "COURIERS", ["humpback", "voc"])
    _clear_tariffs()
    assert [p.id for p in carrier.active_providers()] == ["humpback", "voc"]
    assert carrier.has_buyback() and carrier.buyback_site() == carrier.VOC.buyback_site
    assert {"O4T-Z5", "7G-QIG"} <= set(carrier.courier_origins())
    assert carrier.route("7G-QIG", carrier.JITA)["provider"] == "voc"


def test_cheapest_provider_wins_a_shared_route(monkeypatch):
    routes = [{"origin": "X", "dest": carrier.JITA, "min_fee": 5e6, "per_m3": 1250, "collateral_pct": 1, "max_m3": 6e4,
               "provider": "humpback"},
              {"origin": "X", "dest": carrier.JITA, "min_fee": 1e7, "per_m3": 900, "collateral_pct": 1, "max_m3": 6e4,
               "provider": "voc"}]
    assert carrier.route("X", carrier.JITA, routes)["provider"] == "voc"


def test_humpback_tariff_parser_skips_disabled_rows_and_maps_hubs():
    routes = carrier.parse_humpback(json.dumps(HUMPBACK_ROWS))
    assert routes == [
        {"origin": "Fictional pickup", "dest": carrier.JITA, "min_fee": 5e6, "per_m3": 1250.0, "collateral_pct": 1.0,
         "max_m3": 60000.0, "frequency": "Daily"},
        {"origin": carrier.JITA, "dest": "Fictional pickup", "min_fee": 5e6, "per_m3": 900.0, "collateral_pct": 0.0,
         "max_m3": 340000.0, "frequency": "Weekly"}]
    assert carrier.parse_humpback("not json") == []


def test_refresh_reads_only_active_providers_and_keeps_fallback_on_failure(monkeypatch):
    monkeypatch.setattr(config, "COURIERS", [])
    _clear_tariffs()
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text=json.dumps(HUMPBACK_ROWS))

    monkeypatch.setattr(carrier, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    asyncio.run(carrier.refresh_routes())
    assert seen == [carrier.HUMPBACK.source_url]
    assert carrier.route("Fictional pickup", carrier.JITA)["provider"] == "humpback"
    assert carrier.routes_info()["live"]

    _clear_tariffs()
    monkeypatch.setattr(carrier, "_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    asyncio.run(carrier.refresh_routes())
    assert carrier.route("O4T-Z5", carrier.JITA)["per_m3"] == 1250     # fallback values stay in use


def test_contracts_of_an_inactive_provider_still_count(monkeypatch):
    monkeypatch.setattr(config, "COURIERS", [])
    assert carrier.by_corp(carrier.VOC.corp_id) is carrier.VOC
    assert carrier.by_corp(carrier.HUMPBACK.corp_id) is carrier.HUMPBACK
    assert carrier.by_corp(12345) is None
    legacy = {"type": "item_exchange", "voc": True, "pi": True}       # read before the provider list existed
    assert operate.pi_buyback(legacy)


def test_reference_lists_every_provider_without_refreshing(browser, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('A reference page must not request outside data')
    monkeypatch.setattr(carrier, 'refresh_routes', forbidden)
    monkeypatch.setattr(carrier, 'refresh_provider', forbidden)
    monkeypatch.setattr(config, "COURIERS", [])
    _clear_tariffs()
    page = browser().get('/couriers').text
    assert 'Humpback Whale Logistic' in page and 'Used in plans' in page
    assert 'VOC Hauling' in page and 'Not used: Stopped in November 2026.' in page
    assert 'Fallback values recorded on 27 November 2026' in page and 'Daily' in page and 'Weekly' in page
    assert carrier.HUMPBACK.site in page and carrier.VOC.buyback_site in page
    assert page.index('Humpback Whale Logistic') < page.index('VOC Hauling')


def test_reference_shows_a_cached_tariff_without_substituting_defaults(browser):
    db.kv_set(carrier.HUMPBACK.routes_key, {'at': time.time(), 'routes': [
        {'origin': 'Fictional pickup', 'dest': 'Fictional destination', 'min_fee': 4560000,
         'per_m3': 234, 'collateral_pct': 1.5, 'max_m3': 60000, 'frequency': 'Daily'}]})
    try:
        page = browser().get('/couriers').text
        assert 'Viewing this page does not refresh' in page
        assert 'Fictional pickup' in page and 'Fictional destination' in page and '234' in page
    finally:
        _clear_tariffs()


def test_old_voc_address_redirects_to_couriers(browser):
    r = browser().get('/voc-hauling', follow_redirects=False)
    assert r.status_code == 301 and r.headers['location'] == '/couriers#voc'


def test_pilot_settings_links_reference_and_preserves_stored_assumptions(browser, eve, monkeypatch):
    client = browser()
    sso_login(client, eve, new_id(), 'Fictional settings pilot')
    pid = me(client)
    monkeypatch.setattr(service, 'planning_characters', lambda profile: [])
    before = store.load_settings(pid).to_json()
    page = client.get('/pi/settings').text
    assert 'href="/couriers"' in page
    assert 'taxes_from_skills' in page and 'stack_yield_pct' in page
    client.get('/couriers')
    assert store.load_settings(pid).to_json() == before
