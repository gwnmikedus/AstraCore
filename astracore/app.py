"""The Astracore web app: core pages + every registered module."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .core.web import PKG
from .modules.pi import module as _pi_module  # noqa: F401  (registers AstracorePI)
from .modules.pi.routes import router as pi_router


def create_app() -> FastAPI:
    debug = not config.PRODUCTION
    app = FastAPI(title="Astracore", debug=debug,
                  docs_url="/docs" if debug else None, redoc_url=None,
                  openapi_url="/openapi.json" if debug else None)
    app.mount("/static", StaticFiles(directory=str(PKG / "static")), name="static")

    @app.on_event("startup")
    async def _startup() -> None:
        db.init()

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return PlainTextResponse("ok")

    app.include_router(pi_router)
    return app


app = create_app()
