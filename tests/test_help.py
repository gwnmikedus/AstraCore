"""The "?" help pattern and the glossary (#63)."""
from __future__ import annotations

import re

from astracore.modules.pi import glossary
from astracore.modules.pi.planner import compare, setups
from astracore.modules.pi.settings import Settings

from test_core import browser, eve, new_id, sso_login  # noqa: F401 (fixtures)
from test_planner import TEMPLATES, _plan, pi  # noqa: F401 (fixture)

REQUIRED_TERMS = ["drop-off", "batch", "transfer", "buffer", "restock", "buyback", "ccu", "p0-p4", "poco", "esi",
                  "voc", "dalshooth"]


def _guide_context(monkeypatch, calibrated=False):
    from astracore.modules.pi import service

    async def context(pid, **kwargs):
        return {"s": Settings(stack_yield_pct=70), "chars": [{"character_id": 1, "name": "Ready", "slots": 6,
                                                             "ccu_level": 5}],
                "systems": {}, "area": {}, "calibrated": calibrated, "head_yield": 1500, "dropoff": None,
                "seller": None}

    monkeypatch.setattr(service, "planning_context", context)


def test_glossary_page_lists_every_term_with_an_anchor(browser, eve):
    c = browser()
    sso_login(c, eve, new_id(), "Reader")
    r = c.get("/pi/glossary")
    assert r.status_code == 200
    for term in REQUIRED_TERMS:
        assert f'<dt id="{term}">' in r.text, term
    assert "Command Center Upgrades" in r.text and "VOC Hauling" in r.text
    assert 'href="/what-we-read"' in r.text
    assert "github.com/DalShooth" in r.text


def test_every_answer_links_to_a_glossary_entry_and_stays_short():
    ids = [g["id"] for g in glossary.GLOSSARY]
    assert len(ids) == len(set(ids))
    for key, a in glossary.answers(Settings(), 1500).items():
        assert a["more"] in glossary.TERMS, key
        assert a["label"].endswith("?"), key
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", a["text"]) if s]
        assert 1 <= len(sentences) <= 3, (key, a["text"])


def test_answers_follow_the_settings_and_the_time_yardstick():
    a = glossary.answers(Settings(stack_yield_pct=80), 1500)
    assert "80% of the first, the third at 64%" in a["share"]["text"]
    assert "1,500 P0 an hour" in a["yield"]["text"]
    assert "measured from your own extractors" in glossary.answers(Settings(), 1500, calibrated=True)["yield"]["text"]
    note = glossary.time_note()
    for minutes in (compare.MIN_PER_RESTART, compare.MIN_PER_SYSTEM_VISIT, compare.MIN_PER_RESTOCK):
        assert f"{minutes:g} min" in note


def test_guided_setup_has_the_help_toggles_and_no_time_paragraph(browser, eve, monkeypatch):
    c = browser()
    sso_login(c, eve, new_id(), "Guided")
    _guide_context(monkeypatch)
    html = c.get("/pi/plan").text
    assert re.search(r'<script src="/static/js/help\.js\?v=[^"]+"></script>', html)
    assert re.search(r'<script src="/static/js/plan-help\.js\?v=[^"]+"></script>', html)
    # the server-rendered "?" next to the yield estimate
    assert ('<button type="button" class="help-btn" aria-expanded="false" aria-controls="help-yield-head" '
            'aria-label="Why is yield an estimate?"') in html
    assert '<span class="help-answer" id="help-yield-head" hidden>' in html
    assert 'href="/pi/glossary#yield"' in html
    # the browser-side answers come from glossary.answers()
    assert "const HELP = {" in html and '"time":' in html and "const GLOSSARY = \"/pi/glossary\"" in html
    assert "AC.helpPartsFor(HELP.isk" in html and "'Your time / week' + timeHelp.button" in html
    assert "samePlanHTML(step, o, r, res)" in html
    assert "TIME_NOTE" not in html and "Time estimate: 1.5 min" not in html


def test_advanced_planner_loads_the_help_scripts(browser, eve, monkeypatch):
    c = browser()
    sso_login(c, eve, new_id(), "Advanced")
    _guide_context(monkeypatch, calibrated=True)
    html = c.get("/pi/plan?view=advanced").text
    assert "/static/js/help.js" in html and "/static/js/plan-help.js" in html
    assert "AC.tierHelp(res.tier_need)" in html


def test_p1_equivalent_counts_what_went_into_a_product(pi):  # noqa: F811
    assert setups.p1_equivalent(pi, 2396) == 1.0            # P1
    assert setups.p1_equivalent(pi, 2288) == 0.0            # P0
    assert setups.p1_equivalent(pi, 2329) == 16.0           # 40 + 40 P1 make 5 Biocells
    # 12 advanced factories, 80 P1 an hour each
    assert setups.factory_p1_need(pi, TEMPLATES, 2) == 80 * 12 * 24
    assert setups.factory_p1_need(pi, TEMPLATES, 3) is None


def test_plan_says_how_many_miners_a_higher_factory_needs(pi):  # noqa: F811
    res = _plan(pi, max_tier=2, prices={2329: 1.0, 9832: 1.0, 2396: 500.0, 2399: 500.0, 2390: 500.0, 3645: 500.0})
    need = res["tier_need"]
    assert need["allowed"] == 2 and need["used"] == 1
    miners = [c for c in res["colonies"] if c["kind"] == "miner"]
    assert need["miners"] == len(miners) > 0
    per_miner = sum(sum(c["out_per_day"].values()) for c in miners) / len(miners)
    assert need["factory_miners"]["2"] == max(1, round(80 * 12 * 24 / per_miner))
    assert "3" not in need["factory_miners"]
