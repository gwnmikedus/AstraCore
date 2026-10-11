"""Release identity, publishing consistency, and public discovery."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from astracore.core import releases


def _data():
    return json.loads(releases.RELEASE_DATA.read_text(encoding="utf-8"))


def test_packaged_history_is_minor_releases_only():
    data = _data()
    releases.validate(data)
    assert data["current_version"].startswith("0.") and data["current_version"].endswith(".0")
    assert all(entry["version"].endswith(".0") for entry in data["releases"])


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(current_version="0.1.3"),                       # patch numbers come from git
    lambda data: data["releases"][0].update(version="0.1.3"),
])
def test_patch_versions_are_never_written_down(mutation):
    data = _data()
    mutation(data)
    with pytest.raises(ValueError):
        releases.validate(data)


@pytest.fixture()
def described(monkeypatch):
    """Pretend the checkout is `git describe`d as the given string."""
    def use(text):
        monkeypatch.setattr(releases, "_describe", lambda base: text)
        releases.build.cache_clear()
    yield use
    releases.build.cache_clear()


def test_patch_number_is_the_commits_since_the_minor_tag(described, monkeypatch):
    monkeypatch.delenv("ASTRACORE_COMMIT", raising=False)
    base = releases.current()["base"]
    described(f"v{base}-12-gabc1234")
    cur = releases.current()
    assert cur["version"] == base.rsplit(".", 1)[0] + ".12" and cur["patch"] == 12
    assert cur["commit"] == "abc1234" and cur["changes_url"].endswith(f"/compare/v{base}...abc1234")
    described(f"v{base}-0-gabc1234")                     # the release commit itself
    assert releases.current()["version"] == base and releases.current()["changes_url"] == ""
    described("")                                        # no git or no tag: the minor version
    assert releases.current()["version"] == base and releases.current()["commit"] == ""


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(current_version="9.9.0"),                      # must match the newest release
    lambda data: data["releases"].append(copy.deepcopy(data["releases"][0])),
    lambda data: data["releases"][0].update(date=None),
    lambda data: data["releases"][0].update(date="2026-02-30"),
    lambda data: data["releases"][0].update(changes=[""]),
    lambda data: data["releases"][0].update(references=[{"label": "Unsafe", "url": "javascript:alert(1)"}]),
])
def test_invalid_release_history_is_rejected(mutation):
    data = _data()
    mutation(data)
    with pytest.raises(ValueError):
        releases.validate(data)


def test_package_mismatch_is_rejected():
    with pytest.raises(ValueError, match="package version"):
        releases.validate(_data(), "9.9.0")


def test_commit_identity_is_optional_and_validated(monkeypatch, described):
    described("")
    monkeypatch.setenv("ASTRACORE_COMMIT", "../private-path")
    assert releases.current()["commit_url"] == ""
    monkeypatch.setenv("ASTRACORE_COMMIT", "abc1234")
    assert releases.current()["commit_url"] == "https://github.com/gwnmikedus/AstraCore/commit/abc1234"


def test_project_and_release_history_are_public():
    from astracore.app import app
    with TestClient(app) as client:
        project = client.get("/project")
        history = client.get("/releases")
        home = client.get("/")
    assert project.status_code == history.status_code == 200
    assert "PolyForm Noncommercial 1.0.0" in project.text
    assert 'href="https://github.com/gwnmikedus/AstraCore"' in project.text
    assert 'href="/project"' in home.text
    assert f"v{releases.current()['version']}" in home.text
    assert 'id="release-technical"' in history.text
    assert 'role="switch"' in history.text
    assert 'aria-controls="release-history"' in history.text
    assert 'data-release-technical open' not in history.text
    assert f'id="release-{releases.current()["base"]}"' in history.text and "Running here" in history.text


def test_release_page_links_the_smaller_updates_since_the_minor_release(described):
    from astracore.app import app
    base = releases.current()["base"]
    described(f"v{base}-3-gabc1234")
    with TestClient(app) as client:
        history = client.get("/releases").text
        home = client.get("/").text
    assert "3 smaller updates" in history and f"/compare/v{base}...abc1234" in history
    assert f'href="/releases#release-{base}">v{base.rsplit(".", 1)[0]}.3</a>' in home
