"""Production runs a pinned checkout, so env files and data must come from ASTRACORE_HOME, not the code's folder."""
import json
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PROBE = ("import json; from astracore import config as c; print(json.dumps({k: str(getattr(c, k)) for k in "
         "('ROOT', 'HOME', 'ENV_PATH', 'DATA_DIR', 'STATIC_DIR', 'BACKUP_DIR', 'LOG_DIR', 'RUN_DIR')}))")


def _paths(tmp_path, **env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("ASTRACORE_", "PI_PLANNER_"))}
    clean.update(PYTHONPATH=str(SRC), ASTRACORE_MODE="local", **env)
    out = subprocess.run([sys.executable, "-c", PROBE], env=clean, cwd=tmp_path, capture_output=True, text=True, check=True)
    return {k: Path(v) for k, v in json.loads(out.stdout).items()}


def test_home_holds_env_and_data_when_code_runs_elsewhere(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    p = _paths(tmp_path, ASTRACORE_HOME=str(home))
    assert p["ROOT"] == SRC.parent
    assert p["HOME"] == home.resolve()
    for key in ("ENV_PATH", "DATA_DIR", "STATIC_DIR", "BACKUP_DIR", "LOG_DIR", "RUN_DIR"):
        assert home.resolve() in p[key].parents, key
    assert p["ENV_PATH"].name == ".env.local"


def test_home_defaults_to_the_code_checkout(tmp_path):
    p = _paths(tmp_path, ASTRACORE_DATA=str(tmp_path / "data"), ASTRACORE_STATIC_DATA=str(tmp_path / "static"))
    assert p["HOME"] == p["ROOT"]
    assert p["ENV_PATH"] == p["ROOT"] / ".env.local"
