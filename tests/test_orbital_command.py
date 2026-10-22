"""Operational state and responsive asset delivery use real app contracts."""
import re

import pytest

from astracore import db
from astracore.core import assets, registry
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401


@pytest.mark.parametrize("state,planned,built,href", [
    ("connect", 0, 0, "/pi"),
    ("plan", 0, 0, "/pi/plan"),
    ("operate", 12, 4, "/pi/operate#plan-status"),
    ("operate", 12, 12, "/pi/operate"),
])
def test_dashboard_action_follows_setup_and_colony_progress(browser, eve, monkeypatch, state, planned, built, href):
    client = browser()
    sso_login(client, eve, new_id(), "Operations test")
    db.update_profile(me(client), onboarded=1)

    async def tile(profile):
        result = {"state": state, "href": {"connect": "/pi",
                  "plan": "/pi/plan", "operate": "/pi/operate"}[state], "cta": "Continue"}
        if planned:
            result.update(planned=planned, built=built, plan_isk_per_day=7_300_000,
                          plan_label="Test plan", has_colonies=True, in_hangars=650_800_000,
                          earned_7d=8_200_000, synced_at=0, next_up=[])
        return result

    monkeypatch.setattr(registry.get("pi"), "dashboard_tile", tile)
    response = client.get("/")
    assert response.status_code == 200
    assert f'class="primary-link" href="{href}"' in response.text
    assert ('class="console-label">Build in progress' in response.text) == (built < planned)
    if planned:   # one plan line: forecast/day · built X/Y · earned 7d · in hangars (#109)
        assert (f"Forecast <b>7.3M</b> ISK/day · Built <b>{built} / {planned}</b> · Earned 7d <b>8.2M</b>"
                " · In hangars <b>650.8M</b>") in response.text
    else:
        assert 'class="plan-line"' not in response.text
    assert ('class="setup-path"' in response.text) == (state != "operate")


def test_responsive_sources_are_served_with_valid_hashes(browser):
    client = browser()
    for path in ('/', '/about', '/roadmap', '/credits'):
        response = client.get(path)
        assert response.status_code == 200
        for srcset in re.findall(r'srcset="([^"]+)"', response.text):
            widths = []
            for source in srcset.split(','):
                url, descriptor = source.strip().split()
                widths.append(int(descriptor[:-1]))
                assert descriptor.endswith('w')
                rel, _, version = url.partition('?v=')
                assert version != '0' and version == assets.version(rel)
                image = client.get(url)
                assert image.status_code == 200
                assert 'immutable' in image.headers['cache-control']
                assert image.headers['content-type'] == 'image/webp'
            assert widths == sorted(set(widths))
