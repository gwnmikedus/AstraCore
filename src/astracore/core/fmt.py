"""The one number formatter (Jinja side). Mirrors static/js/fmt.js exactly.

Locale is fixed to EVE's own (`en`): `123,379 m³`, `46.2M ISK`, `1.24B ISK`, never `-0`.
"""
from __future__ import annotations

import math
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except Exception:  # noqa: BLE001 - None, '', jinja Undefined, junk: all "no number"
        return None
    return x if x == x else None   # NaN -> None


def _fixed(x: float, digits: int) -> str:
    """Like f"{x:,.{digits}f}" but rounding halves away from zero, as the browser's Intl does."""
    q = Decimal(repr(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f"{q:,.{digits}f}"


def _nz(s: str) -> str:
    """Never show a negative zero ("-0", "-0.0M")."""
    return s[1:] if s.startswith("-") and not any(c in "123456789" for c in s) else s


def num(v: Any, digits: int = 0) -> str:
    """Thousands separators, `digits` decimals: 123379 -> '123,379'."""
    x = _f(v)
    if x is None:
        return "–"
    return _nz(_fixed(x, digits))


def isk(v: Any) -> str:
    """Compact ISK: 46.2M, 1.24B, 950k, 812."""
    x = _f(v)
    if x is None:
        return "–"
    a = abs(x)
    if a >= 1e12:
        s = _fixed(x / 1e12, 2) + "T"
    elif a >= 1e9:
        s = _fixed(x / 1e9, 2) + "B"
    elif a >= 1e6:
        s = _fixed(x / 1e6, 1) + "M"
    elif a >= 1e3:
        s = _fixed(x / 1e3, 0) + "k"
    else:
        s = _fixed(x, 0)
    return _nz(s)


def m3(v: Any) -> str:
    """Volume: '123,379 m³' (one decimal only below 10 m³)."""
    x = _f(v)
    if x is None:
        return "–"
    return num(x, 1 if 0 < abs(x) < 10 else 0) + " m³"


def count(v: Any) -> str:
    """Counts are whole things: 94.5 restarts/week -> '95'."""
    x = _f(v)
    return "–" if x is None else num(x)


def pct(v: Any, digits: int = 1) -> str:
    x = _f(v)
    if x is None:
        return "–"
    if digits == 0 and 0 < x < 1:
        return "<1%"
    s = f"{x:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{x:.0f}"
    return _nz(s) + "%"


def ago(ts: Any) -> str:
    if not ts:
        return "never"
    d = time.time() - float(ts)
    if d < 120:
        return "just now"
    if d < 7200:
        return f"{int(d // 60)} min ago"
    if d < 172800:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} days ago"


def hours(h: Any) -> str:
    x = _f(h)
    if x is None:
        return "?"
    if abs(x) >= 48:
        return f"{x / 24:.1f} days".replace(".0 ", " ")
    return f"{x:.1f} h"


def duration(minutes: Any) -> str:
    """Time spent, from minutes: '45 min', '1 h 05 min'."""
    x = _f(minutes)
    if x is None or math.isinf(x):
        return "–"
    m = int(Decimal(repr(max(0.0, x))).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


FILTERS = {"num": num, "isk": isk, "m3": m3, "count": count, "pct": pct, "ago": ago, "hours": hours,
           "duration": duration}
