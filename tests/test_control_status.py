"""`./astracore status --json` is what AstraCore Control.app reads; keep its shape stable."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "astracore"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_status_json_when_nothing_runs(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    shutil.copy(SCRIPT, home / "astracore")
    (home / ".env.production").write_text("ASTRACORE_PUBLIC_URL=https://example.test\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASTRACORE_")}
    out = subprocess.run(["bash", str(home / "astracore"), "status", "--json"], cwd=home, env=env,
                         capture_output=True, text=True, timeout=60, check=True)
    status = json.loads(out.stdout)
    assert status["home"] == str(home)
    assert status["app"] == {"running": False, "mode": None, "pid": None, "healthy": False, "url": None}
    assert status["tunnel"] == {"running": False, "pid": None}
    assert status["urls"] == {"production": "https://example.test", "local": "http://localhost:8765"}
    prod = status["production"]
    assert prod["exists"] is False and prod["commit"] is None and prod["undeployed"] is None
    assert prod["checkout"] == f"{home}-production"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_plain_status_is_unchanged(tmp_path):
    shutil.copy(SCRIPT, tmp_path / "astracore")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASTRACORE_")}
    out = subprocess.run(["bash", str(tmp_path / "astracore"), "status"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=60, check=True)
    assert out.stdout.splitlines()[0] == "App:    stopped"
