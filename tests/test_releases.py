"""Release identity, publishing consistency, and public discovery."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from astracore.core import releases


def _data():
    return json.loads(releases.RELEASE_DATA.read_text(encoding="utf-8"))


def test_packaged_history_has_honest_baseline():
    data = _data()
    releases.validate(data)
    baseline = next(entry for entry in data["releases"] if entry["version"] == "1.0.0")
    assert baseline["kind"] == "baseline"
    assert baseline["date"] is None


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(current_version=data["releases"][-1]["version"]),
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
        releases.validate(_data(), "9.9.9")


def test_commit_identity_is_optional_and_validated(monkeypatch):
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
    assert "date not recorded" in history.text
