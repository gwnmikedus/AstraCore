"""Static asset versioning: every static URL carries a content hash and the cache headers follow it."""
import re

from fastapi.testclient import TestClient

from astracore.core import assets, eveimg


def _client():
    from astracore.app import app
    return TestClient(app)


def test_pages_reference_only_versioned_static_urls():
    with _client() as c:
        home = c.get("/").text
    urls = re.findall(r'(?:src|href)="(/static/[^"]+)"', home)
    assert urls, "the home page should load static files"
    for u in urls:
        path, _, v = u.partition("?v=")
        assert v == assets.version(path), u


def test_versioned_static_is_immutable_and_unversioned_revalidates():
    url = assets.asset("img/logo.svg")
    with _client() as c:
        r = c.get(url)
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        assert c.get("/static/img/logo.svg").headers["cache-control"] == "no-cache"
        assert c.get("/static/img/logo.svg?v=stale00000").headers["cache-control"] == "no-cache"
        assert c.get("/static/img/nope.svg").status_code == 404


def test_css_urls_are_rewritten_to_versioned_fonts():
    with _client() as c:
        css = c.get(assets.asset("css/astracore.css"))
        assert css.headers["content-type"].startswith("text/css")
        fonts = re.findall(r'url\("(/static/fonts/[^"]+)"\)', css.text)
        assert fonts and all("?v=" in f for f in fonts)
        etag = css.headers["etag"]
        assert c.get(assets.asset("css/astracore.css"), headers={"if-none-match": etag}).status_code == 304
        assert c.get(fonts[0]).headers["cache-control"].endswith("immutable")


def test_pages_and_icons_are_never_cached_stale():
    with _client() as c:
        assert c.get("/").headers["cache-control"] == "private, no-cache"
        for p in ("/favicon.ico", "/apple-touch-icon.png"):
            r = c.get(p)
            assert r.status_code == 200 and r.headers["content-type"] == "image/png"
            assert r.headers["cache-control"] == "no-cache"


def test_hash_follows_content(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "STATIC", tmp_path)
    monkeypatch.setattr(assets, "_hashes", {})
    f = tmp_path / "a.txt"
    f.write_text("one")
    v1 = assets.version("a.txt")
    f.write_text("two!")
    assert assets.version("/static/a.txt") != v1


def test_eve_image_urls_are_versioned():
    assert re.search(r"\?v=[0-9a-f]{10}$", eveimg.planet_url("Lava"))
    assert "?v=" in eveimg.build_js()


def test_generated_eve_images_js_is_current():
    """Replaced an image? Run `python -m astracore.core.eveimg` so the browser map carries the new hash."""
    js = (assets.STATIC / "js" / "eve-images.js").read_text()
    assert js == eveimg.build_js()
