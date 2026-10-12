"""sqlite3 persistence: schema, migrations and the core data (profiles, characters, tokens).

Personal data always belongs to a profile: every function that reads or changes it takes a
`profile_id` (or a character id that the caller has already checked belongs to the profile).
Shared, non-personal caches (kv: prices, SDE, VOC tariff, area data, public ESI responses in http_cache)
stay global. Authenticated ESI responses in http_cache are personal: keyed per character (`#auth:<id>`),
deleted with the character and dropped once expired.
Module data access lives with the module (e.g. modules/pi/store.py).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from .config import ADMIN_CHARACTER_IDS, DB_PATH, HOME, LEGACY_DB_PATH, MODE

DEFAULT_LOCAL_DB = HOME / "data" / "local" / "astracore.sqlite3"

log = logging.getLogger("astracore")

MAX_CHARACTERS_PER_ACCOUNT = 3   # EVE allows three characters per account

# --------------------------------------------------------------------------- connection
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- schema
# v1 = the MVP (PI Planner) schema, kept so an MVP database upgrades step by step.
SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY, body TEXT NOT NULL, etag TEXT, expires REAL NOT NULL, pages INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS characters (
    character_id INTEGER PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual',
    slots INTEGER NOT NULL DEFAULT 6, ccu_level INTEGER NOT NULL DEFAULT 5, enabled INTEGER NOT NULL DEFAULT 1,
    skills_json TEXT, colonies_json TEXT, synced_at REAL
);
CREATE TABLE IF NOT EXISTS tokens (
    character_id INTEGER PRIMARY KEY, refresh_token TEXT NOT NULL, access_token TEXT, expires_at REAL
);
CREATE TABLE IF NOT EXISTS planet_overrides (planet_id INTEGER PRIMARY KEY, richness REAL NOT NULL);
CREATE TABLE IF NOT EXISTS plan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, label TEXT,
    settings_json TEXT NOT NULL, result_json TEXT NOT NULL
);
"""
V1_CHARACTER_COLUMNS = {
    "corporation_id": "INTEGER", "corporation_name": "TEXT", "alliance_id": "INTEGER", "alliance_name": "TEXT",
    "assets_json": "TEXT", "contracts_json": "TEXT", "orders_json": "TEXT", "wallet_json": "TEXT",
    "standings_json": "TEXT", "customs_offices_json": "TEXT",
}

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    last_login_at REAL,
    display_name TEXT NOT NULL DEFAULT '',
    main_character_id INTEGER,
    settings_json TEXT NOT NULL DEFAULT '{}',
    notices_json TEXT NOT NULL DEFAULT '[]',     -- messages shown once on the next visit
    onboarded INTEGER NOT NULL DEFAULT 0,
    last_esi_refresh_at REAL
);
CREATE TABLE IF NOT EXISTS eve_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS characters_v2 (
    character_id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    eve_account_id INTEGER REFERENCES eve_accounts(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    owner_hash TEXT,
    status TEXT NOT NULL DEFAULT 'ok',            -- ok | needs_login
    linked_at REAL,
    enabled INTEGER NOT NULL DEFAULT 1,           -- included in AstracorePI plans
    enabled_modules_json TEXT NOT NULL DEFAULT '["pi"]',
    bundle_prefs_json TEXT NOT NULL DEFAULT '{}', -- bundles switched off without a new login: {"id": false}
    source TEXT NOT NULL DEFAULT 'esi',
    slots INTEGER NOT NULL DEFAULT 6,
    ccu_level INTEGER NOT NULL DEFAULT 5,
    skills_json TEXT, colonies_json TEXT, synced_at REAL,
    corporation_id INTEGER, corporation_name TEXT, alliance_id INTEGER, alliance_name TEXT,
    assets_json TEXT, contracts_json TEXT, orders_json TEXT, wallet_json TEXT,
    standings_json TEXT, customs_offices_json TEXT
);
CREATE TABLE IF NOT EXISTS tokens_v2 (
    character_id INTEGER PRIMARY KEY REFERENCES characters(character_id) ON DELETE CASCADE,
    refresh_token_enc TEXT NOT NULL,
    access_token_enc TEXT,
    expires_at REAL,
    scopes TEXT NOT NULL DEFAULT '',
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    id_hash TEXT PRIMARY KEY,                      -- sha256 of the cookie value
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,   -- NULL = signed out
    csrf TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    user_agent TEXT,
    ip_hint TEXT,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS sessions_profile ON sessions(profile_id);
CREATE TABLE IF NOT EXISTS sso_states (
    state TEXT PRIMARY KEY,
    session_hash TEXT NOT NULL,
    intent TEXT NOT NULL,                          -- login | add | upgrade:<character_id>
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS module_settings (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    module_id TEXT NOT NULL,
    settings_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (profile_id, module_id)
);
CREATE TABLE IF NOT EXISTS access_list (
    kind TEXT NOT NULL,                            -- character | corporation | alliance
    entity_id INTEGER NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    added_at REAL NOT NULL,
    PRIMARY KEY (kind, entity_id)
);
CREATE TABLE IF NOT EXISTS plan_runs_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    created REAL NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 0,
    settings_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planet_overrides_v2 (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    planet_id INTEGER NOT NULL,
    richness REAL NOT NULL,
    PRIMARY KEY (profile_id, planet_id)
);
"""


def _cols(c: sqlite3.Connection, table: str) -> set:
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}


def _has_table(c: sqlite3.Connection, table: str) -> bool:
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _migrate_v1(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA_V1)
    have = _cols(c, "characters")
    for col, typ in V1_CHARACTER_COLUMNS.items():
        if col not in have:
            c.execute(f"ALTER TABLE characters ADD COLUMN {col} {typ}")
    if "scopes" not in _cols(c, "tokens"):
        c.execute("ALTER TABLE tokens ADD COLUMN scopes TEXT")


def _migrate_v2(c: sqlite3.Connection) -> None:
    """MVP -> Astracore: everything personal moves into profile #1 (if there is anything)."""
    from .core import crypto

    c.executescript(SCHEMA_V2)
    now = time.time()
    old_chars = [dict(r) for r in c.execute("SELECT * FROM characters ORDER BY character_id")]
    has_plans = c.execute("SELECT COUNT(*) FROM plan_runs").fetchone()[0]
    has_overrides = c.execute("SELECT COUNT(*) FROM planet_overrides").fetchone()[0]
    old_settings = c.execute("SELECT value FROM kv WHERE key='settings'").fetchone()
    pid = None
    if old_chars or has_plans or has_overrides or old_settings:
        main = next((x for x in old_chars if x["character_id"] in ADMIN_CHARACTER_IDS), old_chars[0] if old_chars else None)
        cur = c.execute("INSERT INTO profiles(created_at, last_login_at, display_name, main_character_id, onboarded) "
                        "VALUES(?,?,?,?,1)", (now, None, main["name"] if main else "Profile 1",
                                               main["character_id"] if main else None))
        pid = cur.lastrowid
        log.info("migration: created profile %s for %d MVP character(s)", pid, len(old_chars))

    keep = [k for k in _cols(c, "characters") if k in _cols(c, "characters_v2") and k != "character_id"]
    for ch in old_chars:
        cols = ["character_id", "profile_id", "linked_at"] + keep
        vals = [ch["character_id"], pid, now] + [ch[k] for k in keep]
        c.execute(f"INSERT INTO characters_v2({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", vals)
    for t in c.execute("SELECT * FROM tokens").fetchall():
        if not any(ch["character_id"] == t["character_id"] for ch in old_chars):
            continue
        c.execute("INSERT INTO tokens_v2(character_id, refresh_token_enc, access_token_enc, expires_at, scopes, updated_at) "
                  "VALUES(?,?,?,?,?,?)",
                  (t["character_id"], crypto.encrypt(t["refresh_token"]), crypto.encrypt(t["access_token"]),
                   t["expires_at"], t["scopes"] or "", now))
    if pid is not None:
        for r in c.execute("SELECT * FROM plan_runs").fetchall():
            c.execute("INSERT INTO plan_runs_v2(profile_id, created, label, settings_json, result_json) VALUES(?,?,?,?,?)",
                      (pid, r["created"], r["label"] or "", r["settings_json"], r["result_json"]))
        for r in c.execute("SELECT * FROM planet_overrides").fetchall():
            c.execute("INSERT INTO planet_overrides_v2 VALUES(?,?,?)", (pid, r["planet_id"], r["richness"]))
        if old_settings:
            c.execute("INSERT INTO module_settings(profile_id, module_id, settings_json) VALUES(?, 'pi', ?)",
                      (pid, old_settings["value"]))
            c.execute("DELETE FROM kv WHERE key='settings'")

    for old, new in (("characters", "characters_v2"), ("tokens", "tokens_v2"), ("plan_runs", "plan_runs_v2"),
                     ("planet_overrides", "planet_overrides_v2")):
        c.execute(f"DROP TABLE {old}")
        c.execute(f"ALTER TABLE {new} RENAME TO {old}")
    c.execute("CREATE INDEX IF NOT EXISTS characters_profile ON characters(profile_id)")
    c.execute("CREATE INDEX IF NOT EXISTS plan_runs_profile ON plan_runs(profile_id)")


def _migrate_v3(c: sqlite3.Connection) -> None:
    """Optional bundles are off by default. MVP logins asked for every scope, so characters carried over
    from the MVP would otherwise start with the optional bundles switched on: pause them instead
    ("granted but unused") until the user turns them on."""
    optional = ["pi.optional.customs", "pi.optional.waypoints"]
    for r in c.execute("SELECT character_id, bundle_prefs_json FROM characters").fetchall():
        prefs = json.loads(r["bundle_prefs_json"] or "{}")
        for b in optional:
            prefs.setdefault(b, False)
        c.execute("UPDATE characters SET bundle_prefs_json=? WHERE character_id=?", (json.dumps(prefs), r["character_id"]))


def _migrate_v4(c: sqlite3.Connection) -> None:
    """Community reports, reliable delivery and the public GitHub issue cache."""
    from .core.community import SCHEMA
    c.executescript(SCHEMA)


def _migrate_v5(c: sqlite3.Connection) -> None:
    """Keep the displayed PI result server-side until the pilot saves it."""
    c.execute("CREATE TABLE IF NOT EXISTS plan_results ("
              "profile_id INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE, "
              "result_id TEXT NOT NULL, created REAL NOT NULL, settings_json TEXT NOT NULL, "
              "stamp TEXT NOT NULL, result_json TEXT NOT NULL, active_id INTEGER, run_id INTEGER "
              "REFERENCES plan_runs(id) ON DELETE SET NULL)")


def _migrate_v6(c: sqlite3.Connection) -> None:
    """Authenticated ESI responses used to share one cache entry per URL; drop them (they're re-fetched
    per character) and keep personal responses only while fresh."""
    c.execute("DELETE FROM http_cache WHERE url LIKE '%#auth'")
    c.execute("DELETE FROM http_cache WHERE url LIKE '%#auth:%' AND expires < ?", (time.time(),))


def _migrate_v7(c: sqlite3.Connection) -> None:
    """Remember ESI's own expiry next to ours, so a refresh never asks ESI again before it has new data."""
    if "esi_expires" not in _cols(c, "http_cache"):
        c.execute("ALTER TABLE http_cache ADD COLUMN esi_expires REAL")


MIGRATIONS = [_migrate_v1, _migrate_v2, _migrate_v3, _migrate_v4, _migrate_v5, _migrate_v6, _migrate_v7]


def adopt_legacy_db() -> bool:
    """Local mode, first start: copy the MVP database (data/pi_planner.sqlite3) into data/local/.
    The original file stays untouched as the pre-migration backup."""
    if MODE != "local" or DB_PATH != DEFAULT_LOCAL_DB or DB_PATH.exists() or not LEGACY_DB_PATH.exists():
        return False
    src = sqlite3.connect(LEGACY_DB_PATH)
    dst = sqlite3.connect(DB_PATH)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return True


def migrate(conn: Optional[sqlite3.Connection] = None) -> int:
    """Run pending migrations (idempotent: PRAGMA user_version records how far we are)."""
    c = conn or connect()
    try:
        c.execute("PRAGMA foreign_keys=OFF")   # table rebuilds
        version = c.execute("PRAGMA user_version").fetchone()[0]
        for i, step in enumerate(MIGRATIONS, start=1):
            if version < i:
                with c:
                    step(c)
                    c.execute(f"PRAGMA user_version={i}")
                version = i
        c.execute("PRAGMA foreign_keys=ON")
        return version
    finally:
        if conn is None:
            c.close()


def init() -> None:
    adopt_legacy_db()
    migrate()


def backup(dest) -> None:
    src = connect()
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


# --------------------------------------------------------------------------- kv (shared caches, admin settings)
def kv_get(key: str, default: Any = None) -> Any:
    with session() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def kv_set(key: str, value: Any) -> None:
    with session() as c:
        c.execute("REPLACE INTO kv(key, value) VALUES(?, ?)", (key, json.dumps(value)))


def admin_settings() -> Dict[str, Any]:
    return kv_get("admin_settings", {}) or {}


def set_admin_settings(values: Dict[str, Any]) -> None:
    cur = admin_settings()
    cur.update(values)
    kv_set("admin_settings", cur)


# --------------------------------------------------------------------------- profiles
def create_profile(display_name: str, main_character_id: Optional[int] = None) -> int:
    now = time.time()
    with session() as c:
        cur = c.execute("INSERT INTO profiles(created_at, last_login_at, display_name, main_character_id) VALUES(?,?,?,?)",
                        (now, now, display_name, main_character_id))
        return int(cur.lastrowid)


def get_profile(profile_id: Optional[int]) -> Optional[dict]:
    if not profile_id:
        return None
    with session() as c:
        r = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if not r:
        return None
    p = dict(r)
    p["settings"] = json.loads(p.pop("settings_json") or "{}")
    p["notices"] = json.loads(p.pop("notices_json") or "[]")
    return p


PROFILE_FIELDS = {"last_login_at", "display_name", "main_character_id", "onboarded", "last_esi_refresh_at"}


def update_profile(profile_id: int, **kw: Any) -> None:
    with session() as c:
        for k, v in kw.items():
            if k == "settings":
                c.execute("UPDATE profiles SET settings_json=? WHERE id=?", (json.dumps(v), profile_id))
            elif k in PROFILE_FIELDS:
                c.execute(f"UPDATE profiles SET {k}=? WHERE id=?", (v, profile_id))
            else:
                raise KeyError(k)


def add_notice(profile_id: int, text: str, kind: str = "warn") -> None:
    with session() as c:
        r = c.execute("SELECT notices_json FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if not r:
            return
        notes = json.loads(r["notices_json"] or "[]")
        notes.append({"text": text, "kind": kind, "at": time.time()})
        c.execute("UPDATE profiles SET notices_json=? WHERE id=?", (json.dumps(notes[-20:]), profile_id))


def pop_notices(profile_id: int) -> List[dict]:
    with session() as c:
        r = c.execute("SELECT notices_json FROM profiles WHERE id=?", (profile_id,)).fetchone()
        c.execute("UPDATE profiles SET notices_json='[]' WHERE id=?", (profile_id,))
    return json.loads(r["notices_json"] or "[]") if r else []


def delete_profile(profile_id: int) -> None:
    """Everything of the profile goes (characters, tokens, accounts, settings, plans, overrides, sessions)."""
    with session() as c:
        cids = [r[0] for r in c.execute("SELECT character_id FROM characters WHERE profile_id=?", (profile_id,))]
        c.executemany("DELETE FROM tokens WHERE character_id=?", [(x,) for x in cids])
        for x in cids:
            forget_character_cache(c, x)
        for table in ("characters", "eve_accounts", "module_settings", "plan_runs", "planet_overrides", "sessions"):
            c.execute(f"DELETE FROM {table} WHERE profile_id=?", (profile_id,))
        c.execute("DELETE FROM profiles WHERE id=?", (profile_id,))


def is_admin(profile_id: int) -> bool:
    return any(ch["character_id"] in ADMIN_CHARACTER_IDS for ch in list_characters(profile_id))


# --------------------------------------------------------------------------- characters
JSON_COLUMNS = ("skills", "colonies", "assets", "contracts", "orders", "wallet", "standings", "customs_offices")
META_JSON = {"enabled_modules": [], "bundle_prefs": {}}


def _char_row(d: dict, scopes: Optional[str]) -> dict:
    for k in JSON_COLUMNS:
        raw = d.pop(f"{k}_json", None)
        d[k] = json.loads(raw) if raw else ({} if k in ("skills", "wallet") else [])
    for k, default in META_JSON.items():
        raw = d.pop(f"{k}_json", None)
        d[k] = json.loads(raw) if raw else type(default)()
    d["scopes"] = (scopes or "").split()
    d["has_token"] = scopes is not None
    return d


def list_characters(profile_id: int, enabled_only: bool = False) -> List[dict]:
    q = ("SELECT c.*, t.scopes AS _scopes FROM characters c LEFT JOIN tokens t USING(character_id) "
         "WHERE c.profile_id=?" + (" AND c.enabled=1" if enabled_only else "") + " ORDER BY c.name COLLATE NOCASE")
    with session() as c:
        rows = c.execute(q, (profile_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        scopes = d.pop("_scopes")
        out.append(_char_row(d, scopes))
    return out


def get_character(character_id: int) -> Optional[dict]:
    """A character regardless of profile. Callers must check `profile_id` before acting on it."""
    with session() as c:
        r = c.execute("SELECT c.*, t.scopes AS _scopes FROM characters c LEFT JOIN tokens t USING(character_id) "
                      "WHERE c.character_id=?", (character_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    scopes = d.pop("_scopes")
    return _char_row(d, scopes)


def owned_character(profile_id: int, character_id: int) -> Optional[dict]:
    ch = get_character(character_id)
    return ch if ch and ch["profile_id"] == profile_id else None


def link_character(character_id: int, profile_id: int, name: str, owner_hash: Optional[str] = None) -> None:
    """Attach a character to a profile (new, or moved from another profile)."""
    with session() as c:
        exists = c.execute("SELECT profile_id FROM characters WHERE character_id=?", (character_id,)).fetchone()
        if exists:
            c.execute("UPDATE characters SET profile_id=?, eve_account_id=NULL, name=?, owner_hash=COALESCE(?, owner_hash), "
                      "status='ok', linked_at=? WHERE character_id=?",
                      (profile_id, name, owner_hash, time.time(), character_id))
        else:
            c.execute("INSERT INTO characters(character_id, profile_id, name, owner_hash, linked_at, source) "
                      "VALUES(?,?,?,?,?, 'esi')", (character_id, profile_id, name, owner_hash, time.time()))


CHARACTER_FIELDS = {"name", "owner_hash", "status", "enabled", "slots", "ccu_level", "synced_at", "source",
                    "corporation_id", "corporation_name", "alliance_id", "alliance_name", "eve_account_id"}


def set_character(character_id: int, **kw: Any) -> None:
    with session() as c:
        for k, v in kw.items():
            if k in JSON_COLUMNS or k in META_JSON:
                c.execute(f"UPDATE characters SET {k}_json=? WHERE character_id=?", (json.dumps(v), character_id))
            elif k in CHARACTER_FIELDS:
                c.execute(f"UPDATE characters SET {k}=? WHERE character_id=?", (v, character_id))
            else:
                raise KeyError(k)


def forget_character_cache(c: sqlite3.Connection, character_id: int) -> None:
    """Delete every cached authenticated ESI response made with this character's token."""
    c.execute("DELETE FROM http_cache WHERE url LIKE ?", (f"%#auth:{int(character_id)}",))


def purge_expired_private_cache() -> None:
    """Authenticated ESI responses are only kept while ESI says they're fresh."""
    with session() as c:
        c.execute("DELETE FROM http_cache WHERE url LIKE '%#auth:%' AND expires < ?", (time.time(),))


def delete_character(character_id: int) -> None:
    with session() as c:
        forget_character_cache(c, character_id)
        c.execute("DELETE FROM tokens WHERE character_id=?", (character_id,))
        c.execute("DELETE FROM characters WHERE character_id=?", (character_id,))


def character_profile(character_id: int) -> Optional[int]:
    with session() as c:
        r = c.execute("SELECT profile_id FROM characters WHERE character_id=?", (character_id,)).fetchone()
    return r["profile_id"] if r else None


# --------------------------------------------------------------------------- EVE accounts
def list_accounts(profile_id: int) -> List[dict]:
    with session() as c:
        return [dict(r) for r in c.execute("SELECT * FROM eve_accounts WHERE profile_id=? ORDER BY sort, id",
                                           (profile_id,))]


def create_account(profile_id: int, name: str) -> int:
    with session() as c:
        n = c.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM eve_accounts WHERE profile_id=?", (profile_id,)).fetchone()[0]
        return int(c.execute("INSERT INTO eve_accounts(profile_id, name, sort) VALUES(?,?,?)",
                             (profile_id, name.strip()[:60] or "EVE account", n)).lastrowid)


def rename_account(profile_id: int, account_id: int, name: str) -> bool:
    with session() as c:
        cur = c.execute("UPDATE eve_accounts SET name=? WHERE id=? AND profile_id=?",
                        (name.strip()[:60] or "EVE account", account_id, profile_id))
        return cur.rowcount > 0


def delete_account(profile_id: int, account_id: int) -> bool:
    """Characters of a deleted account go back to "Unassigned"."""
    with session() as c:
        c.execute("UPDATE characters SET eve_account_id=NULL WHERE eve_account_id=? AND profile_id=?",
                  (account_id, profile_id))
        return c.execute("DELETE FROM eve_accounts WHERE id=? AND profile_id=?", (account_id, profile_id)).rowcount > 0


def assign_account(profile_id: int, character_id: int, account_id: Optional[int]) -> str:
    """Move a character into an EVE account (None = Unassigned). Returns '' or an error message."""
    with session() as c:
        ch = c.execute("SELECT 1 FROM characters WHERE character_id=? AND profile_id=?", (character_id, profile_id)).fetchone()
        if not ch:
            return "Unknown character."
        if account_id is not None:
            acc = c.execute("SELECT name FROM eve_accounts WHERE id=? AND profile_id=?", (account_id, profile_id)).fetchone()
            if not acc:
                return "Unknown EVE account."
            n = c.execute("SELECT COUNT(*) FROM characters WHERE eve_account_id=? AND character_id<>?",
                          (account_id, character_id)).fetchone()[0]
            if n >= MAX_CHARACTERS_PER_ACCOUNT:
                return f"{acc['name']} already has {MAX_CHARACTERS_PER_ACCOUNT} characters (EVE's maximum)."
        c.execute("UPDATE characters SET eve_account_id=? WHERE character_id=?", (account_id, character_id))
    return ""


# --------------------------------------------------------------------------- tokens (encrypted at rest)
def get_token(character_id: int) -> Optional[dict]:
    from .core import crypto
    with session() as c:
        row = c.execute("SELECT * FROM tokens WHERE character_id=?", (character_id,)).fetchone()
    if not row:
        return None
    return {"character_id": row["character_id"], "refresh_token": crypto.decrypt(row["refresh_token_enc"]),
            "access_token": crypto.decrypt(row["access_token_enc"]), "expires_at": row["expires_at"],
            "scopes": row["scopes"] or ""}


def save_token(character_id: int, refresh_token: str, access_token: Optional[str], expires_in: int,
               scopes: Optional[str] = None) -> None:
    from .core import crypto
    with session() as c:
        old = c.execute("SELECT scopes FROM tokens WHERE character_id=?", (character_id,)).fetchone()
        c.execute(
            "REPLACE INTO tokens(character_id, refresh_token_enc, access_token_enc, expires_at, scopes, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (character_id, crypto.encrypt(refresh_token), crypto.encrypt(access_token),
             time.time() + expires_in - 30, scopes if scopes is not None else (old["scopes"] if old else ""),
             time.time()),
        )


def delete_token(character_id: int) -> None:
    with session() as c:
        c.execute("DELETE FROM tokens WHERE character_id=?", (character_id,))


# --------------------------------------------------------------------------- module settings
def module_settings(profile_id: int, module_id: str) -> Optional[dict]:
    with session() as c:
        r = c.execute("SELECT settings_json FROM module_settings WHERE profile_id=? AND module_id=?",
                      (profile_id, module_id)).fetchone()
    return json.loads(r["settings_json"]) if r else None


def set_module_settings(profile_id: int, module_id: str, values: dict) -> None:
    with session() as c:
        c.execute("REPLACE INTO module_settings(profile_id, module_id, settings_json) VALUES(?,?,?)",
                  (profile_id, module_id, json.dumps(values)))


def delete_module_settings(profile_id: int, module_id: str) -> None:
    with session() as c:
        c.execute("DELETE FROM module_settings WHERE profile_id=? AND module_id=?", (profile_id, module_id))


# --------------------------------------------------------------------------- access list (invite gate)
def access_list() -> List[dict]:
    with session() as c:
        return [dict(r) for r in c.execute("SELECT * FROM access_list ORDER BY kind, name")]


def access_add(kind: str, entity_id: int, name: str = "") -> None:
    with session() as c:
        c.execute("REPLACE INTO access_list(kind, entity_id, name, added_at) VALUES(?,?,?,?)",
                  (kind, entity_id, name, time.time()))


def access_remove(kind: str, entity_id: int) -> None:
    with session() as c:
        c.execute("DELETE FROM access_list WHERE kind=? AND entity_id=?", (kind, entity_id))
