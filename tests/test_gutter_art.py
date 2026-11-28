"""Gutter art (#293): the generated partial matches its drawing script and stays decorative."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTIAL = ROOT / "src" / "astracore" / "templates" / "_gutter_art.html"


def _script():
    spec = importlib.util.spec_from_file_location("draw_gutter_art", ROOT / "scripts" / "draw_gutter_art.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_partial_is_generated_from_the_script():
    assert PARTIAL.read_text() == _script().render(), "run python scripts/draw_gutter_art.py"


def test_gutter_art_is_decorative_and_uses_tokens_only():
    html = PARTIAL.read_text()
    assert 'class="gutter-art gutter-art--{{ side }}" aria-hidden="true"' in html
    assert len(re.findall(r"<svg ", html)) == len(_script().ART) >= 5
    assert not re.search(r"<script|\son[a-z]+=|href=|style=|(fill|stroke)='#", html, re.I)


def test_landing_places_gutter_art_on_alternating_sides():
    home = (ROOT / "src" / "astracore" / "templates" / "home.html").read_text()
    sides = re.findall(r"gutter_art\('(\w+)', '(left|right)'", home)
    assert len(sides) >= 4
    assert all(a[1] != b[1] for a, b in zip(sides, sides[1:])), "sides alternate down the page"
