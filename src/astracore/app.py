"""The Astracore web app: core pages + every registered module."""
from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager, suppress
from logging.handlers import RotatingFileHandler

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db
from .core import auth, community, crypto, pages, releases, sessions
from .core.assets import REVALIDATE, CacheHeaders, VersionedStatic
from .core.ratelimit import RequestLimitMiddleware
from .core.web import PKG, redirect, render
from .esi import errors as esi_errors
from .esi import sso
from .esi.client import ESIError
from .modules.pi import module as _pi_module  # noqa: F401  (registers AstracorePI)
from .modules.pi import service as pi_service
from .modules.pi.routes import legacy as pi_legacy
from .modules.pi.routes import router as pi_router

log = logging.getLogger("astracore")


def _setup_logging() -> None:
    if any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        return
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(config.LOG_DIR / f"astracore-{config.MODE}.log", maxBytes=5_000_000, backupCount=5)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except OSError:
        pass


class SecurityHeaders:
    """CSP with a per-request script nonce, no framing, same-origin referrers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["nonce"] = nonce
        csp = ("default-src 'self'; "
               f"script-src 'self' 'nonce-{nonce}'; "
               "style-src 'self' 'unsafe-inline'; "
               "img-src 'self' data: https://images.evetech.net https://avatars.githubusercontent.com; "
               "connect-src 'self'; "
               "form-action 'self' https://login.eveonline.com; "
               "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
        if not config.PRODUCTION and scope["path"].startswith(("/docs", "/openapi")):
            csp = ""   # Swagger UI loads its own scripts (local mode only)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                h = list(message.get("headers", []))
                if csp:
                    h.append((b"content-security-policy", csp.encode()))
                h += [(b"x-frame-options", b"DENY"), (b"referrer-policy", b"same-origin"),
                      (b"x-content-type-options", b"nosniff")]
                if config.PRODUCTION:
                    h.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = h
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _wants_json(request: Request) -> bool:
    return (request.url.path.startswith(("/pi/api/", "/api/"))
            or "application/json" in request.headers.get("accept", "")
            or request.headers.get("content-type", "").startswith("application/json"))


def create_app() -> FastAPI:
    _setup_logging()
    debug = not config.PRODUCTION
    @asynccontextmanager
    async def lifespan(_app):
        db.init()
        if crypto.rotating():
            log.info("token key rotation: re-encrypted %d stored EVE logins with the first key",
                     db.reencrypt_tokens())
        from .esi.character import clear_legacy_private_cache
        clear_legacy_private_cache()
        sessions.purge_expired()
        log.info("Astracore started in %s mode on %s", config.MODE, config.PUBLIC_URL)
        sync_task = asyncio.create_task(community.run_sync_loop())
        warm_task = asyncio.create_task(pi_service.warm_history())
        try:
            yield
        finally:
            for task in (sync_task, warm_task):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="AstraCore", version=releases.current()["version"], debug=debug,
                  dependencies=[Depends(sessions.csrf_protect)],
                  docs_url="/docs" if debug else None, redoc_url=None, lifespan=lifespan,
                  openapi_url="/openapi.json" if debug else None)
    app.add_middleware(RequestLimitMiddleware)   # inside the session: limits know the profile
    app.add_middleware(sessions.SessionMiddleware)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(CacheHeaders)
    app.mount("/static", VersionedStatic(directory=str(PKG / "static")), name="static")

    # Fixed paths browsers and phones ask for on their own: always revalidated, so a new icon shows up.
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(PKG / "static" / "img" / "favicon-32.png", media_type="image/png",
                            headers={"cache-control": REVALIDATE})

    @app.get("/apple-touch-icon.png", include_in_schema=False)
    @app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
    async def apple_touch_icon():
        return FileResponse(PKG / "static" / "img" / "apple-touch-icon.png", media_type="image/png",
                            headers={"cache-control": REVALIDATE})

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return PlainTextResponse("ok")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 401:
            if _wants_json(request):
                return JSONResponse({"error": exc.detail}, status_code=401)
            return redirect("/", "Sign in first.")
        if _wants_json(request):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        msg = {404: "This page doesn't exist.", 403: str(exc.detail), 405: "That doesn't work here."}.get(
            exc.status_code, str(exc.detail))
        return render(request, "error.html", page="error", page_title="Error", code=exc.status_code, message=msg,
                      status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        if _wants_json(request):
            return JSONResponse({"error": "Bad request."}, status_code=400)
        return render(request, "error.html", page="error", page_title="Error", code=400,
                      message="That request didn't look right.", status_code=400)

    async def esi_down(request: Request, exc: Exception):
        """ESI (or EVE SSO, or a public data file) failed and the page had no stored copy to fall back on:
        a plain explanation with a retry instead of the generic error page. Details go to the log."""
        log.warning("EVE data unavailable on %s %s: %r", request.method, request.url.path, exc)
        msg = esi_errors.explain(exc)
        if _wants_json(request):
            return JSONResponse({"error": msg}, status_code=503)
        retry = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return render(request, "error.html", page="error", page_title="EVE data unavailable", code=503,
                      message=msg, retry=retry if request.method == "GET" else None, status_code=503)

    for exc_type in (ESIError, sso.SSOError, httpx.HTTPError):
        app.add_exception_handler(exc_type, esi_down)

    @app.exception_handler(Exception)
    async def crash(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        if _wants_json(request):
            return JSONResponse({"error": "Something went wrong on our side. It has been logged."}, status_code=500)
        return render(request, "error.html", page="error", page_title="Error", code=500,
                      message="Something went wrong on our side. It has been logged.", status_code=500)

    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(community.router)
    app.include_router(pi_router)
    app.include_router(pi_legacy)
    return app


app = create_app()
