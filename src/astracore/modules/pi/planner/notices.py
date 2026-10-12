"""Plan warnings as structured notes, so each view can word and link them its own way.

A note is a dict:
    code    what it is about (stable, for tests and styling)
    text    the wording for the Advanced planner (may name its controls)
    guided  the wording for the guided setup (only its answers), when it differs from `text`
    steps   guided-setup steps that change it ("goal", "cycle", "area", "tier", "share", "chain",
            "sell", "batch"), most useful first; the result links "Change <answer>" to each
    level   "warn" (do something) or "info" (good to know); info notes are listed last

Plans saved before notes existed hold plain strings; `normalize` and `text_of` accept both.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

STEPS = ("goal", "cycle", "area", "tier", "share", "chain", "sell", "batch")

Note = Union[str, dict]


def note(code: str, text: str, *, guided: Optional[str] = None, steps: Sequence[str] = (),
         level: str = "warn") -> dict:
    assert all(s in STEPS for s in steps), steps
    out = {"code": code, "text": text, "steps": list(steps), "level": level}
    if guided and guided != text:
        out["guided"] = guided
    return out


def text_of(w: Note) -> str:
    """The Advanced wording of a note or a legacy plain-string warning."""
    return w if isinstance(w, str) else str(w.get("text", ""))


def normalize(ws: Iterable[Note]) -> List[dict]:
    """Every warning as a note; plain strings from older plans become notes without steps.
    Identical notes are listed once."""
    out, seen = [], set()
    for w in ws or []:
        n = note("note", w) if isinstance(w, str) else w
        key = (n.get("code"), n.get("text"))
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


def plural(n: float, one: str, many: Optional[str] = None) -> str:
    """"1 slot", "3 slots", "2 colonies": the count with the right form of the noun."""
    many = many or (one[:-1] + "ies" if one.endswith("y") and one[-2:-1] not in "aeiou" else one + "s")
    shown = f"{n:g}" if isinstance(n, float) else str(n)
    return f"{shown} {one if n == 1 else many}"


def names(xs: Sequence[str]) -> str:
    """"A", "A and B", "A, B and C"."""
    xs = list(xs)
    if len(xs) < 2:
        return "".join(xs)
    return ", ".join(xs[:-1]) + " and " + xs[-1]


def _has(n: int) -> str:
    return "has" if n == 1 else "have"


def low_ccu(characters: Sequence[dict], miner_ccu: int) -> List[dict]:
    """Characters whose Command Center Upgrades keep them (partly) out of the plan, grouped."""
    left_out, factories_only = [], defaultdict(list)
    for c in characters:
        lvl = int(c.get("ccu_level", 0))
        if lvl < 2:
            left_out.append((c["name"], lvl))
        elif lvl < miner_ccu:
            factories_only[lvl].append(c["name"])
    out = []
    if len(left_out) == 1:
        who, lvl = left_out[0]
        out.append(note("ccu_low", f"{who} has Command Center Upgrades {lvl}; no template fits, so {who} is left out."))
    elif left_out:
        out.append(note("ccu_low", f"{names([w for w, _ in left_out])} have Command Center Upgrades below 2; "
                                   f"no template fits, so they are left out."))
    for lvl in sorted(factories_only):
        who = factories_only[lvl]
        out.append(note("ccu_factories_only",
                        f"{names(who)} {_has(len(who))} Command Center Upgrades {lvl}: only factory "
                        f"templates fit (miners need {miner_ccu})."))
    return out


def ccu_check_in_game(levels: Dict[str, set]) -> Optional[dict]:
    """One note for every character whose templates were saved at a higher command center level.
    `levels` maps character name -> {(template level, character level)}."""
    if not levels:
        return None
    by_level: Dict[int, List[str]] = defaultdict(list)
    tpl = 0
    for who, pairs in sorted(levels.items()):
        tl, cl = max(pairs)
        tpl = max(tpl, tl)
        by_level[cl].append(who)
    groups = [f"{names(by_level[cl])} {_has(len(by_level[cl]))} Command Center Upgrades {cl}"
              for cl in sorted(by_level, reverse=True)]
    n = sum(len(v) for v in by_level.values())
    fit = (f"level {next(iter(by_level))}" if len(by_level) == 1 else "those levels")
    return note("ccu_check",
                f"Check in game: {' and '.join(groups)}, but the templates were saved with a level {tpl} "
                f"command center. The structures fit {fit} on paper; place one first and confirm the game "
                f"accepts it before building the rest" + (" with each character." if n > 1 else "."))


def unused_slots(free: int, max_systems: int, max_jumps: int, per_planet: int) -> dict:
    """Slots the plan leaves empty: nothing else in reach pays for the time it takes."""
    are = "is" if free == 1 else "are"
    return note(
        "unused_slots",
        f"{plural(free, 'slot')} {are} unused: the selected area or limits (max systems "
        f"{max_systems or '∞'}, max jumps {max_jumps}, colonies per planet {per_planet}) don't offer "
        f"anything worth the time it takes. Loosen a limit or value your time lower.",
        guided=f"{plural(free, 'slot')} {are} unused: nothing else in your area pays enough for the time "
               f"it takes. Allow more systems or more of your colonies per planet, or value your time lower.",
        steps=("area", "share", "goal"))


def storage(tight: Sequence[Tuple[str, str]], cycle_days: float) -> dict:
    """Colonies whose launchpad and storage can't hold a full login cycle."""
    shown = ", ".join(f"{planet} {product}" for planet, product in tight[:4]) + (", …" if len(tight) > 4 else "")
    n = len(tight)
    return note("storage",
                f"Storage check: {plural(n, 'colony')} can't buffer {plural(cycle_days, 'day')} of inputs "
                f"or products in {'its' if n == 1 else 'their'} launchpad and storage space ({shown}). "
                f"Plan the extra visits shown per colony, or add storage in game.",
                steps=("cycle",))
