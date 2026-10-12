"""Mode, paths and secrets.

Astracore runs in one of two modes (`ASTRACORE_MODE`, set by `./astracore start [--prod]`):

* ``local``      -> `.env.local`      + `data/local/`      (http://localhost:8765)
* ``production`` -> `.env.production` + `data/production/` (the public URL, through the tunnel)

Each mode has its own EVE application, env file and database, because EVE refresh tokens
only work with the application (client id) that issued them.

Secrets are read from the env file and never logged.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]   # src/astracore/config.py -> repo root (the code that runs)
# Where env files and data/ live. Production runs a pinned checkout (`./astracore deploy`) whose code sits
# elsewhere, so the launcher points this at the maintainer's checkout. Defaults to ROOT.
HOME = Path(os.environ.get("ASTRACORE_HOME") or ROOT).resolve()
MODE = os.environ.get("ASTRACORE_MODE", "local").strip().lower()
if MODE not in ("local", "production"):
    raise SystemExit(f"ASTRACORE_MODE must be 'local' or 'production', not {MODE!r}")
PRODUCTION = MODE == "production"

ENV_PATH = Path(os.environ.get("ASTRACORE_ENV_FILE", HOME / f".env.{MODE}"))
LEGACY_ENV_PATH = HOME / ".env"   # MVP file; only read when `.env.local` doesn't exist yet


def _parse_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_env() -> Dict[str, str]:
    """Values from the mode's env file; process environment variables win."""
    path = ENV_PATH if ENV_PATH.exists() or PRODUCTION else LEGACY_ENV_PATH
    env = _parse_env(path)
    for k, v in os.environ.items():
        if k.startswith(("ASTRACORE_", "EVE_", "PI_PLANNER_")):
            env[k] = v
    return env


def save_env(updates: Dict[str, Optional[str]]) -> None:
    """Add/replace keys in the mode's env file, keeping comments and order (chmod 600)."""
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    todo = {k: v for k, v in updates.items() if v is not None}
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in todo:
            out.append(f"{key}={todo.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in todo.items()]
    ENV_PATH.write_text("\n".join(out) + "\n")
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass


_ENV = load_env()


def env(key: str, default: str = "", legacy: Optional[str] = None) -> str:
    """One setting; `legacy` is the old PI_PLANNER_* name, still read for one release."""
    if key in _ENV and _ENV[key] != "":
        return _ENV[key]
    if legacy and _ENV.get(legacy):
        return _ENV[legacy]
    return default


def _ids(key: str) -> List[int]:
    return [int(x) for x in env(key).replace(" ", "").split(",") if x.strip().isdigit()]


def _data_dir() -> Path:
    raw = env("ASTRACORE_DATA", legacy="PI_PLANNER_DATA") or f"data/{MODE}"
    p = Path(raw)
    return p if p.is_absolute() else HOME / p


HOST = "127.0.0.1"   # the tunnel is the only way in
PORT = int(env("ASTRACORE_PORT", "8765", legacy="PI_PLANNER_PORT"))
PUBLIC_URL = env("ASTRACORE_PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")

DATA_DIR = _data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "astracore.sqlite3"
# Non-personal downloads (SDE csv, DalShooth templates) are shared by both modes.
STATIC_DIR = Path(env("ASTRACORE_STATIC_DATA") or HOME / "data")
STATIC_DIR.mkdir(parents=True, exist_ok=True)
LEGACY_DB_PATH = HOME / "data" / "pi_planner.sqlite3"   # the MVP database (migrated into data/local)

BACKUP_DIR = HOME / "data" / "backups"
LOG_DIR = HOME / "data" / "logs"
RUN_DIR = HOME / "data" / "run"

ADMIN_CHARACTER_IDS = set(_ids("ASTRACORE_ADMIN_CHARACTER_IDS"))
ALLOWED = {
    "character": set(_ids("ASTRACORE_ALLOWED_CHARACTERS")),
    "corporation": set(_ids("ASTRACORE_ALLOWED_CORPS")),
    "alliance": set(_ids("ASTRACORE_ALLOWED_ALLIANCES")),
}
ACCESS_GATE = PRODUCTION or env("ASTRACORE_ACCESS_GATE") == "1"


def default_solve_concurrency(cpus: Optional[int]) -> int:
    """Plans solved at once when ASTRACORE_SOLVE_CONCURRENCY isn't set: half the CPU cores, 2 to 4.
    Each solve uses one core (CBC with threads=1); the other half stays free for the web server, ESI syncs
    and the rest of the Mac."""
    return max(2, min(4, (cpus or 2) // 2))


def solve_concurrency(setting: str, cpus: Optional[int]) -> int:
    """ASTRACORE_SOLVE_CONCURRENCY when set (at least 1), otherwise the CPU-based default."""
    return max(1, int(setting)) if setting.strip() else default_solve_concurrency(cpus)


SOLVE_CONCURRENCY = solve_concurrency(env("ASTRACORE_SOLVE_CONCURRENCY"), os.cpu_count())
SECURE_COOKIES = PUBLIC_URL.startswith("https://")


def callback_url() -> str:
    """Must match the Callback URL registered on developers.eveonline.com exactly."""
    return env("EVE_CALLBACK_URL") or f"{PUBLIC_URL}/auth/callback"


def sso_credentials() -> tuple:
    return env("EVE_CLIENT_ID"), env("EVE_CLIENT_SECRET")


def token_key() -> str:
    return env("ASTRACORE_TOKEN_KEY")


def session_secret() -> str:
    return env("ASTRACORE_SESSION_SECRET")


def missing_production_secrets() -> List[str]:
    need = ["EVE_CLIENT_ID", "EVE_CLIENT_SECRET", "ASTRACORE_TOKEN_KEY", "ASTRACORE_SESSION_SECRET",
            "ASTRACORE_PUBLIC_URL"]
    return [k for k in need if not env(k)]
