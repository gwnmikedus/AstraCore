"""The home hero plays the PI trailer live from its source (no video file), within the content security policy."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from astracore.core import assets

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "astracore" / "static"
FILM = ROOT / "docs" / "demo" / "trailer" / "film"


def _home():
    from astracore.app import app
    with TestClient(app) as c:
        return c.get("/").text


def test_home_hero_plays_the_film_live_without_a_video():
    home = _home()
    hero = home[home.index('class="platform-hero film-hero"'):home.index("</section>", home.index('class="platform-hero'))]
    assert "data-hero-film" in hero and 'aria-hidden="true"' in hero and "data-hero-film-toggle" in hero
    assert "fictional example pilots and figures" in hero
    assert "<video" not in home and "trailer-dialog" not in home and "astracore-trailer.mp4" not in home
    for path in ("js/hero-film.js", "js/hero-film-scenes.js", "css/hero-film.css"):
        assert assets.asset(path) in home, path
    assert not (STATIC / "video" / "astracore-trailer.mp4").exists()


def test_bundled_scenes_are_current_and_respect_the_style_policy():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_hero_film", ROOT / "scripts" / "trailer" / "build_hero_film.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert build.main(check=True) == 0, "run python scripts/trailer/build_hero_film.py"
    bundle = (STATIC / "js" / "hero-film-scenes.js").read_text()
    assert not re.search(r'\bstyle\s*=\s*\\?["\']', bundle)          # inline styles became data-css
    assert "data-css=" in bundle and "kit.boot(" in bundle
    assert "kit.score(" not in bundle                                # the hero plays without sound
    css = (STATIC / "css" / "hero-film.css").read_text()
    for rule in css.splitlines()[1:]:
        assert rule.startswith(".hero-film-stage"), rule               # scoped: can't touch the page


def test_film_source_is_sixty_seconds_and_self_contained():
    scenes = json.loads((FILM / "scenes.json").read_text())["scenes"]
    assert round(sum(s["dur"] for s in scenes), 3) == 60
    for s in scenes:
        assert (FILM / f"scene-{s['id']}.js").exists(), s["id"]
    code = "\n".join(p.read_text() for p in FILM.glob("*.js"))
    assert not re.search(r"https?://", code), "the film draws everything itself and loads nothing"
    player = (STATIC / "js" / "hero-film.js").read_text()
    assert not re.search(r"https?://", player)
