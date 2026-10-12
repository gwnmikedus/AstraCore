"""Plan warnings as structured notes: guided wording and step links, grouping and plurals."""
from __future__ import annotations

import re
from pathlib import Path

from astracore.modules.pi.planner import notices, optimizer
from astracore.modules.pi.settings import Settings
from test_planner import CHARS, PRICES, _area, _plan, pi  # noqa: F401 - shared SDE fixture and planner call

PI_SRC = Path(__file__).resolve().parents[1] / "src" / "astracore" / "modules" / "pi"
ADVANCED_ONLY = re.compile(r"slider|max (systems|jumps|tier)|constellation|colonies per planet \d", re.I)
# "slot(s) unused", "colony(ies)", "system(s), ≤": a noun with a hedged plural, not a call like f(s)
TENTATIVE_PLURAL = re.compile(r"(?<![\w.])(?!(float|str|int|len|sorted)\()[a-z]+\((s|es|ies)\)")


def test_plural_and_names():
    assert notices.plural(1, "slot") == "1 slot" and notices.plural(16, "slot") == "16 slots"
    assert notices.plural(1, "colony") == "1 colony" and notices.plural(2, "colony") == "2 colonies"
    assert notices.plural(3, "day") == "3 days" and notices.plural(1.0, "day") == "1 day"
    assert notices.plural(2.5, "day") == "2.5 days"
    assert notices.names(["A"]) == "A" and notices.names(["A", "B"]) == "A and B"
    assert notices.names(["A", "B", "C"]) == "A, B and C" and notices.names([]) == ""


def test_legacy_string_warnings_still_read_and_duplicates_merge():
    old = ["Storage check: 2 colonies can't buffer …", "Storage check: 2 colonies can't buffer …"]
    notes = notices.normalize(old + [notices.note("x", "New")])
    assert [n["text"] for n in notes] == ["Storage check: 2 colonies can't buffer …", "New"]
    assert notes[0]["steps"] == [] and notes[0]["level"] == "warn"
    assert notices.text_of("plain") == "plain" and notices.text_of(notes[1]) == "New"


def test_ccu_check_in_game_is_one_line_for_every_character():
    n = notices.ccu_check_in_game({"Ann": {(5, 4)}, "Bob": {(5, 4)}, "Cy": {(5, 4)}})
    assert n["code"] == "ccu_check"
    assert n["text"].startswith("Check in game: Ann, Bob and Cy have Command Center Upgrades 4, but the "
                                "templates were saved with a level 5 command center.")
    mixed = notices.ccu_check_in_game({"Ann": {(5, 4)}, "Bob": {(5, 3)}})
    assert "Ann has Command Center Upgrades 4 and Bob has Command Center Upgrades 3" in mixed["text"]
    assert notices.ccu_check_in_game({}) is None


def test_low_ccu_characters_are_grouped():
    chars = [{"name": n, "ccu_level": lvl} for n, lvl in [("A", 0), ("B", 1), ("C", 3), ("D", 3), ("E", 5)]]
    notes = notices.low_ccu(chars, 4)
    assert [n["code"] for n in notes] == ["ccu_low", "ccu_factories_only"]
    assert notes[0]["text"] == "A and B have Command Center Upgrades below 2; no template fits, so they are left out."
    assert notes[1]["text"].startswith("C and D have Command Center Upgrades 3: only factory templates fit")
    one = notices.low_ccu([{"name": "Low", "ccu_level": 1}], 4)
    assert one[0]["text"] == "Low has Command Center Upgrades 1; no template fits, so Low is left out."


def test_unused_slots_has_guided_wording_and_steps():
    n = notices.unused_slots(1, 3, 3, 1)
    assert n["text"].startswith("1 slot is unused:") and "max jumps 3" in n["text"]
    assert n["guided"].startswith("1 slot is unused:") and not ADVANCED_ONLY.search(n["guided"])
    assert n["steps"] == ["area", "share", "goal"]
    assert notices.unused_slots(16, 0, 6, 2)["text"].startswith("16 slots are unused:")


def test_storage_note_counts_properly():
    one = notices.storage([("P I", "Biocells")], 1)
    assert "1 colony can't buffer 1 day of inputs or products in its launchpad" in one["text"]
    many = notices.storage([(f"P {i}", "Water") for i in range(6)], 3)
    assert "6 colonies can't buffer 3 days" in many["text"] and many["text"].count("Water") == 4
    assert many["steps"] == ["cycle"]


def test_plan_returns_structured_notes_that_fit_the_guided_setup(pi):  # noqa: F811
    res = _plan(pi, chars=[{"character_id": 1, "name": "A", "slots": 12, "ccu_level": 5, "colonies": []}])
    assert "error" not in res, res
    for w in res["warnings"]:
        assert set(w) >= {"code", "text", "steps", "level"}
        assert all(s in notices.STEPS for s in w["steps"])
        assert not ADVANCED_ONLY.search(w.get("guided", w["text"])) or not w["steps"], w
    unused = next(w for w in res["warnings"] if w["code"] == "unused_slots")
    assert "area" in unused["steps"] and "(s)" not in unused["text"]


def test_no_fit_error_points_to_the_area_step(pi):  # noqa: F811
    s = Settings(hub_system="HUB", max_jumps=1, max_systems=0, effort=100, max_tier=1)
    area = _area()
    res = optimizer.plan(pi, s, area, {int(k): v for k, v in area["systems"].items()}, CHARS, PRICES, [])
    assert res["error"] == optimizer.NO_FIT and res["error_steps"] == ["area"]
    assert "constellation" not in res["error"]


def test_no_tentative_plurals_in_planner_texts():
    hits = [f"{p.relative_to(PI_SRC)}:{i}" for p in PI_SRC.rglob("*") if p.suffix in {".py", ".html"}
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if TENTATIVE_PLURAL.search(line)]
    assert hits == []
