"""Current ESI sovereignty responses are fictional; all HTTP uses MockTransport."""
import json

import httpx
import pytest

from astracore import db
from astracore.esi import public, client
from astracore.esi.client import COMPATIBILITY_DATE, ESIClient, ESIUnavailable
from astracore.modules.pi.intel import area
from test_esi_client import run

@pytest.fixture(autouse=True)
def isolated_sovereignty_cache(monkeypatch):
    with db.session() as c:
        c.execute("DELETE FROM http_cache WHERE url LIKE '%/sovereignty/systems/%'")
    async def no_wait(seconds):
        pass
    monkeypatch.setattr(client, '_sleep', no_wait)
    monkeypatch.setattr(client, 'BUDGET', client._Budget())


SOV = {'solar_systems': [
    {'solar_system_id': 1, 'claim': {'alliance': {'alliance_id': 99000141}}},
    {'solar_system_id': 2, 'claim': {'faction': {'faction_id': 500001}}},
    {'solar_system_id': 3, 'claim': {'unclaimed': True}},
    {'solar_system_id': 4, 'claim': {'alliance': {'alliance_id': 99000142}}},
]}


def test_current_sovereignty_endpoint_maps_only_alliance_claims():
    result, requests = run(lambda request: httpx.Response(200, json=SOV), public.sov_systems)
    assert result == {1: 99000141, 2: None, 3: None, 4: 99000142}
    assert requests[0].url.path == '/latest/sovereignty/systems/'
    assert requests[0].headers['x-compatibility-date'] == COMPATIBILITY_DATE == '2026-08-18'


def test_sovereignty_preserves_public_cache_and_explicit_refresh():
    async def steps(esi):
        first = await public.sov_systems(esi)
        assert await public.sov_systems(esi) == first
        with db.session() as c:
            c.execute("UPDATE http_cache SET esi_expires=0 WHERE url LIKE '%/sovereignty/systems/%'")
        return await public.sov_systems(esi, force=True)
    result, requests = run(lambda request: httpx.Response(200, json=SOV), steps)
    assert result[1] == 99000141 and len(requests) == 2


@pytest.mark.parametrize('force', [False, True])
def test_sovereignty_outage_uses_stale_copy_only_without_explicit_refresh(force):
    path = 'https://esi.evetech.net/latest/sovereignty/systems/?'
    with db.session() as c:
        c.execute("REPLACE INTO http_cache(url, body, expires, esi_expires) VALUES(?,?,0,0)",
                  (path, json.dumps(SOV)))
    if force:
        with pytest.raises(ESIUnavailable):
            run(lambda request: httpx.Response(503), lambda esi: public.sov_systems(esi, force=True))
    else:
        result, _ = run(lambda request: httpx.Response(503), public.sov_systems)
        assert result[1] == 99000141


@pytest.mark.parametrize('query,expected', [('Synthetic alliance', [1]), ('Synthetic system', [2])])
def test_area_resolves_alliance_claims_and_keeps_faction_systems_unowned(query, expected):
    def handler(request):
        path = request.url.path.removeprefix('/latest')
        if path == '/sovereignty/systems/':
            return httpx.Response(200, json=SOV)
        if path == '/universe/ids/':
            ids = {'alliances': [{'id': 99000141, 'name': query}]} if query.endswith('alliance') else {
                'systems': [{'id': 2, 'name': query}]}
            return httpx.Response(200, json=ids)
        if path == '/universe/names/':
            return httpx.Response(200, json=[{'id': 10, 'name': 'Synthetic constellation'},
                                           {'id': 20, 'name': 'Synthetic region'},
                                           {'id': 99000141, 'name': 'Synthetic alliance'}])
        if path.startswith('/universe/systems/'):
            sid = int(path.split('/')[-2])
            return httpx.Response(200, json={'system_id': sid, 'name': 'Synthetic system',
                                           'constellation_id': 10, 'security_status': -0.5, 'planets': []})
        if path == '/universe/constellations/10/':
            return httpx.Response(200, json={'constellation_id': 10, 'region_id': 20, 'systems': [1, 2]})
        raise AssertionError(f'Unexpected endpoint: {path}')
    result, requests = run(handler, lambda esi: area.resolve(esi, query, force=True))
    assert sorted(int(s) for s in result['systems']) == expected
    system = result['systems'][str(expected[0])]
    assert system['sov_alliance_id'] == (99000141 if expected == [1] else None)
    assert system['sov_alliance'] == ('Synthetic alliance' if expected == [1] else '')
    assert not any('/sovereignty/map/' in str(r.url) for r in requests)
