"""gzip for text responses: pages, CSS, JS, SVG and JSON.

Pages are mostly repeated markup (the community page is ~300 KB of HTML and ~20 KB gzipped), so compressing them at
the app saves the Cloudflare tunnel and every browser that talks to the app directly most of the bytes.

Left alone:
- streams: anything marked `Cache-Control: no-transform` (the what-if NDJSON stream sets it so no proxy buffers it),
  and NDJSON / server-sent events in any case: gzip would hold chunks back until its buffer fills;
- formats that are already compressed (PNG, WebP, WOFF2, ...), responses that already carry a Content-Encoding,
  small bodies, and responses without a body (304, HEAD).
"""
from __future__ import annotations

import zlib

from starlette.datastructures import Headers, MutableHeaders

MINIMUM_SIZE = 1024
LEVEL = 6
COMPRESSIBLE = ("text/", "application/json", "application/javascript", "application/manifest+json",
                "application/xml", "image/svg+xml")
STREAMING = ("text/event-stream", "application/x-ndjson")


def compressible(headers: Headers) -> bool:
    ctype = headers.get("content-type", "").lower()
    if "content-encoding" in headers or ctype.startswith(STREAMING):
        return False
    if "no-transform" in headers.get("cache-control", "").lower():
        return False
    return ctype.startswith(COMPRESSIBLE)


class Compress:
    def __init__(self, app, minimum_size: int = MINIMUM_SIZE, level: int = LEVEL):
        self.app = app
        self.minimum_size = minimum_size
        self.level = level

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or "gzip" not in Headers(scope=scope).get("accept-encoding", "").lower():
            return await self.app(scope, receive, send)

        start = None          # the held-back http.response.start, until the first body chunk decides
        encoder = None        # a zlib gzip stream once this response is being compressed
        passthrough = False

        async def wrapped(message):
            nonlocal start, encoder, passthrough
            kind = message["type"]
            if kind == "http.response.start":
                message["headers"] = list(message.get("headers", []))
                start = message
                passthrough = not compressible(Headers(raw=message["headers"]))
                if passthrough:
                    return await send(start)
                MutableHeaders(raw=message["headers"]).add_vary_header("Accept-Encoding")
                return
            if kind != "http.response.body":   # e.g. http.response.pathsend: the file goes out as is
                if start is not None and not passthrough and encoder is None:
                    passthrough = True
                    await send(start)
                return await send(message)
            if passthrough:
                return await send(message)
            body, more = message.get("body", b""), message.get("more_body", False)
            if encoder is None:
                if not more and len(body) < self.minimum_size:
                    passthrough = True
                    await send(start)
                    return await send(message)
                encoder = zlib.compressobj(self.level, zlib.DEFLATED, 31)   # wbits 31: gzip container
                headers = MutableHeaders(raw=start["headers"])
                headers["content-encoding"] = "gzip"
                etag = headers.get("etag")
                if etag and not etag.startswith("W/"):
                    headers["etag"] = "W/" + etag   # the bytes differ from the uncompressed variant
                data = encoder.compress(body) + (b"" if more else encoder.flush())
                if more:
                    del headers["content-length"]
                else:
                    headers["content-length"] = str(len(data))
                await send(start)
                return await send({"type": "http.response.body", "body": data, "more_body": more})
            data = encoder.compress(body) + (b"" if more else encoder.flush())
            await send({"type": "http.response.body", "body": data, "more_body": more})

        await self.app(scope, receive, wrapped)
