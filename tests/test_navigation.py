"""Navigation groups stay consistent across canonical pages and planner views."""
import pytest

from astracore import db
from astracore.core import registry
from astracore.modules.pi import service, store
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401
from test_experience import OutboundLinks
from test_planner import pi  # noqa: F401


@pytest.fixture()
def navigator(browser, eve, monkeypatch, pi):
    client = browser()
    sso_login(client, eve, new_id(), "Navigation pilot")
    db.update_profile(me(client), onboarded=1)

    async def no_space(chars, settings):
        return None

    async def context(profile_id):
        return {"chars": service.planning_characters(profile_id), "s": store.load_settings(profile_id),
                "pi": pi, "books": {}, "area": None, "systems": {}, "tpl": [],
                "calibrated": False, "head_yield": 9000, "dropoff": "", "seller": {}}

    async def tile(profile):
        return {"state": "plan", "href": "/pi/plan", "cta": "Build a plan"}

    monkeypatch.setattr(service, "load_space", no_space)
    monkeypatch.setattr(service, "planning_context", context)
    monkeypatch.setattr(registry.get("pi"), "dashboard_tile", tile)
    return client


def _links(html, marker, end="</nav>"):
    return OutboundLinks.parse(html.split(marker, 1)[1].split(end, 1)[0])


@pytest.mark.parametrize("path,selected,current", [
    ("/", "/", "page"),
    ("/pi/plan", "/pi/plan", "page"),
    ("/pi/plan?view=advanced", "/pi/plan", "page"),
    ("/pi/area", "/pi/plan", "true"),
    ("/pi/settings", "/pi/plan", "true"),
    ("/pi/operate", "/pi/operate", "page"),
    ("/profile", "/profile", "page"),
])
def test_operation_destinations_and_current_section(navigator, path, selected, current):
    response = navigator.get(path)
    assert response.status_code == 200, response.text
    shortcuts = _links(response.text, '<nav class="header-shortcuts"')
    assert [(link["text"].strip(), link["attrs"]["href"]) for link in shortcuts] == [
        ("Home", "/"), ("Plan", "/pi/plan"), ("Operate", "/pi/operate"), ("Characters", "/profile")]
    assert [(link["attrs"]["href"], link["attrs"]["aria-current"]) for link in shortcuts
            if "aria-current" in link["attrs"]] == [(selected, current)]
    operation = _links(response.text, '<h2 id="menu-operation-title">', "</section>")
    assert [link["attrs"]["href"] for link in operation] == ["/", "/pi/plan", "/pi/operate", "/profile"]
    assert [(link["attrs"]["href"], link["attrs"]["aria-current"]) for link in operation
            if "aria-current" in link["attrs"]] == [(selected, current)]
    assert 'class="brand" href="/" aria-label="AstraCore home"' in response.text


@pytest.mark.parametrize("path,selected", [
    ("/pi/plan", "/pi/plan"), ("/pi/plan?view=advanced", "/pi/plan"),
    ("/pi/area", "/pi/area"), ("/pi/settings", "/pi/settings"),
])
def test_area_and_settings_are_contextual_plan_links(navigator, path, selected):
    html = navigator.get(path).text
    setup = _links(html, 'aria-label="Plan setup"')
    assert [link["attrs"]["href"] for link in setup] == ["/pi/plan", "/pi/area", "/pi/settings"]
    assert [link["attrs"]["href"] for link in setup if link["attrs"].get("aria-current") == "page"] == [selected]
    assert 'href="/pi/plan?view=advanced"' in navigator.get("/pi/plan").text
    assert 'aria-label="Plan setup"' not in navigator.get("/pi/operate").text


@pytest.mark.parametrize("path", ["/about", "/project", "/credits", "/releases", "/roadmap",
                                  "/community", "/feedback?kind=bug", "/privacy", "/what-we-read"])
def test_information_pages_share_one_community_destination(navigator, path):
    response = navigator.get(path)
    assert response.status_code == 200
    community = _links(response.text, '<h2 id="menu-community-title">', "</section>")
    assert len(community) == 1
    assert community[0]["attrs"]["href"] == "/community"
    assert community[0]["attrs"]["aria-current"] == ("page" if path == "/community" else "true")


def test_community_hub_exposes_existing_information_routes(browser):
    html = browser().get("/community").text
    links = _links(html, 'aria-label="About AstraCore"')
    assert [link["attrs"]["href"] for link in links] == [
        "/about", "/project", "/credits#contributors", "/releases", "/what-we-read", "/privacy"]
    assert 'href="/feedback?kind=idea"' in html and 'href="/feedback?kind=bug"' in html
    assert 'href="#roadmap-title"' in html and 'href="#reports-title"' in html


@pytest.mark.parametrize("path,selected,current", [
    ("/", None, None), ("/about", "/about", "page"),
    ("/community", "/community", "page"), ("/roadmap", "/community", "true"),
    ("/project", "/community", "true"), ("/credits", "/community", "true"),
    ("/releases", "/community", "true"), ("/feedback?kind=bug", "/community", "true"),
    ("/privacy", "/community", "true"), ("/what-we-read", "/community", "true"),
])
def test_signed_out_shortcuts_have_one_current_destination(browser, path, selected, current):
    response = browser().get(path)
    assert response.status_code == 200
    links = _links(response.text, '<nav class="header-shortcuts"')
    assert [link["attrs"]["href"] for link in links] == ["/about#pi-today", "/about", "/community"]
    active = [(link["attrs"]["href"], link["attrs"]["aria-current"]) for link in links
              if "aria-current" in link["attrs"]]
    assert active == ([(selected, current)] if selected else [])


@pytest.mark.parametrize("admin", [False, True])
def test_admin_navigation_is_visible_only_to_admins(navigator, monkeypatch, admin):
    monkeypatch.setattr(db, "is_admin", lambda profile_id: admin)
    html = navigator.get("/about").text
    header = html.split('<header class="topbar site-header">', 1)[1].split('</header>', 1)[0]
    assert ('href="/admin"' in header) == admin


def test_signed_out_navigation_never_exposes_admin(browser):
    html = browser().get("/about").text
    header = html.split('<header class="topbar site-header">', 1)[1].split('</header>', 1)[0]
    assert 'href="/admin"' not in header


def test_menu_feedback_links_and_single_footer_community_destination(navigator):
    html = navigator.get("/about").text
    help_links = _links(html, 'aria-label="Help improve AstraCore"')
    assert [(link["text"].strip(), link["attrs"]["href"]) for link in help_links] == [
        ("Report a bug", "/feedback?kind=bug"), ("Suggest an idea", "/feedback?kind=idea")]
    footer = _links(html, '<footer class="site-footer">', '</footer>')
    assert [link["attrs"]["href"] for link in footer if link["attrs"]["href"] in ("/community", "/roadmap")] == ["/community"]
    assert '<h2 id="menu-plan-title">Plan setup</h2>' in html
