"""Printing a plan (#60) and the guided setup on phones (#96, #119)."""
from __future__ import annotations

import re
from pathlib import Path

from astracore.core import assets
from astracore.modules.pi.settings import Settings

from test_core import browser, eve, new_id, sso_login  # noqa: F401 (fixtures)

STATIC = Path(__file__).resolve().parents[1] / "src" / "astracore" / "static"


def _rules(css: str, selector: str) -> str:
    """The declarations of every rule whose selector list contains `selector`."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
             if selector in [s.strip() for s in sel.split(",")]]
    assert found, selector
    return " ".join(found)


def test_every_page_links_the_print_stylesheet(browser):
    html = browser().get("/").text
    link = re.search(r'<link rel="stylesheet" href="(/static/css/print\.css\?v=[^"]+)" media="print">', html)
    assert link and link.group(1).endswith(assets.version("/static/css/print.css"))


def test_print_stylesheet_hides_chrome_and_keeps_tables_readable():
    css = (STATIC / "css" / "print.css").read_text()
    hidden = _rules(css, ".site-header")
    assert "display: none" in hidden
    for chrome in (".section-navigation", ".site-footer", ".characters-panel", ".page-guide .track",
                   ".guide-progress", ".toolbar", "button", ".page-guide .nav"):
        assert "display: none" in _rules(css, chrome), chrome
    assert "overflow: visible" in _rules(css, ".scroll")
    assert "table-header-group" in _rules(css, "thead")
    assert "break-inside: avoid" in _rules(css, ".who")
    assert "nowrap" in _rules(css, ".who td:first-child")
    assert "--void: #ffffff" in _rules(css, ":root[data-theme]")          # light paper in either theme
    # The build checklist prints alone.
    assert "display: none" in _rules(css, "html.print-checklist body > :not(.print-checklist-sheet)")


def test_plan_offers_a_printable_build_checklist():
    render = (STATIC.parent / "modules" / "pi" / "templates" / "pi" / "_plan_render.html").read_text()
    assert "data-print-checklist" in render and "AC.printChecklist(PRINT_PLAN)" in render
    for page in ("guide.html", "planner.html"):
        template = (STATIC.parent / "modules" / "pi" / "templates" / "pi" / page).read_text()
        assert "js/print-checklist.js" in template, page


def test_page_rules_for_details_never_move_the_menu():
    # .page-area details once pushed the fixed menu 16px down, onto the Plan sub-navigation (#119).
    css = (STATIC / "css" / "astracore.css").read_text()
    assert ".page-area details" not in css
    assert "margin: 0" in _rules(css, ".site-header details.site-menu")


def test_guide_names_the_step_and_folds_the_hero(browser, eve, monkeypatch):
    from astracore.modules.pi import service

    c = browser()
    sso_login(c, eve, new_id(), "Phone")

    async def context(pid):
        return {"s": Settings(), "chars": [{"character_id": 1, "name": "Ready", "slots": 6, "ccu_level": 5}],
                "systems": {}, "area": {}, "calibrated": False, "head_yield": 1500, "dropoff": None, "seller": None}

    monkeypatch.setattr(service, "planning_context", context)
    html = c.get("/pi/plan").text
    assert '<p class="g-head-line">Plan · 1 character · 6 slots' in html
    assert 'id="step-name"' in html
    assert "document.body.classList.toggle('guide-later', cur > 0)" in html
    assert "AC.tourScroll(" in html
    css = (STATIC / "css" / "astracore.css").read_text()
    assert "min-height: 56px" in _rules(css, ".page-guide .q .nav")
