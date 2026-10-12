"""Preserve solved candidates only across compatible relaxations of PI limits."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

LIMITS = {"max_tier", "max_systems", "max_jumps", "per_planet", "cross_character"}
WIZARD_STATE = {"guide_step", "answered"}
CONTEXT_FIELDS = ("tpl", "area", "systems", "chars", "values", "overrides", "head_yield",
                  "dropoff", "local", "origin", "origin_jumps", "seller", "books", "history",
                  "books_at", "history_at")


def candidate(ctx: dict, plan: dict) -> dict:
    """Keep the allocation and a compact fingerprint of its actual economic inputs in the cache."""
    inputs = {key: ctx.get(key) for key in CONTEXT_FIELDS}
    inputs["pi"] = ctx["pi"].to_json()
    raw = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return {"settings": asdict(ctx["solve_s"]), "assumptions": hashlib.sha256(raw.encode()).hexdigest(),
            "plan": plan}


def nested(narrow: dict, wide: dict) -> bool:
    """Only limits are relaxed; cycle, selling, yield, taxes, effort and time value must match.

    A higher sharing cap adds optional colonies at the same existing copy yields. Allowing trade
    relaxes ownership of factory inputs. Neither requires an existing allocation to change.
    """
    fixed = set(narrow) | set(wide)
    if any(narrow.get(k) != wide.get(k) for k in fixed - LIMITS - WIZARD_STATE):
        return False
    for key in ("max_tier", "max_jumps", "per_planet"):
        if narrow[key] > wide[key]:
            return False
    nsys, wsys = narrow["max_systems"], wide["max_systems"]
    if wsys > 0 and (nsys <= 0 or nsys > wsys):
        return False
    if narrow["cross_character"] and not wide["cross_character"]:
        return False
    return any(narrow[k] != wide[k] for k in LIMITS)


def _fits(plan: dict, settings: dict) -> bool:
    """Reject a solver/fitting fallback that already violates the requested ownership limits."""
    if "error" in plan:
        return False
    if not settings["cross_character"] and plan.get("transfers"):
        return False
    colonies = plan.get("colonies", [])
    if any(c["tier"] > settings["max_tier"] for c in colonies):
        return False
    systems = {c["system_id"] for c in colonies}
    if settings["max_systems"] > 0 and len(systems) > settings["max_systems"]:
        return False
    planets = [c["planet_id"] for c in colonies]
    return all(planets.count(p) <= settings["per_planet"] for p in set(planets))


def _same_plan(a: dict, b: dict) -> bool:
    keys = ("character_id", "planet_id", "product_id", "template_file", "utilisation",
            "out_per_day", "in_per_day")

    def allocations(plan):
        return sorted(json.dumps({k: c.get(k) for k in keys}, sort_keys=True)
                      for c in plan.get("colonies", []))
    return allocations(a) == allocations(b) and a.get("transfers") == b.get("transfers")


def select(rows: list) -> list:
    """Each wider row retains the best-income feasible candidate from its own true subsets.

    Select from original candidates, so neither request order nor a chain of substitutions can
    move an allocation between incomparable settings. Failed solves can also use a known feasible
    subset. The caller summarizes the chosen allocation with the destination's settings.
    """
    out = []
    for row in rows:
        best = row
        for other in rows:
            if other["assumptions"] != row["assumptions"] or not nested(other["settings"], row["settings"]):
                continue
            plan = other["plan"]
            if not _fits(plan, row["settings"]):
                continue
            current = best["plan"]
            if "error" in current or plan["totals"]["isk_per_day"] > current["totals"]["isk_per_day"]:
                best = other
            elif (plan["totals"]["isk_per_day"] == current["totals"]["isk_per_day"]
                  and _same_plan(plan, current)
                  and (best is row or nested(other["settings"], best["settings"]))):
                best = other
        result = {"id": row["id"], "plan": best["plan"], "settings": row["settings"]}
        if best is not row:
            result["same_as"] = best["id"]
        out.append(result)
    return out
