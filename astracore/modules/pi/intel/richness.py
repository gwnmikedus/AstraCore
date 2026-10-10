"""Planet yield estimates.

ESI does not expose per-planet resource richness (only an in-game scan shows it),
so the default is a security-based heuristic: lower true-sec = richer deposits.
Users can override any planet after scanning in game.
"""
from __future__ import annotations

from typing import Dict, Optional

RICHNESS_LABELS = {"poor": 0.6, "average": 1.0, "good": 1.25, "rich": 1.5}


def sec_multiplier(security: float) -> float:
    if security >= 0.45:
        return 0.5
    if security > 0.0:
        return 0.75
    # nullsec: 1.0 at 0.0 sec, rising to ~1.4 at -1.0
    return 1.0 + 0.4 * min(1.0, -security)


def richness(planet_id: int, security: float, overrides: Optional[Dict[int, float]] = None) -> float:
    if overrides and planet_id in overrides:
        return float(overrides[planet_id])
    return sec_multiplier(security)


def _extractor_samples(colonies_by_char: Dict[int, list]) -> list:
    """(planet_id, realised P0/hour/head normalised to a 3-day program) for every extractor ESI shows."""
    from datetime import datetime

    from ..static_data import extraction

    fmt = "%Y-%m-%dT%H:%M:%SZ"
    samples = []
    for colonies in colonies_by_char.values():
        for col in colonies:
            for pin in col.get("pins", []):
                ex = pin.get("extractor_details")
                if not ex or not ex.get("heads") or not ex.get("cycle_time") or not ex.get("qty_per_cycle"):
                    continue
                cycle_s = extraction.normalise_cycle_time(ex["cycle_time"])
                try:
                    duration = (datetime.strptime(pin["expiry_time"], fmt)
                                - datetime.strptime(pin["install_time"], fmt)).total_seconds()
                except (KeyError, TypeError, ValueError):
                    duration = 3 * 86400.0
                if duration < cycle_s:
                    continue
                per_hour = extraction.avg_per_hour(ex["qty_per_cycle"], cycle_s, duration)
                per_head = per_hour / len(ex["heads"]) / extraction.cycle_factor(duration / 86400)
                samples.append((col.get("planet_id"), per_head))
    return samples


def calibrate_head_yield(colonies_by_char: Dict[int, list], planet_sec: Dict[int, float],
                         cycle_factor_now: float = 1.0) -> Optional[float]:
    """P0/hour/head at richness 1.0 on a 3-day program, from users' real extractors (ESI).

    Each extractor's real output over its program comes from CCP's formula (qty_per_cycle,
    cycle_time, install/expiry), divided by heads, normalised to a 3-day program and to the
    planet's richness estimate. Returns the median, or None when there is no data.
    """
    samples = [v / sec_multiplier(planet_sec.get(pid, -0.5)) for pid, v in _extractor_samples(colonies_by_char)]
    if not samples:
        return None
    samples.sort()
    return round(samples[len(samples) // 2], 1)


def measured_richness(colonies_by_char: Dict[int, list], head_yield: float) -> Dict[int, float]:
    """Per-planet richness from your own extractors, relative to the calibrated head yield.
    Only meaningful with 2+ extracting colonies; manual overrides still win."""
    samples = _extractor_samples(colonies_by_char)
    if len(samples) < 2 or not head_yield:
        return {}
    per_planet: Dict[int, list] = {}
    for pid, v in samples:
        per_planet.setdefault(pid, []).append(v / head_yield)
    return {pid: round(sum(v) / len(v), 2) for pid, v in per_planet.items() if pid}
