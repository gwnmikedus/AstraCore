"""Templates and the page renderer shared by core and modules."""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import jinja2
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from astracore import config

from . import fmt, registry
from .icons import icon

PKG = Path(__file__).resolve().parent.parent
TEMPLATE_DIRS = [PKG / "templates", PKG / "modules" / "pi" / "templates"]

templates = Jinja2Templates(directory=str(TEMPLATE_DIRS[0]))
templates.env.loader = jinja2.ChoiceLoader([jinja2.FileSystemLoader(str(d)) for d in TEMPLATE_DIRS])
templates.env.filters.update(fmt.FILTERS)
templates.env.globals["icon"] = icon


def asset(path: str) -> str:
    """/static URL with the file's mtime, so browsers pick up a new stylesheet/script right away."""
    f = PKG / "static" / path
    try:
        v = int(f.stat().st_mtime)
    except OSError:
        v = 0
    return f"/static/{path}?v={v}"


templates.env.globals["asset"] = asset


def current_user(request: Request) -> Optional[dict]:
    return getattr(request.state, "user", None)


def render(request: Request, name: str, *, module_id: Optional[str] = None, status_code: int = 200,
           **ctx: Any) -> HTMLResponse:
    """Render a page inside the shared layout."""
    module = registry.get(module_id) if module_id else None
    user = current_user(request)
    sess = getattr(request.state, "session", None)
    ctx.setdefault("subnav", module.nav if module and user else None)
    ctx.setdefault("active_nav", request.url.path)
    ctx.update(
        request=request, user=user, module=module, modules=registry.MODULES,
        local_mode=not config.PRODUCTION, csrf_token=(sess or {}).get("csrf"),
        nonce=getattr(request.state, "nonce", ""),
        flash=ctx.get("flash") or _flash(request),
        flash_kind=ctx.get("flash_kind") or (request.query_params.get("kind") if _flash(request) else None),
    )
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _sign(msg: str) -> str:
    from .sessions import _secret
    return hmac.new(_secret(), ("flash:" + msg).encode(), hashlib.sha256).hexdigest()[:20]


def _flash(request: Request) -> Optional[str]:
    """Flash messages travel in the redirect URL, signed, so nobody can craft a link that puts
    their own text on the site."""
    msg, sig = request.query_params.get("msg"), request.query_params.get("sig", "")
    if msg and hmac.compare_digest(sig, _sign(msg)):
        return msg
    return None


def safe_path(url: Optional[str], default: str = "/") -> str:
    """Only local paths: `back`/`next` form values must never send people to another site."""
    if not url or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return default
    return url


def redirect(url: str, msg: Optional[str] = None, kind: Optional[str] = None) -> RedirectResponse:
    url = safe_path(url)
    if msg:
        url += ("&" if "?" in url else "?") + "msg=" + quote(msg) + "&sig=" + _sign(msg)
        if kind:
            url += "&kind=" + quote(kind)
    return RedirectResponse(url, status_code=303)
