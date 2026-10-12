"""First-run area suggestions and searches remain read-only until confirmation."""
from astracore import db
from astracore.modules.pi import service, store
from test_core import PI_SCOPES, browser, csrf, eve, me, new_id, sso_login  # noqa: F401
from test_planner import _area


def setup(client, eve):
    cid = new_id()
    sso_login(client, eve, cid, 'Fictional area pilot')
    db.save_token(cid, 'rt', 'at', 1199, PI_SCOPES)
    db.set_character(cid, ccu_level=5, slots=2)
    return me(client)


def test_entry_starts_goal_without_saved_area(browser, eve):
    c = browser()
    pid = setup(c, eve)
    assert not store.has_settings(pid)
    assert c.get('/pi', follow_redirects=False).headers['location'] == '/pi/plan'
    assert not store.has_settings(pid)


def test_area_suggestion_get_does_not_save_a_default(browser, eve, monkeypatch):
    c = browser()
    pid = setup(c, eve)
    async def area(chars, s, **kw):
        return _area()
    monkeypatch.setattr(service, 'load_space', area)
    assert c.get('/pi/area').status_code == 200
    response = c.get('/pi/api/area')
    assert response.status_code == 200 and response.json()['selected']
    assert not store.has_settings(pid)


def test_search_uses_experimental_region_without_changing_saved_settings(browser, eve, monkeypatch):
    c = browser()
    pid = setup(c, eve)
    s = store.load_settings(pid)
    s.answered = ['goal', 'cycle']
    s.guide_step = 2
    store.save_settings(pid, s)
    original = store.load_settings(pid).to_json()
    seen = []
    async def area(chars, s, **kw):
        seen.append(s.extra_area)
        return _area() if s.extra_area == 'The Forge' else None
    monkeypatch.setattr(service, 'load_space', area)
    assert c.get('/pi/api/area').json()['selected'] == []
    response = c.get('/pi/api/area?extra_area=The%20Forge')
    assert response.json()['selected'] and seen[-1] == 'The Forge'
    assert store.load_settings(pid).to_json() == original
    confirmed = response.json()['selected']
    r = c.post('/pi/api/save', json={'selected_constellations': confirmed, 'extra_area': 'The Forge',
                                   'answered': ['goal', 'cycle', 'area'], 'guide_step': 3},
               headers={'X-CSRF-Token': csrf(c)})
    assert r.json()['ok']
    saved = store.load_settings(pid)
    assert saved.selected_constellations == confirmed and saved.extra_area == 'The Forge'
    assert saved.answered == ['goal', 'cycle', 'area']


def test_guided_get_keeps_context_suggestions_unsaved(browser, eve, monkeypatch):
    c = browser()
    pid = setup(c, eve)
    async def context(profile_id, **kwargs):
        assert kwargs["persist_default"] is False
        s = store.load_settings(profile_id)
        s.selected_constellations = [20000001]
        return {"s": s, "chars": [{"character_id": 1, "slots": 2, "ccu_level": 5}],
                "systems": {}, "area": {}, "calibrated": False, "head_yield": 1500,
                "dropoff": None, "seller": None}
    monkeypatch.setattr(service, "planning_context", context)
    html = c.get("/pi/plan").text
    import json
    import re
    encoded = re.search(r"const S = JSON.parse\((.*?)\);", html).group(1)
    assert json.loads(json.loads(encoded))["selected_constellations"] == []
    assert not store.has_settings(pid)


def test_area_preview_coverage_matches_search_and_dropoff_without_saving(browser, eve, monkeypatch):
    c = browser()
    pid = setup(c, eve)
    async def area(chars, s, **kwargs):
        if not s.extra_area:
            return None
        result = _area()
        for system in result["systems"].values():
            system["region"] = "Delve" if s.extra_area == "Covered region" else "Fictional remote region"
        result["systems"]["3"]["region"] = "Fictional remote region"
        return result
    monkeypatch.setattr(service, "load_space", area)
    assert not c.get('/pi/api/area').json()['selling_coverage']['local']
    covered = c.get('/pi/api/area', params={'extra_area': 'Covered region', 'hub_system': 'HUB'})
    assert covered.json()['selling_coverage']['local'] is True
    remote = c.get('/pi/api/area', params={'extra_area': 'Remote region', 'hub_system': 'HUB'})
    assert not any(remote.json()['selling_coverage'].values())
    changed_hub = c.get('/pi/api/area', params={'extra_area': 'Covered region',
                                              'selected_constellations': '1', 'hub_system': 'FAR'})
    assert not any(changed_hub.json()['selling_coverage'].values())
    empty = c.get('/pi/api/area', params={'extra_area': 'Covered region',
                                        'selected_constellations': '', 'hub_system': 'HUB'})
    assert empty.json()['selected'] == []
    assert not any(empty.json()['selling_coverage'].values())
    assert not store.has_settings(pid)
