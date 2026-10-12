"""AstracorePI's personal data: settings, saved plans and planet richness overrides, per profile."""
from __future__ import annotations

import json
import secrets
import time
from dataclasses import fields
from typing import Callable, Dict, List, Optional

from astracore import db

from .planner.compare import plan_facts
from .settings import ADMIN_FIELDS, Settings

MODULE_ID = "pi"
MAX_PLANS = 30


# --------------------------------------------------------------------------- settings
def admin_defaults() -> Dict:
    a = db.admin_settings()
    return {k: a[k] for k in ADMIN_FIELDS if k in a}


def load_settings(profile_id: int) -> Settings:
    """Profile preferences, with the instance-wide admin values on top."""
    raw = db.module_settings(profile_id, MODULE_ID)
    s = Settings.from_json(json.dumps(raw) if raw else None)
    for k, v in admin_defaults().items():
        setattr(s, k, v)
    return s


def save_settings(profile_id: int, s: Settings) -> None:
    data = json.loads(s.to_json())
    for k in ADMIN_FIELDS:      # never stored per profile
        data.pop(k, None)
    db.set_module_settings(profile_id, MODULE_ID, data)


def has_settings(profile_id: int) -> bool:
    return db.module_settings(profile_id, MODULE_ID) is not None


def admin_settings() -> Settings:
    s = Settings()
    for k, v in admin_defaults().items():
        setattr(s, k, v)
    return s


def save_admin_settings(values: Dict) -> None:
    s = admin_settings()
    s.update({k: v for k, v in values.items() if k in ADMIN_FIELDS})
    db.set_admin_settings({k: getattr(s, k) for k in ADMIN_FIELDS})


SETTINGS_FIELDS = {f.name for f in fields(Settings)}


# --------------------------------------------------------------------------- planet overrides
def planet_overrides(profile_id: int) -> Dict[int, float]:
    with db.session() as c:
        return {r["planet_id"]: r["richness"] for r in
                c.execute("SELECT planet_id, richness FROM planet_overrides WHERE profile_id=?", (profile_id,))}


def set_planet_override(profile_id: int, planet_id: int, richness: Optional[float]) -> None:
    with db.session() as c:
        if richness is None:
            c.execute("DELETE FROM planet_overrides WHERE profile_id=? AND planet_id=?", (profile_id, planet_id))
        else:
            c.execute("REPLACE INTO planet_overrides(profile_id, planet_id, richness) VALUES(?,?,?)",
                      (profile_id, planet_id, richness))


# --------------------------------------------------------------------------- saved plans
RESULT_MAX_AGE = 3600


class StaleResult(ValueError):
    """The displayed result can no longer be saved safely."""


def plan_settings(settings: Settings) -> dict:
    data = json.loads(settings.to_json())
    for name in ("guide_step", "answered"):
        data.pop(name, None)
    return data


def remember_plan_result(profile_id: int, settings: Settings, result: dict, stamp: str) -> str:
    """One latest, expiring snapshot per profile; clients only receive its random handle."""
    result_id = secrets.token_urlsafe(32)
    with db.session() as c:
        c.execute("DELETE FROM plan_results WHERE created < ?", (time.time() - RESULT_MAX_AGE,))
        active = c.execute("SELECT id FROM plan_runs WHERE profile_id=? AND active=1", (profile_id,)).fetchone()
        c.execute("REPLACE INTO plan_results(profile_id, result_id, created, settings_json, stamp, "
                  "result_json, active_id) VALUES(?,?,?,?,?,?,?)",
                  (profile_id, result_id, time.time(), settings.to_json(), stamp, json.dumps(result),
                   active["id"] if active else None))
    return result_id


def save_plan_result(profile_id: int, result_id: str, label: str, stamp: Callable[[], str],
                     active: bool = False) -> dict:
    """Atomically save the owned snapshot; repeat requests return the same saved plan."""
    with db.session() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM plan_results WHERE profile_id=? AND result_id=?",
                        (profile_id, result_id)).fetchone()
        if not row or row["created"] < time.time() - RESULT_MAX_AGE:
            raise StaleResult("This result has expired or been replaced. Recalculate your plan before saving.")
        if row["run_id"]:
            return get_plan_run(profile_id, row["run_id"])
        original = Settings.from_json(row["settings_json"])
        settings = load_settings(profile_id)
        if plan_settings(original) != plan_settings(settings) or row["stamp"] != stamp():
            raise StaleResult("Your planning data or answers changed. Recalculate your plan before saving.")
        current = c.execute("SELECT id FROM plan_runs WHERE profile_id=? AND active=1", (profile_id,)).fetchone()
        current_id = current["id"] if current else None
        if current_id != row["active_id"]:
            raise StaleResult("Your active plan changed. Recalculate to compare before replacing it.")
        active = bool(active) or current_id is None
        if active:
            c.execute("UPDATE plan_runs SET active=0 WHERE profile_id=?", (profile_id,))
        count = c.execute("SELECT COUNT(*) FROM plan_runs WHERE profile_id=?", (profile_id,)).fetchone()[0]
        label = label.strip()[:80] or f"Plan {count + 1}"
        cur = c.execute("INSERT INTO plan_runs(profile_id, created, label, active, settings_json, result_json) "
                        "VALUES(?,?,?,?,?,?)", (profile_id, time.time(), label, int(active),
                                                row["settings_json"], row["result_json"]))
        run_id = int(cur.lastrowid)
        c.execute("UPDATE plan_results SET run_id=? WHERE profile_id=?", (run_id, profile_id))
        _trim_plans(c, profile_id)
    return get_plan_run(profile_id, run_id)


def _trim_plans(c, profile_id: int) -> None:
    old = [r[0] for r in c.execute("SELECT id FROM plan_runs WHERE profile_id=? AND active=0 ORDER BY id DESC "
                                   "LIMIT -1 OFFSET ?", (profile_id, MAX_PLANS))]
    c.executemany("DELETE FROM plan_runs WHERE id=?", [(x,) for x in old])


def save_plan_run(profile_id: int, label: str, settings: Settings, result: dict, active: bool = False) -> int:
    with db.session() as c:
        if active:
            c.execute("UPDATE plan_runs SET active=0 WHERE profile_id=?", (profile_id,))
        cur = c.execute("INSERT INTO plan_runs(profile_id, created, label, active, settings_json, result_json) "
                        "VALUES(?,?,?,?,?,?)", (profile_id, time.time(), label.strip()[:80], int(active),
                                                settings.to_json(), json.dumps(result)))
        rid = int(cur.lastrowid)
        # keep the newest MAX_PLANS (never drop the active one)
        _trim_plans(c, profile_id)
    return rid


def list_plan_runs(profile_id: int, limit: int = MAX_PLANS) -> List[dict]:
    with db.session() as c:
        rows = c.execute("SELECT id, created, label, active, settings_json, result_json FROM plan_runs "
                         "WHERE profile_id=? ORDER BY active DESC, id DESC LIMIT ?", (profile_id, limit)).fetchall()
    out = []
    for r in rows:
        res = json.loads(r["result_json"])
        try:
            settings = json.loads(r["settings_json"] or "{}")
        except ValueError:
            settings = {}
        out.append(dict(id=r["id"], created=r["created"], label=r["label"], active=bool(r["active"]),
                        totals=res.get("totals", {}), hub=res.get("hub"), facts=plan_facts(res, settings)))
    return out


def get_plan_run(profile_id: int, run_id: int) -> Optional[dict]:
    with db.session() as c:
        r = c.execute("SELECT * FROM plan_runs WHERE id=? AND profile_id=?", (run_id, profile_id)).fetchone()
    if not r:
        return None
    return dict(id=r["id"], created=r["created"], label=r["label"], active=bool(r["active"]),
                settings=json.loads(r["settings_json"]), result=json.loads(r["result_json"]))


def active_plan(profile_id: int) -> Optional[dict]:
    with db.session() as c:
        r = c.execute("SELECT id FROM plan_runs WHERE profile_id=? AND active=1", (profile_id,)).fetchone()
    return get_plan_run(profile_id, r["id"]) if r else None


def set_active_plan(profile_id: int, run_id: int) -> bool:
    with db.session() as c:
        if not c.execute("SELECT 1 FROM plan_runs WHERE id=? AND profile_id=?", (run_id, profile_id)).fetchone():
            return False
        c.execute("UPDATE plan_runs SET active=(id=?) WHERE profile_id=?", (run_id, profile_id))
    return True


def delete_plan_run(profile_id: int, run_id: int) -> bool:
    with db.session() as c:
        return c.execute("DELETE FROM plan_runs WHERE id=? AND profile_id=?", (run_id, profile_id)).rowcount > 0


# --------------------------------------------------------------------------- hooks (registry)
def strip_character(profile_id: int, character_id: int) -> None:
    """A removed character disappears from saved plans (its colonies and transfers are stripped)."""
    with db.session() as c:
        rows = c.execute("SELECT id, result_json FROM plan_runs WHERE profile_id=?", (profile_id,)).fetchall()
        for r in rows:
            res = json.loads(r["result_json"])
            gone = {ch.get("name") for ch in res.get("characters", []) if ch.get("character_id") == character_id}
            if not gone:
                continue
            res["characters"] = [ch for ch in res.get("characters", []) if ch.get("character_id") != character_id]
            res["colonies"] = [x for x in res.get("colonies", []) if x.get("character_id") != character_id]
            res["transfers"] = [x for x in res.get("transfers", []) if x.get("from") not in gone and x.get("to") not in gone]
            res["removals"] = [x for x in res.get("removals", []) if x.get("character") not in gone]
            res.setdefault("warnings", []).append(f"{', '.join(sorted(gone))} was removed from your profile after this plan "
                                                  "was made; their colonies are no longer listed.")
            c.execute("UPDATE plan_runs SET result_json=? WHERE id=?", (json.dumps(res), r["id"]))


def reset_profile(profile_id: int) -> None:
    """Reset AstracorePI: settings, plans and overrides go; characters stay."""
    db.delete_module_settings(profile_id, MODULE_ID)
    with db.session() as c:
        c.execute("DELETE FROM plan_results WHERE profile_id=?", (profile_id,))
        c.execute("DELETE FROM plan_runs WHERE profile_id=?", (profile_id,))
        c.execute("DELETE FROM planet_overrides WHERE profile_id=?", (profile_id,))
