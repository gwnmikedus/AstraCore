"""The app gzips pages and text assets, but never the streamed what-if comparison or already-compressed files."""
import asyncio
import gzip
import json

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route
from fastapi.testclient import TestClient

from astracore.core import assets
from astracore.core.compress import Compress
from astracore.modules.pi import routes

from test_core import browser, csrf, eve, new_id, sso_login  # noqa: F401 - pytest fixtures

GZIP = {"accept-encoding": "gzip"}


def raw(client, method, url, **kw):
    """The response as sent: httpx would otherwise decompress it silently."""
    with client.stream(method, url, **kw) as r:
        return r, b"".join(r.iter_raw())


def test_pages_and_text_assets_are_gzipped_when_the_browser_accepts_it(browser):
    client = browser()
    for url in ("/", assets.asset("css/astracore.css"), assets.asset("js/hero-film.js"), assets.asset("img/icons.svg")):
        r, body = raw(client, "GET", url, headers=GZIP)
        assert r.status_code == 200, url
        assert r.headers["content-encoding"] == "gzip", url
        assert "accept-encoding" in r.headers["vary"].lower(), url
        assert int(r.headers["content-length"]) == len(body), url
        plain = gzip.decompress(body)
        assert len(body) < len(plain) / 2, url
    # the cache rules are unchanged by compression
    r, _ = raw(client, "GET", assets.asset("css/astracore.css"), headers=GZIP)
    assert "immutable" in r.headers["cache-control"]
    assert raw(client, "GET", "/", headers=GZIP)[0].headers["cache-control"] == "private, no-cache"


def test_compressed_css_still_revalidates_with_its_etag(browser):
    client = browser()
    url = assets.asset("css/astracore.css")
    r, _ = raw(client, "GET", url, headers=GZIP)
    etag = r.headers["etag"]
    assert etag.startswith("W/")                    # the gzipped bytes are a different representation
    assert client.get(url, headers={**GZIP, "if-none-match": etag}).status_code == 304


def test_without_accept_encoding_or_for_images_nothing_is_compressed(browser):
    client = browser()
    r, body = raw(client, "GET", "/", headers={"accept-encoding": "identity"})
    assert "content-encoding" not in r.headers and body.lstrip().startswith(b"<!")
    r, _ = raw(client, "GET", assets.asset("img/favicon-32.png"), headers=GZIP)
    assert "content-encoding" not in r.headers


def test_css_rewrite_is_cached_until_the_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "STATIC", tmp_path)
    monkeypatch.setattr(assets, "_hashes", {})
    monkeypatch.setattr(assets, "_css", {})
    (tmp_path / "css").mkdir()
    (tmp_path / "img").mkdir()
    css, img = tmp_path / "css" / "a.css", tmp_path / "img" / "x.svg"
    img.write_text("<svg/>")
    css.write_text('b { background: url("../img/x.svg"); }')
    calls = []
    real = assets.rewrite_css
    monkeypatch.setattr(assets, "rewrite_css", lambda *a: calls.append(1) or real(*a))
    first, etag = assets.versioned_css("css/a.css")
    assert assets.versioned_css("css/a.css") == (first, etag) and len(calls) == 1
    img.write_text("<svg></svg>")                   # a referenced file changed: its versioned URL must follow
    second, etag2 = assets.versioned_css("css/a.css")
    assert len(calls) == 2 and second != first and etag2 != etag
    assert f"?v={assets.version('img/x.svg')}".encode() in second


def test_streams_are_never_buffered_by_compression():
    async def chunks():
        for i in range(3):
            yield json.dumps({"n": i}).encode() * 200 + b"\n"
            await asyncio.sleep(0)

    app = Starlette(routes=[
        Route("/ndjson", lambda r: StreamingResponse(chunks(), media_type="application/x-ndjson")),
        Route("/sse", lambda r: StreamingResponse(chunks(), media_type="text/event-stream")),
        Route("/no-transform", lambda r: StreamingResponse(chunks(), media_type="text/plain",
                                                           headers={"cache-control": "no-cache, no-transform"})),
        Route("/text", lambda r: PlainTextResponse("x" * 5000)),
        Route("/small", lambda r: PlainTextResponse("x" * 100)),
    ])
    app.add_middleware(Compress)
    client = TestClient(app)
    for path in ("/ndjson", "/sse", "/no-transform"):
        r, body = raw(client, "GET", path, headers=GZIP)
        assert "content-encoding" not in r.headers, path
        assert body.count(b"\n") == 3, path
    r, body = raw(client, "GET", "/text", headers=GZIP)
    assert r.headers["content-encoding"] == "gzip" and gzip.decompress(body) == b"x" * 5000
    r, body = raw(client, "GET", "/small", headers=GZIP)
    assert "content-encoding" not in r.headers and body == b"x" * 100


def test_the_whatif_stream_reaches_the_browser_uncompressed(browser, eve, monkeypatch):  # noqa: F811
    async def whatif_card(pid, base, opt):
        return {"id": opt["id"], "totals": {"isk_per_day": 1e6 * opt["id"], "systems": 1}, "mix": "x" * 2000,
                "facts": {"minutes_per_week": 60}}
    monkeypatch.setattr(routes, "_whatif_card", whatif_card)
    client = browser()
    sso_login(client, eve, new_id(), "Fictional Stream Pilot")
    options = [{"id": t, "patch": {"max_tier": t}} for t in (1, 2, 3)]
    r, body = raw(client, "POST", "/pi/api/whatif", json={"base": {}, "options": options, "stream": True},
                  headers={**GZIP, "X-CSRF-Token": csrf(client)})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    assert "content-encoding" not in r.headers
    assert "no-transform" in r.headers["cache-control"]
    events = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert events[-1] == {"done": True}
