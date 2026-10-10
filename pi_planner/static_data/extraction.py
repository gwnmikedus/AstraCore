"""Extractor output, using CCP's published formula
(https://developers.eveonline.com/docs/guides/pi/).

ESI reports, per extractor: qty_per_cycle (the base value), cycle_time, install_time and
expiry_time. The real output of cycle i is

    w = cycle_time / 900                     (bar width, in 15-minute units)
    t = (i + 0.5) * w
    decay = qty / (1 + t * DECAY)
    noise = max(0, (cos(qty^0.7 + t/12) + cos(qty^0.7 / 2 + t/5) + cos(t/2)) / 3)
    out_i = int(w * decay * (1 + NOISE * noise))

so the hourly rate falls the longer a program runs. The base value is taken as fixed for a
given head placement, whatever the program length.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import List

DECAY = 0.012   # dogma attribute 1683
NOISE = 0.8     # dogma attribute 1687
REFERENCE_DAYS = 3.0


def cycle_seconds(program_hours: float) -> int:
    """Cycle length the game picks for a program: 15 min up to 25 h, doubling every time the
    program length doubles (47.5 h -> 30 min, 72 h -> 1 h, 7 days -> 2 h, 14 days -> 4 h)."""
    k = max(0, math.ceil(math.log2(max(program_hours, 1e-9) / 25.0)))
    return int(900 * 2 ** k)


def normalise_cycle_time(cycle_time: float) -> float:
    """ESI gives seconds. Treat small values as minutes, which some docs and tools use."""
    return cycle_time * 60 if cycle_time and cycle_time <= 240 else cycle_time


def outputs(qty_per_cycle: float, cycle_time_s: float, duration_s: float) -> List[int]:
    n = int(duration_s // cycle_time_s)
    w = cycle_time_s / 900.0
    phase = qty_per_cycle ** 0.7
    res = []
    for i in range(n):
        t = (i + 0.5) * w
        decay = qty_per_cycle / (1 + t * DECAY)
        noise = max(0.0, (math.cos(phase + t / 12) + math.cos(phase / 2 + t / 5) + math.cos(t / 2)) / 3)
        res.append(int(w * decay * (1 + NOISE * noise)))
    return res


def avg_per_hour(qty_per_cycle: float, cycle_time_s: float, duration_s: float) -> float:
    """Average units/hour an extractor really delivers over its whole program."""
    if duration_s <= 0 or cycle_time_s <= 0:
        return 0.0
    out = outputs(qty_per_cycle, cycle_time_s, duration_s)
    hours = len(out) * cycle_time_s / 3600.0
    return sum(out) / hours if hours else 0.0


@lru_cache(maxsize=256)
def _ref_rate(days: float) -> float:
    hours = days * 24
    cyc = cycle_seconds(hours)
    # average over a spread of base values so the cosine "noise" phase doesn't skew the ratio
    bases = range(1000, 20001, 500)
    return sum(avg_per_hour(b, cyc, hours * 3600) / b for b in bases) / len(bases)


def cycle_factor(days: float) -> float:
    """Average hourly output of a `days` program relative to a 3-day program
    (same heads, same planet). About 1.56 for 1 day, 0.63 for 7 days."""
    days = max(1 / 24, float(days))
    return _ref_rate(round(days, 3)) / _ref_rate(REFERENCE_DAYS)
