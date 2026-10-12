"""Which characters PI can plan with: every character excluded (#120) and CCU too low (#57)."""
from __future__ import annotations

import asyncio

from astracore import db
from astracore.modules.pi import service
from astracore.modules.pi.planner import setups
from astracore.modules.pi.settings import Settings

from test_core import PI_SCOPES, browser, csrf, eve, me, new_id, sso_login  # noqa: F401 (fixtures)


def _ready(c, eve, name):
    cid = new_id()
    sso_login(c, eve, cid, name)
    db.save_token(cid, "rt", "at", 1199, PI_SCOPES)
    return cid


def test_every_character_excluded_lands_on_a_page_that_includes_them_again(browser, eve):
    c = browser()
    cid = _ready(c, eve, "Benched")
    pid = me(c)
    db.set_character(cid, enabled=0)
    assert service.entry_state(pid) == "excluded"

    r = c.get("/pi", follow_redirects=False)                     # no /pi -> /pi/area -> /pi loop
    assert r.status_code == 200
    assert "Every character is left out of the plan." in r.text
    assert f'action="/pi/characters/{cid}/toggle"' in r.text and ">Include</button>" in r.text
    for page in ("/pi/area", "/pi/plan"):                         # they send the pilot back to /pi, which explains
        r = c.get(page, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/pi"

    r = c.post(f"/pi/characters/{cid}/toggle", data={"back": "/pi", "csrf_token": csrf(c)}, follow_redirects=False)
    assert r.headers["location"] == "/pi"
    assert service.entry_state(pid) == "area"
    assert c.get("/pi", follow_redirects=False).headers["location"] == "/pi/area"


def test_dashboard_tile_points_an_all_excluded_profile_at_pi(browser, eve):
    c = browser()
    cid = _ready(c, eve, "Tiled")
    pid = me(c)
    db.set_character(cid, enabled=0)
    tile = asyncio.run(service.dashboard_tile({"id": pid}))
    assert (tile["state"], tile["href"], tile["cta"]) == ("excluded", "/pi", "Include a character")


def test_ccu_note_names_the_level_to_train():
    assert setups.ccu_note(0)["status"] == "bad" and not setups.can_plan({"ccu_level": 1})
    assert setups.ccu_note(1)["next"] == ("Train Command Center Upgrades to 2 to use this character for factories "
                                          "(4 recommended for nullsec miners).")
    assert setups.can_plan({"ccu_level": 2}) and setups.ccu_note(2)["label"] == "Most factories only"
    assert setups.ccu_note(3) == {"status": "warn", "label": "Factories only",
                                  "next": "Train Command Center Upgrades to 4 for nullsec miners (5 for lowsec)."}
    assert setups.ccu_note(4)["status"] == "ok" and setups.ccu_note(4)["next"] == ""
    assert setups.ccu_note(5) == {"status": "ok", "label": "OK for every template", "next": ""}


def test_thresholds_match_the_template_fitting_rule():
    """The levels in the advice are the lowest Command Center levels DalShooth's layouts fit (structure counts of
    the repo's four layouts, 2026-10)."""
    p2_factory = {"advanced": 12, "launchpads": 1}
    p4_factory = {"hightech": 8, "launchpads": 1}
    nullsec_miner = {"ecus": 1, "heads": 10, "basic": 8, "launchpads": 1, "storage": 1}
    lowsec_miner = {"ecus": 2, "heads": 16, "basic": 4, "launchpads": 1, "storage": 1}
    assert setups.template_min_ccu(p2_factory) == setups.FACTORY_CCU
    assert setups.template_min_ccu(p4_factory) == setups.ALL_FACTORIES_CCU
    assert setups.template_min_ccu(nullsec_miner) == setups.NULLSEC_MINER_CCU
    assert setups.template_min_ccu(lowsec_miner) == setups.LOWSEC_MINER_CCU
    from astracore.modules.pi.planner import optimizer
    assert optimizer.MINER_CCU == setups.NULLSEC_MINER_CCU


def test_guided_setup_says_early_which_characters_cant_be_planned(browser, eve, monkeypatch):
    c = browser()
    cid = _ready(c, eve, "Trainee")
    db.set_character(cid, ccu_level=1)
    chars = [{"character_id": cid, "name": "Trainee", "slots": 1, "ccu_level": 1}]

    async def context(pid):
        return {"s": Settings(), "chars": chars, "systems": {}, "area": {}, "calibrated": False,
                "head_yield": 1500, "dropoff": None, "seller": None}

    monkeypatch.setattr(service, "planning_context", context)
    r = c.get("/pi/plan")
    assert r.status_code == 200
    assert "const BLOCKED = 1;" in r.text and "see Characters in this plan" in r.text
    assert 'id="characters-panel"' in r.text
    assert "1 can't be planned yet" in r.text                   # on the collapsed panel's summary
    assert "Train Command Center Upgrades to 2 to use this character for factories" in r.text

    db.set_character(cid, ccu_level=5)
    chars[0]["ccu_level"] = 5
    r = c.get("/pi/plan")
    assert "const BLOCKED = 0;" in r.text and "can't be planned yet" not in r.text
