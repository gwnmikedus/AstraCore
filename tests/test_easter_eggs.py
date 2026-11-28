"""Guards the intentional easter eggs in rendered pages (docs/easter-eggs.md)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src" / "astracore" / "templates"


def test_footer_year_tooltip_matches_the_copyright_year():
    base = (TEMPLATES / "base.html").read_text()
    match = re.search(r'© <span title="YC (\d+) in New Eden" data-egg-hover="yc_year">(\d{4})</span>', base)
    assert match, "the YC year tooltip is an intentional easter egg"
    assert int(match.group(1)) == int(match.group(2)) - 1898


def test_404_tooltip_and_easter_egg_script_are_present():
    error = (TEMPLATES / "error.html").read_text()
    assert 'title="Not on your overview. Try warping to the home page."' in error
    assert "js/easter-eggs.js" in (TEMPLATES / "base.html").read_text()
    assert (ROOT / "src" / "astracore" / "static" / "js" / "easter-eggs.js").exists()
