"""Every link to a section (`#id` or `/page#id`) on AstraCore's pages must land on an element with that id.

Guards against links that keep pointing at a section after it moved to another page (e.g. the creator story
moving from the landing page to /credits)."""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

import httpx
import pytest

from astracore import config
from test_core import browser, eve, new_id, sso_login  # noqa: F401 (fixtures)

PAGES = ("/", "/about", "/community", "/couriers", "/credits", "/feedback", "/glossary", "/privacy", "/project",
         "/releases", "/roadmap", "/what-we-read", "/welcome", "/profile", "/settings", "/area", "/plan",
         "/operate", "/pi", "/admin")
SKIP = ("/auth/", "/export/", "/api/", "/static/", "/profile/export", "/reset", "/profile/reset", "/pi/reset")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Crawling pages must not fetch market prices or anything else from the network."""
    async def refuse(self, request, *a, **kw):
        raise httpx.ConnectError("tests stay offline", request=request)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)


def _ids(page: str) -> set:
    return set(re.findall(r'\sid="([^"]+)"', page)) | set(re.findall(r'\sname="([^"]+)"', page))


def _markup(page: str) -> str:
    """The page without scripts: links inside JS templates render only in their own state."""
    return re.sub(r"<script\b.*?</script>", "", page, flags=re.S)


def _crawl(client) -> list:
    pages, broken = {}, []

    def get(path):
        if path not in pages:
            r = client.get(path)
            pages[path] = r.text if r.status_code == 200 and "text/html" in r.headers.get("content-type", "") else None
        return pages[path]

    queue, seen = list(PAGES), set()
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        page = get(path)
        if page is None:
            continue
        page = _markup(page)
        for href in re.findall(r'href="(/[^"#?]*)', page):      # follow every internal page, too
            if not href.startswith(SKIP) and href not in seen and len(seen) < 120:
                queue.append(href)
        for href in re.findall(r'href="([^"]*#[^"]*)"', page):
            href = html.unescape(href)
            parts = urlsplit(href)
            if parts.scheme or parts.netloc or not parts.fragment or parts.path.startswith(SKIP):
                continue
            target_path = parts.path or path
            target = page if not parts.path else get(target_path)
            target = target and _markup(target) if parts.path else target
            if target is not None and parts.fragment not in _ids(target):
                broken.append(f"{path}: {href}")
    return sorted(set(broken))


def test_section_links_land_on_a_section_for_visitors(browser):
    assert _crawl(browser()) == []


def test_section_links_land_on_a_section_for_a_signed_in_admin(browser, eve):
    admin_id = next(iter(config.ADMIN_CHARACTER_IDS))
    client = browser()
    sso_login(client, eve, new_id(), "Anchor main")
    sso_login(client, eve, admin_id, "Anchor admin", path="/auth/login?intent=add")
    assert _crawl(client) == []
