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


def test_home_hero_plays_the_film_once_over_the_header_without_a_video():
    home = _home()
    hero = home[home.index('class="platform-hero"'):home.index("</section>", home.index('class="platform-hero'))]
    # the header is all there underneath: picture, copy and caption; the film is a layer over it
    assert 'class="platform-scene"' in hero and 'id="hero-title"' in hero and 'class="hero-caption"' in hero
    assert "data-hero-film" in hero and "data-hero-film-toggle" in hero and "data-hero-film-skip" in hero
    assert re.search(r'<div class="hero-film" data-hero-film aria-hidden="true"', hero)   # decorative: the copy carries it
    assert re.search(r'data-hero-film-replay hidden>', hero) and "Play the film" in hero
    assert re.search(r'data-hero-film-bar hidden>', hero)                                 # no JS: the plain header
    assert "Fictional example pilots and figures" in hero
    assert "<video" not in home and "trailer-dialog" not in home and "astracore-trailer.mp4" not in home
    for path in ("js/hero-film.js", "js/hero-film-scenes.js", "css/hero-film.css"):
        assert assets.asset(path) in home, path
    assert not (STATIC / "video" / "astracore-trailer.mp4").exists()
    # sound is opt-in: the synth and score load only after a click, so the page never ships or starts them
    for path in ("js/hero-film-audio.js", "js/hero-film-score.js"):
        assert f'src="{assets.asset(path)}"' not in home
        assert assets.asset(path) in hero, path            # the player finds them on the hero's data attributes
    assert "data-hero-film-sound" in hero and "Sound on" in hero


def test_bundled_scenes_are_current_and_respect_the_style_policy():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_hero_film", ROOT / "scripts" / "trailer" / "build_hero_film.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert build.main(check=True) == 0, "run python scripts/trailer/build_hero_film.py"
    bundle = (STATIC / "js" / "hero-film-scenes.js").read_text()
    assert not re.search(r'\bstyle\s*=\s*\\?["\']', bundle)          # inline styles became data-css
    assert "data-css=" in bundle and "kit.boot(" in bundle
    assert "kit.score(" not in bundle                                # the score loads apart, with the sound
    assert "kit.score(" in (STATIC / "js" / "hero-film-score.js").read_text()
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


def test_film_counts_the_wizards_six_main_questions():
    """The film's stepper and "Step N of M" copy follow the wizard's main questions (#244)."""
    guide = (ROOT / "src" / "astracore" / "modules" / "pi" / "templates" / "pi" / "guide.html").read_text()
    titles = re.findall(r"\{id: '(\w+)', title: '([^']+)'", guide)
    optional = set(re.findall(r"'(\w+)'", re.search(r"OPTIONAL_IDS = new Set\(\[([^\]]*)\]", guide).group(1)))
    main = [title for step, title in titles if step not in optional]   # the main questions, then the result
    code = "\n".join(p.read_text() for p in FILM.glob("*.js"))
    steps = re.search(r"const STEPS = \[([^\]]*)\]", (FILM / "shared.js").read_text()).group(1)
    assert re.findall(r"'([^']+)'", steps) == main
    assert set(re.findall(r"Step \d of (\d)", code)) == {str(len(main) - 1)}
