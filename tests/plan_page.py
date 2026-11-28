"""Helpers for tests of the plan pages: their server data block and their static scripts."""
from __future__ import annotations

import json
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "astracore" / "static" / "js"


def plan_data(html: str) -> dict:
    """The page's <script type="application/json" id="plan-data"> block, parsed."""
    m = re.search(r'<script type="application/json" id="plan-data">(.*?)</script>', html, re.S)
    assert m, "plan-data block"
    return json.loads(m.group(1))


def script(name: str) -> str:
    """A static script's source, e.g. script("guide.js")."""
    return (JS / name).read_text()
