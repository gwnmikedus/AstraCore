"""A pilot's corporation or alliance moves to new space (#298): affiliations refresh for every character
(also one whose EVE login expired), a selection made for the old space is reset with a notice, and Operate and
Home say when the active plan's systems are outside the area.

Synthetic characters, alliances and systems only; ESI is never called.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from astracore import db
from astracore.esi import character as esi_char
from astracore.modules.pi import service, store
from astracore.modules.pi.intel import area as area_mod

from conftest import REAL_REFRESH_AFFILIATIONS
from test_core import browser, eve  # noqa: F401 (fixtures)
from test_next_up import _pilot

OLD, NEW = 99000001, 99000002
NAMES = {OLD: "Old Test Alliance", NEW: "New Test Alliance", 98000001: "Test Corp", 98000002: "Moved Corp"}


def _run(coro):
    """Run without asyncio.run, which leaves no current event loop for the next test's fixtures (Python 3.9)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeESI:
    """Answers the two public calls affiliation needs, and records them."""

    def __init__(self, affiliation):
        self.affiliation = affiliation     # {character id: (corporation id, alliance id or None)}
        self.posts = []

    async def post(self, path, body, ttl=None, stale_ok=False):
        self.posts.append((path, list(body), ttl))
        if path == "/characters/affiliation/":
            return [{"character_id": i, "corporation_id": self.affiliation[i][0],
                     **({"alliance_id": self.affiliation[i][1]} if self.affiliation[i][1] else {})}
                    for i in body if i in self.affiliation]
        if path == "/universe/names/":
            return [{"id": i, "name": NAMES[i]} for i in body if i in NAMES]
        raise AssertionError(path)


def _system(sid, name, con, alliance=None):
    return {"system_id": sid, "name": name, "security": -0.3, "constellation_id": con, "constellation": f"Con {con}",
            "region": "Test Region", "neighbours": [], "exits": 0, "sov_alliance_id": alliance, "sov_alliance": "",
            "planets": [{"planet_id": sid * 10 + i, "name": f"{name} {i}", "type": "Barren"} for i in range(1, 4)]}


def _area(alliances, *systems):
    return {"query": ", ".join(alliances), "found": [], "systems": {str(s["system_id"]): s for s in systems},
            "sources": {"alliances": list(alliances), "colony_constellations": [], "extra": []}}


def _in_alliance(cid, alliance_id):
    db.set_character(cid, corporation_id=98000001, corporation_name="Test Corp", alliance_id=alliance_id,
                     alliance_name=NAMES[alliance_id])


# --------------------------------------------------------------------------- affiliation refresh
@pytest.fixture
def real_refresh(monkeypatch):
    monkeypatch.setattr(esi_char, "refresh_affiliations", REAL_REFRESH_AFFILIATIONS)


def test_affiliations_are_one_cached_public_call_for_many_characters():
    esi = FakeESI({1: (98000001, OLD), 2: (98000002, None)})
    out = _run(esi_char.affiliations(esi, [2, 1, 2]))
    assert esi.posts[0] == ("/characters/affiliation/", [1, 2], 3600)     # one batch, ESI's cache time kept
    assert out[1]["alliance_name"] == "Old Test Alliance" and out[1]["corporation_name"] == "Test Corp"
    assert out[2]["alliance_id"] is None and out[2]["alliance_name"] == ""
    single = _run(esi_char.affiliation(FakeESI({}), 3))           # unknown: blank, as before
    assert single == {"corporation_id": None, "corporation_name": "", "alliance_id": None, "alliance_name": ""}


def test_refresh_profile_updates_the_alliance_of_a_character_whose_login_expired(browser, eve, monkeypatch,
                                                                                 real_refresh):
    c = browser()
    cid, pid = _pilot(c, eve, "Moved Pilot")
    _in_alliance(cid, OLD)
    db.set_character(cid, status="needs_login")
    synced = []

    async def sync(esi, character_id):       # a full refresh needs the expired login: it fails
        synced.append(character_id)
        raise RuntimeError("no token")

    esi = FakeESI({cid: (98000002, NEW)})

    real = esi_char.affiliations

    async def affiliations(_esi, ids):     # the real batching, answered by the fake ESI
        return await real(esi, ids)

    monkeypatch.setattr(esi_char, "sync_character", sync)
    monkeypatch.setattr(esi_char, "affiliations", affiliations)
    problems = _run(service.refresh_profile(pid))
    assert synced == [cid] and problems
    ch = db.get_character(cid)
    assert (ch["alliance_id"], ch["alliance_name"], ch["corporation_name"]) == (NEW, "New Test Alliance", "Moved Corp")
    assert [p for p, *_ in esi.posts].count("/characters/affiliation/") == 1
    # the selection was made for the old alliance: noted, so the next area load resets it
    assert db.kv_get(service.SPACE_ALLIANCES_KEY + str(pid)) == ["Old Test Alliance"]


def test_affiliation_refresh_never_blanks_a_known_alliance(browser, eve, real_refresh):
    c = browser()
    cid, pid = _pilot(c, eve, "Unresolved Pilot")
    _in_alliance(cid, OLD)
    esi = FakeESI({cid: (98000001, 99000777)})          # a new alliance whose name ESI didn't resolve
    changed = _run(service.refresh_affiliations(esi, service.planning_characters(pid)))
    assert changed == [] and db.get_character(cid)["alliance_name"] == "Old Test Alliance"

    class Down:
        async def post(self, *a, **kw):
            raise RuntimeError("ESI down")

    assert _run(service.refresh_affiliations(Down(), service.planning_characters(pid))) == []


# --------------------------------------------------------------------------- the selection follows the space
def test_selection_for_the_old_space_is_reset_once_with_a_notice(browser, eve):
    c = browser()
    cid, pid = _pilot(c, eve, "Reset Pilot")
    _in_alliance(cid, OLD)
    old_area = _area(["Old Test Alliance"], _system(30000001, "Old-A", 1, OLD), _system(30000002, "Old-B", 2, OLD))
    s = store.load_settings(pid)
    s.selected_constellations = [2]
    chars = service.planning_characters(pid)
    assert service.reconcile_space(pid, chars, old_area, s) is None        # first look: just remembered
    assert s.selected_constellations == [2]

    _in_alliance(cid, NEW)
    chars = service.planning_characters(pid)
    new_area = _area(["New Test Alliance"], _system(30000001, "Old-A", 1, OLD), _system(30000002, "Old-B", 2, OLD),
                     _system(30000101, "New-A", 7, NEW), _system(30000102, "New-B", 8, NEW))
    note = service.reconcile_space(pid, chars, new_area, s)
    assert "Old Test Alliance" in note and "New Test Alliance" in note
    assert s.selected_constellations and store.load_settings(pid).selected_constellations == s.selected_constellations
    assert service.space_notice(pid) == note
    assert service.space_notice(pid, now=time.time() + service.SPACE_NOTICE_FOR + 1) is None
    # the pilot's own choice in the new space sticks
    s.selected_constellations = [8]
    assert service.reconcile_space(pid, chars, new_area, s) is None and s.selected_constellations == [8]


def test_selection_outside_the_area_is_reset_but_not_from_an_area_for_other_alliances(browser, eve):
    c = browser()
    cid, pid = _pilot(c, eve, "Lost Pilot")
    _in_alliance(cid, NEW)
    chars = service.planning_characters(pid)
    s = store.load_settings(pid)
    s.selected_constellations = [55]
    stale = _area(["Old Test Alliance"], _system(30000001, "Old-A", 1, OLD))   # ESI down: the last area shown
    assert service.reconcile_space(pid, chars, stale, s) is None and s.selected_constellations == [55]
    area = _area(["New Test Alliance"], _system(30000101, "New-A", 7, NEW))
    assert "no longer in your area" in service.reconcile_space(pid, chars, area, s)
    assert s.selected_constellations == [7]


def test_area_page_explains_the_reset_until_the_pilot_saves(browser, eve, monkeypatch):
    c = browser()
    cid, pid = _pilot(c, eve, "Notice Pilot")
    _in_alliance(cid, NEW)
    db.kv_set(service.SPACE_ALLIANCES_KEY + str(pid), ["Old Test Alliance"])
    area = _area(["New Test Alliance"], _system(30000101, "New-A", 7, NEW))

    async def load_space(chars, s, **kw):
        return area

    monkeypatch.setattr(service, "load_space", load_space)
    html = c.get("/pi/area").text
    assert "Your alliance changed" in html and store.load_settings(pid).selected_constellations == [7]
    assert "Your alliance changed" in c.get("/pi/area").text                 # shown again on the next visit
    from test_core import csrf
    r = c.post("/pi/area", data={"csrf_token": csrf(c), "con": "7"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert service.space_notice(pid) is None and "Your alliance changed" not in c.get("/pi/area").text


# --------------------------------------------------------------------------- the active plan outside the area
PLAN = {"totals": {"isk_per_day": 1e6}, "hub": "Old-Hub", "hub_id": 30000009, "colonies": [
    {"character_id": 1, "planet_id": 300000011, "system": "Old-A", "system_id": 30000001, "kind": "miner"}]}


def test_plan_outside_area_compares_colonies_with_the_selection_and_the_dropoff_with_the_area():
    area = _area(["New Test Alliance"], _system(30000001, "Old-A", 1, OLD), _system(30000009, "Old-Hub", 3),
                 _system(30000101, "New-A", 7, NEW))
    systems = lambda cons: {int(k): v for k, v in area["systems"].items() if v["constellation_id"] in cons}  # noqa: E731
    assert service.plan_outside_area(PLAN, area, systems([1])) == []          # drop-off may sit outside the selection
    assert service.plan_outside_area(PLAN, area, systems([7])) == ["Old-A"]
    moved = _area(["New Test Alliance"], _system(30000101, "New-A", 7, NEW))
    assert service.plan_outside_area(PLAN, moved, systems([7])) == ["Old-A", "Old-Hub"]
    assert service.plan_outside_area(PLAN, None, {}) == [] and service.plan_outside_area(None, moved, {}) == []


def test_operate_and_home_ask_to_replan_when_the_plan_left_the_area(browser, eve, monkeypatch):
    c = browser()
    cid, pid = _pilot(c, eve, "Banner Pilot")
    _in_alliance(cid, NEW)
    store.save_plan_run(pid, "old space", store.load_settings(pid), PLAN, active=True)
    area = _area(["New Test Alliance"], _system(30000101, "New-A", 7, NEW))
    s = store.load_settings(pid)
    s.selected_constellations = [7]
    store.save_settings(pid, s)
    chars = service.planning_characters(pid)
    db.kv_set(area_mod.AREA_KEY + area["query"].lower(), area)            # what Operate left for Home
    db.kv_set(service._area_owner(chars, s), area["query"])
    assert service.home_space_warning(pid) == ["Old-A", "Old-Hub"]

    async def ctx(profile_id, *a, **kw):
        return {"chars": service.planning_characters(profile_id), "pi": None, "s": store.load_settings(profile_id),
                "books": {}, "area": area, "tpl": [], "systems": {30000101: area["systems"]["30000101"]}}

    monkeypatch.setattr(service, "planning_context", ctx)
    monkeypatch.setattr(service, "first_build", lambda ctx, active: None)
    monkeypatch.setattr(service, "restock_purchases", lambda ctx, active: None)
    operate = c.get("/pi/operate").text
    assert "Your space changed: this plan" in operate and "Old-A, Old-Hub" in operate
    assert 'href="/pi/plan">Replan' in operate
    home = c.get("/").text
    assert "Your space changed: this plan" in home and 'href="/pi/plan">Replan' in home

    # replanned inside the area: no banner
    store.save_plan_run(pid, "new space", s, {**PLAN, "hub": "New-A", "hub_id": 30000101, "colonies": [
        {**PLAN["colonies"][0], "system": "New-A", "system_id": 30000101}]}, active=True)
    assert service.home_space_warning(pid) == []
    assert "Your space changed" not in c.get("/pi/operate").text and "Your space changed" not in c.get("/").text
