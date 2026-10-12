"""What an ESI or EVE SSO failure means for a pilot, in plain words with a next step (issue #80).

Exception text can hold ESI's raw reply, URLs or library internals: it goes to the server log only.
Pages and flash messages use `explain(exc)`, and a page that could still show its last known data
says so with `Outage.banner()` instead of failing."""
from __future__ import annotations

from typing import Iterable, Optional

import httpx

from . import sso
from .client import BUDGET, ESIError, ESIUnavailable

HEADLINE = "EVE's API isn't answering right now."

_KIND = {
    "timeout": "EVE's API (ESI) took too long to answer. Try again in a few minutes.",
    "unreachable": "EVE's API (ESI) couldn't be reached. Try again in a few minutes.",
    "server": "EVE's API (ESI) is having trouble on its side. It usually recovers within minutes; during "
              "EVE's daily downtime (around 11:00 UTC) this is normal. Try again later.",
    "error_limit": "EVE's API (ESI) asked AstraCore to slow down for a moment. Try again in a minute.",
}

# Problems shown next to a character's name ("Pilot: needs a new EVE login …").
NEEDS_LOGIN = "needs a new EVE login (access was revoked or expired). Log in with this character again."
TRANSFERRED = "was transferred to another player and removed from your profile."
MISSING_SCOPE = ("EVE refused part of this character's data. Log in with this character again and grant "
                 "the permissions AstraCore asks for.")
FALLBACK = "Reading EVE's data failed for now. It has been logged; try again in a few minutes."


def is_outage(exc: BaseException) -> bool:
    """ESI (or a data source behind it) isn't answering: worth a retry later, nothing for the pilot to fix."""
    return isinstance(exc, (ESIUnavailable, httpx.TransportError)) or (
        isinstance(exc, ESIError) and (exc.status or 0) >= 500)


def explain(exc: BaseException) -> str:
    """One plain sentence about the failure and what to do next. Never the exception's own text."""
    if isinstance(exc, sso.Transferred):
        return TRANSFERRED
    if isinstance(exc, sso.NeedsLogin):
        return NEEDS_LOGIN
    if isinstance(exc, ESIUnavailable):
        return _KIND.get(exc.kind, _KIND["unreachable"])
    if isinstance(exc, ESIError):
        if exc.status in (401, 403):
            return MISSING_SCOPE
        if (exc.status or 0) >= 500:
            return _KIND["server"]
        return FALLBACK
    if isinstance(exc, sso.SSOError):
        return "EVE's login server didn't answer as expected. Try again in a few minutes."
    if isinstance(exc, httpx.TimeoutException):
        return _KIND["timeout"]
    if isinstance(exc, httpx.HTTPError):
        return "A data source AstraCore reads (EVE's API or a public data file) didn't answer. " \
               "Try again in a few minutes."
    return FALLBACK


class Outage:
    """Collects what couldn't be refreshed while a page was built, and when its data was last fresh."""

    def __init__(self) -> None:
        self.error: Optional[BaseException] = None
        self.ats: list = []

    def note(self, exc: Optional[BaseException] = None, at: Optional[float] = None) -> None:
        if self.error is None:
            self.error = exc or ESIUnavailable("ESI is down", BUDGET.down_kind or "unreachable")
        if at:
            self.ats.append(float(at))

    def __bool__(self) -> bool:
        return self.error is not None

    def banner(self, fallback_at: Iterable[Optional[float]] = ()) -> Optional[dict]:
        """For the shared ESI banner (`esi_outage` in base.html): None when everything was fresh.
        `at` = the oldest data the page shows (noted, else e.g. the characters' last refresh)."""
        if self.error is None:
            return None
        ats = self.ats or [float(a) for a in fallback_at if a]
        return {"headline": HEADLINE, "detail": explain(self.error), "at": min(ats) if ats else None}


def recent_banner(fallback_at: Iterable[Optional[float]] = ()) -> Optional[dict]:
    """The banner for pages that only read stored data (the dashboard): shown while the latest ESI
    request anywhere in AstraCore failed and nothing has succeeded since."""
    kind = BUDGET.outage()
    if not kind:
        return None
    out = Outage()
    out.note(ESIUnavailable("ESI is down", kind))
    return out.banner(fallback_at)

