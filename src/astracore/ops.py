"""Operational helpers for the ./astracore script.

    python -m astracore.ops check     # production: refuse if secrets are missing (exit 1)
    python -m astracore.ops backup    # SQLite backup to data/backups/<mode>/, keeps the newest 14
    python -m astracore.ops migrate   # run pending database migrations

Secrets are never printed: only the names of missing keys.
"""
from __future__ import annotations

import sys
import time

from . import config, db

KEEP_BACKUPS = 14


def check() -> int:
    if not config.ENV_PATH.exists():
        print(f"Missing {config.ENV_PATH.name}.")
        return 1
    if config.PRODUCTION:
        missing = config.missing_production_secrets()
        if not config.env("CLOUDFLARE_TUNNEL_TOKEN"):
            missing.append("CLOUDFLARE_TUNNEL_TOKEN")
        if missing:
            print("Missing in .env.production: " + ", ".join(missing))
            return 1
        if not config.PUBLIC_URL.startswith("https://"):
            print("ASTRACORE_PUBLIC_URL must be https:// in production.")
            return 1
    return 0


def backup() -> int:
    if not config.DB_PATH.exists():
        print("No database yet; nothing to back up.")
        return 0
    folder = config.BACKUP_DIR / config.MODE
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / time.strftime("astracore-%Y%m%d-%H%M.sqlite3")
    db.backup(dest)
    dest.chmod(0o600)
    old = sorted(folder.glob("astracore-*.sqlite3"))[:-KEEP_BACKUPS]
    for f in old:
        f.unlink()
    print(f"Backup: {dest.relative_to(config.ROOT)} ({len(old)} old removed)")
    return 0


def migrate() -> int:
    db.adopt_legacy_db()
    v = db.migrate()
    try:
        config.DB_PATH.chmod(0o600)
    except OSError:
        pass
    print(f"Database at schema version {v}.")
    return 0


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    fn = {"check": check, "backup": backup, "migrate": migrate}.get(cmd)
    if not fn:
        print(__doc__)
        return 2
    return fn()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
