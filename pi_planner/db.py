"""Tiny sqlite3 persistence layer (no ORM needed for this size)."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

from .config import DB_PATH, Settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY, body TEXT NOT NULL, etag TEXT, expires REAL NOT NULL,
    pages INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS characters (
    character_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',   -- 'esi' | 'manual'
    slots INTEGER NOT NULL DEFAULT 6,
    ccu_level INTEGER NOT NULL DEFAULT 5,
    enabled INTEGER NOT NULL DEFAULT 1,
    skills_json TEXT,
    colonies_json TEXT,
    synced_at REAL
);
CREATE TABLE IF NOT EXISTS tokens (
    character_id INTEGER PRIMARY KEY,
    refresh_token TEXT NOT NULL,
    access_token TEXT,
    expires_at REAL
);
CREATE TABLE IF NOT EXISTS planet_overrides (
    planet_id INTEGER PRIMARY KEY, richness REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, label TEXT,
    settings_json TEXT NOT NULL, result_json TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


AFFILIATION_COLUMNS = {
    "corporation_id": "INTEGER", "corporation_name": "TEXT",
    "alliance_id": "INTEGER", "alliance_name": "TEXT",
    # operational data synced from ESI (JSON)
    "assets_json": "TEXT", "contracts_json": "TEXT", "orders_json": "TEXT", "wallet_json": "TEXT",
    "standings_json": "TEXT", "customs_offices_json": "TEXT",
}
JSON_COLUMNS = ("skills", "colonies", "assets", "contracts", "orders", "wallet", "standings", "customs_offices")


def init() -> None:
    with session() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("PRAGMA table_info(characters)")}
        for col, typ in AFFILIATION_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE characters ADD COLUMN {col} {typ}")
        if "scopes" not in {r["name"] for r in c.execute("PRAGMA table_info(tokens)")}:
            c.execute("ALTER TABLE tokens ADD COLUMN scopes TEXT")


# --- kv -----------------------------------------------------------------------
def kv_get(key: str, default: Any = None) -> Any:
    with session() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def kv_set(key: str, value: Any) -> None:
    with session() as c:
        c.execute("REPLACE INTO kv(key, value) VALUES(?, ?)", (key, json.dumps(value)))


def load_settings() -> Settings:
    with session() as c:
        row = c.execute("SELECT value FROM kv WHERE key='settings'").fetchone()
    return Settings.from_json(row["value"] if row else None)


def save_settings(s: Settings) -> None:
    with session() as c:
        c.execute("REPLACE INTO kv(key, value) VALUES('settings', ?)", (s.to_json(),))


# --- characters -----------------------------------------------------------------
def list_characters(enabled_only: bool = False) -> List[dict]:
    q = "SELECT * FROM characters" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY name"
    with session() as c:
        rows = [dict(r) for r in c.execute(q)]
    for r in rows:
        for k in JSON_COLUMNS:
            raw = r.pop(f"{k}_json", None)
            r[k] = json.loads(raw) if raw else ({} if k in ("skills", "wallet") else [])
    with session() as c:
        scopes = {row["character_id"]: (row["scopes"] or "") for row in c.execute("SELECT character_id, scopes FROM tokens")}
    for r in rows:
        r["scopes"] = scopes.get(r["character_id"], "").split()
    return rows


def upsert_character(character_id: int, name: str, source: str, **kw: Any) -> None:
    with session() as c:
        exists = c.execute("SELECT 1 FROM characters WHERE character_id=?", (character_id,)).fetchone()
        if not exists:
            c.execute(
                "INSERT INTO characters(character_id, name, source) VALUES(?,?,?)",
                (character_id, name, source),
            )
        else:
            c.execute("UPDATE characters SET name=?, source=? WHERE character_id=?",
                      (name, source, character_id))
        for k, v in kw.items():
            if k in JSON_COLUMNS:
                k, v = f"{k}_json", json.dumps(v)
            c.execute(f"UPDATE characters SET {k}=? WHERE character_id=?", (v, character_id))


def delete_character(character_id: int) -> None:
    with session() as c:
        c.execute("DELETE FROM characters WHERE character_id=?", (character_id,))
        c.execute("DELETE FROM tokens WHERE character_id=?", (character_id,))




# --- tokens -------------------------------------------------------------------------
def get_token(character_id: int) -> Optional[dict]:
    with session() as c:
        row = c.execute("SELECT * FROM tokens WHERE character_id=?", (character_id,)).fetchone()
    return dict(row) if row else None


def save_token(character_id: int, refresh_token: str, access_token: str, expires_in: int,
               scopes: Optional[str] = None) -> None:
    with session() as c:
        old = c.execute("SELECT scopes FROM tokens WHERE character_id=?", (character_id,)).fetchone()
        c.execute(
            "REPLACE INTO tokens(character_id, refresh_token, access_token, expires_at, scopes) VALUES(?,?,?,?,?)",
            (character_id, refresh_token, access_token, time.time() + expires_in - 30,
             scopes if scopes is not None else (old["scopes"] if old else None)),
        )


# --- planet overrides ------------------------------------------------------------------
def planet_overrides() -> dict:
    with session() as c:
        return {r["planet_id"]: r["richness"] for r in c.execute("SELECT * FROM planet_overrides")}


def set_planet_override(planet_id: int, richness: Optional[float]) -> None:
    with session() as c:
        if richness is None:
            c.execute("DELETE FROM planet_overrides WHERE planet_id=?", (planet_id,))
        else:
            c.execute("REPLACE INTO planet_overrides VALUES(?,?)", (planet_id, richness))


# --- plan runs ---------------------------------------------------------------------------
def save_plan_run(label: str, settings: Settings, result: dict) -> int:
    with session() as c:
        cur = c.execute(
            "INSERT INTO plan_runs(created, label, settings_json, result_json) VALUES(?,?,?,?)",
            (time.time(), label, settings.to_json(), json.dumps(result)),
        )
        return int(cur.lastrowid)


def list_plan_runs(limit: int = 20) -> List[dict]:
    with session() as c:
        rows = c.execute(
            "SELECT id, created, label, result_json FROM plan_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        res = json.loads(r["result_json"])
        out.append(dict(id=r["id"], created=r["created"], label=r["label"],
                        totals=res.get("totals", {})))
    return out


def get_plan_run(run_id: int) -> Optional[dict]:
    with session() as c:
        r = c.execute("SELECT * FROM plan_runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        return None
    return dict(id=r["id"], created=r["created"], label=r["label"],
                settings=json.loads(r["settings_json"]), result=json.loads(r["result_json"]))
