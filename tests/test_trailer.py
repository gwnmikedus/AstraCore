"""The home hero's trailer: a poster card, a dialog with the film, honest credits and a web-sized file (#216)."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from astracore.core import assets

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "astracore" / "static"


def _home():
    from astracore.app import app
    with TestClient(app) as c:
        return c.get("/").text


def test_home_hero_offers_the_trailer_in_a_dialog():
    home = _home()
    hero = home[home.index('class="platform-hero"'):home.index("</section>", home.index('class="platform-hero"'))]
    assert 'data-trailer-open' in hero and 'aria-controls="trailer-dialog"' in hero
    assert "Watch the trailer · 1:00" in hero
    dialog = re.search(r'<dialog id="trailer-dialog".*?</dialog>', home, re.S).group(0)
    assert f'src="{assets.asset("video/astracore-trailer.mp4")}"' in dialog
    assert 'preload="none"' in dialog and "controls" in dialog and "autoplay" not in dialog
    for credit in ("Fictional example", "estimates, not guaranteed income", "DalShooth", "EVE Online belongs to CCP"):
        assert credit in dialog
    assert assets.asset("js/trailer.js") in home


def test_trailer_files_exist_and_stay_web_sized():
    video = STATIC / "video" / "astracore-trailer.mp4"
    assert video.read_bytes()[4:8] == b"ftyp"
    assert video.stat().st_size < 25 * 1024 * 1024
    assert (STATIC / "img" / "trailer" / "trailer-poster-1280.jpg").stat().st_size < 400 * 1024


def test_trailer_source_is_sixty_seconds_and_self_contained():
    film = ROOT / "docs" / "demo" / "trailer" / "film"
    scenes = json.loads((film / "scenes.json").read_text())["scenes"]
    assert round(sum(s["dur"] for s in scenes), 3) == 60
    for s in scenes:
        assert (film / f"scene-{s['id']}.js").exists(), s["id"]
    code = "\n".join(p.read_text() for p in film.glob("*.js"))
    assert not re.search(r"https?://", code), "the film draws everything itself and loads nothing"
