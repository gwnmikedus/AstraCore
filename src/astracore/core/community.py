"""Public roadmap and consented feedback, backed by GitHub issues.

Private ownership and delivery state stay in SQLite. GitHub is authoritative for public
issue status. A timed-out create is reconciled before any administrator can retry it.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Optional

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request

from astracore import config, db
from . import sessions
from .web import redirect, render

router = APIRouter()
log = logging.getLogger("astracore.community")
SCHEMA = """
CREATE TABLE IF NOT EXISTS community_feedback (
    id TEXT PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    submission_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('bug', 'idea')),
    title TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    delivery TEXT NOT NULL DEFAULT 'queued', issue_number INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0,
    lease_until REAL NOT NULL DEFAULT 0, problem TEXT NOT NULL DEFAULT '',
    UNIQUE(profile_id, submission_key)
);
CREATE INDEX IF NOT EXISTS community_delivery ON community_feedback(delivery, next_attempt_at);
CREATE TABLE IF NOT EXISTS community_issues (
    number INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
    state TEXT NOT NULL, state_reason TEXT, labels_json TEXT NOT NULL,
    roadmap_slug TEXT, updated_at TEXT NOT NULL, cached_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS community_webhooks (
    delivery_id TEXT PRIMARY KEY, received_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS community_sync (
    id INTEGER PRIMARY KEY CHECK(id=1), last_success REAL NOT NULL DEFAULT 0,
    next_poll_at REAL NOT NULL DEFAULT 0, problem TEXT NOT NULL DEFAULT ''
);
INSERT OR IGNORE INTO community_sync(id) VALUES(1);
"""

ROADMAP_VERSION = 1
ROADMAP = (
    {"slug": "reliable-market-advice", "area": "PI", "title": "PI recommendations that account for real market demand",
     "summary": "Compare prices with available buyers and historical trading, and distinguish estimated value from sale proceeds.",
     "basis": "Requested by the creator and confirmed by the PI planner audit.",
     "details": "Use full buy-order depth, market-history coverage, conservative sell-order scenarios and one consistent calculation of taxes and hauling. Show data freshness and uncertainty."},
    {"slug": "complete-first-build", "area": "PI", "title": "A complete shopping and construction checklist",
     "summary": "Know which command centers to buy, where to collect them, and what each character needs to build.",
     "basis": "Requested by the creator during the first-build review.",
     "details": "Copy a Multibuy list from the saved plan; separate purchased items from planetary construction and upgrades. Include template compatibility, startup costs and initial factory supplies."},
    {"slug": "practical-upkeep", "area": "PI", "title": "A restock and collection schedule that fits each colony",
     "summary": "Plan factory restocks, extractor restarts and collections around real storage limits.",
     "basis": "Storage and scheduling problems confirmed by the PI planner audit.",
     "details": "Keep extractor cadence separate from factory visits and market shipments. Validate launchpad capacity and show actual-versus-planned output, input shortages and data freshness. Optional reminders are a later extension."},
    {"slug": "clearer-plan-comparison", "area": "PI", "title": "Clear comparisons and easy plan editing",
     "summary": "Compare income and effort clearly, revisit earlier choices, and use the planner comfortably on mobile.",
     "basis": "Tour findings and firsthand feedback about other community PI tools; not an AstraCore vote count.",
     "details": "Preserve answered choices, support direct navigation to completed steps, fix time formatting and offer readable comparison tables. Validate actual multi-character and multi-system examples rather than only theoretical totals."},
    # Directions without an issue sit under Exploring; a linked `roadmap` issue moves them by its status.
    {"slug": "upkeep-reminders", "area": "PI", "title": "Reminders when a colony needs you",
     "summary": "Optional notices when an extractor stops or a colony's storage is about to fill.",
     "basis": "Named as a later extension of the upkeep schedule.",
     "details": "Reminders would stay opt-in. Tell us which moments are worth a notice and where you'd like to receive it."},
    {"slug": "fittings", "area": "Fittings", "title": "Fittings across your alts",
     "summary": "The right ship on the right character, with a shared preparation routine.",
     "basis": "A community direction, not yet scoped.",
     "details": "Describe the fitting problem across your characters you'd most like AstraCore to solve."},
    {"slug": "fleet-preparation", "area": "Fleet", "title": "Ready for the next fleet",
     "summary": "PvP and fleet preparation across your characters.",
     "basis": "A community direction, not yet scoped.",
     "details": "Bring the preparation step that costs you the most time before a fleet."},
    {"slug": "more-modules", "area": "Your operation", "title": "More of your operation in one place",
     "summary": "Logistics, industry, markets, skills and intel could follow.",
     "basis": "Ideas to explore together, with no promised availability.",
     "details": "Suggest the part of your operation you'd like to see next."},
)
RESEARCH_URL = "https://www.reddit.com/r/Eve/comments/1w5vnhx/the_new_and_improved_solution_to_your_pi_problems/"
FIELDS = ("kind", "title", "description", "steps", "expected", "actual")
_sync_lock = asyncio.Lock()
_token_cache = {}


def repository() -> str:
    value = config.env("ASTRACORE_GITHUB_REPOSITORY", "gwnmikedus/AstraCore")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise GitHubError("The repository configuration needs attention.")
    return value


def repository_url() -> str:
    return f"https://github.com/{repository()}"


def configured() -> bool:
    return bool(config.env("ASTRACORE_GITHUB_TOKEN") or (
        config.env("ASTRACORE_GITHUB_APP_ID") and config.env("ASTRACORE_GITHUB_INSTALLATION_ID")
        and config.env("ASTRACORE_GITHUB_PRIVATE_KEY_PATH")))


def current_version() -> str:
    from .releases import current
    return str(current()["version"])


class GitHubError(Exception):
    """A safe, user-facing failure; never contains request credentials or API bodies."""


class AmbiguousCreate(GitHubError):
    pass


async def access_token(client: httpx.AsyncClient) -> str:
    app_id = config.env("ASTRACORE_GITHUB_APP_ID")
    installation_id = config.env("ASTRACORE_GITHUB_INSTALLATION_ID")
    key_path = config.env("ASTRACORE_GITHUB_PRIVATE_KEY_PATH")
    if app_id and installation_id and key_path:
        cache_key = (app_id, installation_id, key_path)
        if _token_cache.get("key") == cache_key and _token_cache.get("expires", 0) > time.time():
            return _token_cache["token"]
        if not installation_id.isdigit():
            raise GitHubError("The GitHub installation configuration needs attention.")
        try:
            private_key = Path(key_path).expanduser().read_text()
            now = int(time.time())
            signed = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256")
            response = await client.post(f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                                         headers={"Authorization": f"Bearer {signed}"},
                                         json={"repositories": [repository().split("/")[1]],
                                               "permissions": {"issues": "write"}})
            response.raise_for_status()
            token = response.json()["token"]
        except (OSError, jwt.PyJWTError, httpx.HTTPError, ValueError, KeyError):
            raise GitHubError("GitHub authorization is unavailable. An administrator can check the connection.") from None
        _token_cache.update(key=cache_key, token=token, expires=time.time() + 3000)
        return token
    token = config.env("ASTRACORE_GITHUB_TOKEN")
    if not token:
        raise GitHubError("GitHub is not connected yet. Your report is saved here until it is connected.")
    return token


async def github_request(client: httpx.AsyncClient, method: str, path: str, *, payload: Optional[dict] = None,
                         params: Optional[dict] = None) -> httpx.Response:
    headers = {}
    if configured() or method != "GET":
        token = await access_token(client)
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = await client.request(method, f"https://api.github.com{path}", json=payload, params=params,
                                        headers=headers)
    except httpx.HTTPError:
        if method == "POST":
            raise AmbiguousCreate("GitHub may have received this report. Checking before another delivery.") from None
        raise GitHubError("GitHub could not be reached. Your saved report will be retried.") from None
    if response.status_code >= 500 and method == "POST":
        raise AmbiguousCreate("GitHub may have received this report. Checking before another delivery.")
    if not 200 <= response.status_code < 300:
        if response.status_code in (403, 429):
            raise GitHubError("GitHub is limiting requests or the connection needs permission. Your report is saved.")
        raise GitHubError("GitHub did not accept the request. An administrator can retry after checking the connection.")
    return response


def marker(feedback_id: str) -> str:
    return f"<!-- astracore-feedback:{feedback_id} -->"


def _roadmap_slug(body: str) -> Optional[str]:
    found = re.search(r"<!-- astracore-roadmap:([a-z0-9-]+) -->", body)
    return found.group(1) if found else None


def cache_issue(issue: dict) -> None:
    if not isinstance(issue, dict) or issue.get("pull_request") or not isinstance(issue.get("number"), int):
        return
    raw_labels = issue.get("labels")
    labels = [x["name"] for x in raw_labels if isinstance(x, dict) and isinstance(x.get("name"), str)] if isinstance(raw_labels, list) else []
    body = str(issue.get("body") or "")
    state = "closed" if issue.get("state") == "closed" else "open"
    with db.session() as c:
        existing = c.execute("SELECT updated_at FROM community_issues WHERE number=?", (issue["number"],)).fetchone()
        updated_at = str(issue.get("updated_at") or "")
        if existing and existing["updated_at"] > updated_at:
            return
        c.execute("INSERT INTO community_issues(number,title,body,state,state_reason,labels_json,roadmap_slug,updated_at,cached_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(number) DO UPDATE SET title=excluded.title,body=excluded.body,"
                  "state=excluded.state,state_reason=excluded.state_reason,labels_json=excluded.labels_json,"
                  "roadmap_slug=excluded.roadmap_slug,updated_at=excluded.updated_at,cached_at=excluded.cached_at",
                  (issue["number"], str(issue.get("title") or "Untitled issue"), body, state,
                   issue.get("state_reason"), json.dumps(labels),
                   _roadmap_slug(body) if "roadmap" in labels and "source:platform" not in labels else None,
                   updated_at, time.time()))
        found = re.search(r"<!-- astracore-feedback:([a-f0-9]{32}) -->", body)
        if found:
            c.execute("UPDATE community_feedback SET delivery='published',issue_number=?,updated_at=?,problem='',lease_until=0 "
                      "WHERE id=? AND delivery != 'withdrawn' AND (issue_number IS NULL OR issue_number=?)",
                      (issue["number"], time.time(), found.group(1), issue["number"]))


def issue_status(issue: dict) -> str:
    labels = issue.get("labels", [])
    if "status:released" in labels:
        return "Released"
    if issue["state"] == "closed":
        return "Completed" if issue.get("state_reason") == "completed" else "Closed"
    if "status:in-progress" in labels:
        return "In progress"
    if "status:planned" in labels or "roadmap" in labels:
        return "Planned"
    return "Under review"


def _issue_row(row) -> dict:
    value = dict(row)
    value["labels"] = json.loads(value.pop("labels_json"))
    value["url"] = f"{repository_url()}/issues/{value['number']}"
    value["status"] = issue_status(value)
    return value


def public_issues() -> list:
    with db.session() as c:
        rows = c.execute("SELECT * FROM community_issues ORDER BY number DESC").fetchall()
    return [_issue_row(r) for r in rows if "platform:hidden" not in json.loads(r["labels_json"])]


def feedback_for(profile_id: int, *, all_profiles: bool = False) -> list:
    with db.session() as c:
        if all_profiles:
            rows = c.execute("SELECT * FROM community_feedback ORDER BY created_at DESC LIMIT 100").fetchall()
        else:
            rows = c.execute("SELECT * FROM community_feedback WHERE profile_id=? ORDER BY created_at DESC LIMIT 100",
                             (profile_id,)).fetchall()
    return [dict(r) for r in rows]


def validate_fields(form) -> dict:
    data = {field: str(form.get(field) or "").strip() for field in FIELDS}
    if data["kind"] not in ("bug", "idea"):
        raise ValueError("Choose a bug report or an idea.")
    if not 8 <= len(data["title"]) <= 160:
        raise ValueError("Use a title between 8 and 160 characters.")
    if not 20 <= len(data["description"]) <= 6000:
        raise ValueError("Describe the problem or idea in 20 to 6,000 characters.")
    for field in ("steps", "expected", "actual"):
        if len(data[field]) > 3000:
            raise ValueError("Keep each detail field below 3,000 characters.")
    if data["kind"] == "bug" and not all(data[field] for field in ("steps", "expected", "actual")):
        raise ValueError("A bug report needs steps to reproduce, the expected result and what actually happened.")
    if any("\x00" in value for value in data.values()):
        raise ValueError("Remove invalid characters before continuing.")
    if any(re.search(r"<!--\s*astracore-(?:feedback|roadmap):", value, re.I) for value in data.values()):
        raise ValueError("Remove internal AstraCore tracking markers from your report text.")
    return data


def public_body(data: dict, version: str) -> str:
    sections = ["Submitted through AstraCore. No character identity or private EVE data was automatically included.",
                f"App version: {version}", "## Problem or idea\n\n" + data["description"]]
    if data["kind"] == "bug":
        sections += ["## Steps to reproduce\n\n" + data["steps"], "## Expected result\n\n" + data["expected"],
                     "## Actual result\n\n" + data["actual"]]
    return "\n\n".join(sections)


def preview_signature(data: dict, version: str, nonce: str, timestamp: int, profile_id: int) -> str:
    payload = json.dumps([data, version, nonce, timestamp, profile_id], sort_keys=True, separators=(",", ":"))
    return hmac.new(config.session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_preview(form, data: dict, profile_id: int) -> tuple:
    nonce, version = str(form.get("submission_key") or ""), str(form.get("version") or "")
    try:
        timestamp = int(form.get("preview_at") or 0)
    except (ValueError, TypeError):
        timestamp = 0
    signature = str(form.get("preview_signature") or "")
    if (not re.fullmatch(r"[a-f0-9]{32}", nonce) or not version or len(version) > 80
            or not 0 <= time.time() - timestamp <= 3600
            or not hmac.compare_digest(signature, preview_signature(data, version, nonce, timestamp, profile_id))):
        raise ValueError("The preview expired or changed. Preview your report again before publishing.")
    if form.get("public_confirm") != "yes":
        raise ValueError("Confirm that you want the previewed content published publicly.")
    return nonce, version


def save_feedback(profile_id: int, data: dict, nonce: str, version: str) -> str:
    now = time.time()
    with db.session() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute("SELECT id FROM community_feedback WHERE profile_id=? AND submission_key=?",
                             (profile_id, nonce)).fetchone()
        if existing:
            return existing["id"]
        count = c.execute("SELECT COUNT(*) FROM community_feedback WHERE profile_id=? AND created_at>?",
                          (profile_id, now - 3600)).fetchone()[0]
        if count >= 5:
            raise ValueError("You have submitted five reports in the last hour. Please try again later.")
        feedback_id = secrets.token_hex(16)
        c.execute("INSERT INTO community_feedback(id,profile_id,submission_key,kind,title,body,version,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?)", (feedback_id, profile_id, nonce, data["kind"], data["title"],
                                                public_body(data, version), version, now, now))
    return feedback_id


async def find_published(client: httpx.AsyncClient, row: dict) -> Optional[dict]:
    # Stop only after covering the report's creation time. A bounded incomplete read
    # never authorizes another create, so very busy repositories fail safely.
    for page in range(1, 21):
        response = await github_request(client, "GET", f"/repos/{repository()}/issues", params={
            "state": "all", "sort": "created", "direction": "desc", "per_page": 100, "page": page})
        issues = response.json()
        if not isinstance(issues, list):
            raise GitHubError("GitHub returned an unexpected response. No duplicate report was sent.")
        for issue in issues:
            if not isinstance(issue, dict):
                raise GitHubError("GitHub returned an unexpected issue. No duplicate report was sent.")
            if marker(row["id"]) in str(issue.get("body") or ""):
                return issue
        if len(issues) < 100:
            return None
        from datetime import datetime
        try:
            oldest = datetime.fromisoformat(issues[-1]["created_at"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError, TypeError):
            continue
        if oldest < row["created_at"] - 60:
            return None
    raise GitHubError("The delivery check could not cover all recent issues. An administrator can review it.")


def delivery_problem(feedback_id: str, problem: str, *, ambiguous: bool = False) -> None:
    with db.session() as c:
        row = c.execute("SELECT attempts,delivery FROM community_feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row or row["delivery"] == "withdrawn":
            return
        delay = min(3600, 60 * 2 ** min(6, row["attempts"]))
        c.execute("UPDATE community_feedback SET delivery=?,problem=?,next_attempt_at=?,lease_until=0,updated_at=? WHERE id=?",
                  ("ambiguous" if ambiguous or row["delivery"] == "ambiguous" else "queued", problem,
                   time.time() + delay, time.time(), feedback_id))


async def deliver(client: httpx.AsyncClient, row: dict) -> None:
    was_ambiguous = row["delivery"] == "ambiguous"
    if not configured() and not was_ambiguous:
        delivery_problem(row["id"], "GitHub is not connected yet. Your report is saved here until it is connected.")
        return
    try:
        found = await find_published(client, row)
        if found:
            cache_issue(found)
            return
        if was_ambiguous:
            delivery_problem(row["id"], "Delivery is unconfirmed. No matching GitHub issue was found; an administrator must review before retrying.", ambiguous=True)
            return
        with db.session() as c:
            current = c.execute("SELECT delivery FROM community_feedback WHERE id=?", (row["id"],)).fetchone()
        if not current or current["delivery"] != "processing":
            return
        response = await github_request(client, "POST", f"/repos/{repository()}/issues", payload={
            "title": row["title"], "body": row["body"] + "\n\n" + marker(row["id"]),
            "labels": [f"type:{row['kind']}", "status:under-review", "source:platform"]})
        try:
            issue = response.json()
            if not isinstance(issue.get("number"), int):
                raise ValueError
        except (ValueError, AttributeError):
            raise AmbiguousCreate("GitHub returned an incomplete confirmation. Checking before another delivery.") from None
        cache_issue(issue)
    except AmbiguousCreate as exc:
        delivery_problem(row["id"], str(exc), ambiguous=True)
    except (GitHubError, ValueError) as exc:
        problem = str(exc) if isinstance(exc, GitHubError) else "GitHub returned unreadable data. Your report remains saved."
        delivery_problem(row["id"], problem, ambiguous=was_ambiguous)


async def poll_issues(client: httpx.AsyncClient) -> None:
    # A full snapshot also removes deleted/transferred issues from the projection.
    numbers = []
    for page in range(1, 101):
        response = await github_request(client, "GET", f"/repos/{repository()}/issues",
                                        params={"state": "all", "per_page": 100, "page": page})
        batch = response.json()
        if not isinstance(batch, list):
            raise GitHubError("GitHub returned an unexpected issue listing.")
        for issue in batch:
            if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
                raise GitHubError("GitHub returned an incomplete issue listing.")
            if not issue.get("pull_request"):
                cache_issue(issue)
                numbers.append(issue["number"])
        if len(batch) < 100:
            break
    else:
        raise GitHubError("The issue listing was incomplete. Existing cached issues were preserved.")
    with db.session() as c:
        for row in c.execute("SELECT number FROM community_issues").fetchall():
            if row["number"] not in numbers:
                c.execute("DELETE FROM community_issues WHERE number=?", (row["number"],))
        c.execute("UPDATE community_sync SET last_success=?,problem='' WHERE id=1", (time.time(),))


async def sync_once(*, force: bool = False, transport=None) -> None:
    if _sync_lock.locked():
        return
    async with _sync_lock:
        now = time.time()
        with db.session() as c:
            c.execute("UPDATE community_feedback SET delivery='ambiguous',lease_until=0,next_attempt_at=0 "
                      "WHERE delivery='processing' AND lease_until<?", (now,))
            due = c.execute("SELECT * FROM community_feedback WHERE delivery IN ('queued','ambiguous') "
                            "AND next_attempt_at<=? ORDER BY created_at LIMIT 10", (now,)).fetchall()
            sync = c.execute("SELECT * FROM community_sync WHERE id=1").fetchone()
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10",
                   "User-Agent": "AstraCore community integration"}
        async with httpx.AsyncClient(timeout=15, headers=headers, transport=transport) as client:
            for saved in due:
                row = dict(saved)
                with db.session() as c:
                    claim = c.execute("UPDATE community_feedback SET delivery='processing',lease_until=?,attempts=attempts+1 "
                                      "WHERE id=? AND delivery IN ('queued','ambiguous') AND next_attempt_at<=?",
                                      (time.time() + 300, row["id"], now))
                    claimed = claim.rowcount == 1
                if claimed:
                    await deliver(client, row)
            if sync and (force or sync["next_poll_at"] <= now):
                try:
                    interval = max(60, int(config.env("ASTRACORE_COMMUNITY_POLL_SECONDS", "300")))
                except ValueError:
                    interval = 300
                # Unauthenticated public API reads share a 60-request/hour IP quota.
                # One page every five minutes uses 12 requests/hour; each extra page counts.
                if not configured():
                    interval = max(300, interval)
                with db.session() as c:
                    c.execute("UPDATE community_sync SET next_poll_at=? WHERE id=1", (now + interval,))
                try:
                    await poll_issues(client)
                except (GitHubError, ValueError, KeyError):
                    with db.session() as c:
                        c.execute("UPDATE community_sync SET problem=? WHERE id=1",
                                  ("GitHub updates are temporarily unavailable. Showing the last confirmed information.",))


async def run_sync_loop() -> None:
    from . import contributors

    while True:
        try:
            await sync_once()
        except Exception:  # noqa: BLE001 - keep the delivery worker alive after an unexpected failure
            # Log only the failure category, never exception bodies or private report text.
            log.warning("Community synchronization failed; queued reports will be checked again.")
        try:
            await contributors.sync_once()
        except Exception:  # noqa: BLE001 - contributor credits must not stop report delivery
            log.warning("Contributor synchronization failed; cached credits remain available.")
        await asyncio.sleep(30)


def sync_state() -> dict:
    with db.session() as c:
        row = c.execute("SELECT * FROM community_sync WHERE id=1").fetchone()
    return dict(row) if row else {"last_success": 0, "problem": "GitHub has not been connected yet."}


def _lane(status: str) -> str:
    return {"In progress": "now", "Completed": "now", "Planned": "next",
            "Released": "released", "Closed": "closed"}.get(status, "review")


def roadmap_board(issues: list) -> dict:
    """Group curated directions and labelled issues into Now / Next / Exploring, plus released work.

    A curated item follows its linked roadmap issue; without one it is still being explored.
    Issues under review stay in the issue list instead of the board: they aren't decided yet.
    """
    by_slug = {i["roadmap_slug"]: i for i in issues if i["roadmap_slug"]}
    board = {"now": [], "next": [], "exploring": [], "released": [], "closed": []}
    linked = set()
    for item in ROADMAP:
        issue = by_slug.get(item["slug"])
        lane = _lane(issue["status"]) if issue else "exploring"
        if issue:
            linked.add(issue["number"])
        board["next" if lane == "review" else lane].append({**item, "issue": issue})
    for issue in issues:
        lane = _lane(issue["status"])
        if issue["number"] not in linked and lane != "review":
            board[lane].append({"title": issue["title"], "issue": issue,
                                "area": "Bug fix" if "type:bug" in issue["labels"] else "Improvement"})
    board["open"] = [i for i in issues if i["state"] == "open"]
    board["under_review"] = sum(1 for i in board["open"] if i["status"] == "Under review")
    return board


@router.get("/roadmap")
@router.get("/community")
async def roadmap_page(request: Request):
    user = request.state.user
    mine = feedback_for(user["id"]) if user else []
    return render(request, "community.html", page="community", page_title="Roadmap & feedback",
                  board=roadmap_board(public_issues()), mine=mine, sync=sync_state(), github_url=repository_url(),
                  research_url=RESEARCH_URL)


def _feedback_context(request: Request, data: Optional[dict] = None, error: str = "") -> dict:
    return dict(page="feedback", page_title="Share an idea or report a bug", data=data or {}, error=error,
                github_url=repository_url(), connected=configured(), feedback_login_url="/auth/community")


@router.get("/feedback")
@router.get("/community/report")
async def feedback_page(request: Request, kind: str = "idea"):
    return render(request, "feedback.html", **_feedback_context(request, {"kind": "bug" if kind == "bug" else "idea"}))


@router.post("/feedback/preview")
async def feedback_preview(request: Request):
    user = sessions.require_user(request)
    form = await request.form()
    try:
        data = validate_fields(form)
    except ValueError as exc:
        return render(request, "feedback.html", status_code=400,
                      **_feedback_context(request, {f: str(form.get(f) or "") for f in FIELDS}, str(exc)))
    version, nonce, timestamp = current_version(), secrets.token_hex(16), int(time.time())
    signature = preview_signature(data, version, nonce, timestamp, user["id"])
    return render(request, "feedback_preview.html", page="feedback", page_title="Preview your public report", data=data,
                  body=public_body(data, version), version=version, submission_key=nonce, preview_at=timestamp,
                  preview_signature=signature, github_url=repository_url(), connected=configured(), error="")


@router.post("/feedback/edit")
async def feedback_edit(request: Request):
    sessions.require_user(request)
    form = await request.form()
    return render(request, "feedback.html", **_feedback_context(request, {f: str(form.get(f) or "") for f in FIELDS}))


@router.post("/feedback")
async def feedback_submit(request: Request):
    user = sessions.require_user(request)
    form = await request.form()
    try:
        data = validate_fields(form)
        nonce, version = verify_preview(form, data, user["id"])
        feedback_id = save_feedback(user["id"], data, nonce, version)
    except ValueError as exc:
        return render(request, "feedback.html", status_code=400,
                      **_feedback_context(request, {f: str(form.get(f) or "") for f in FIELDS}, str(exc)))
    return redirect(f"/community/reports/{feedback_id}", "Your report is saved. It will appear publicly once GitHub confirms delivery.", "ok")


@router.get("/community/reports/{feedback_id}")
async def feedback_detail(request: Request, feedback_id: str):
    user = sessions.require_user(request)
    with db.session() as c:
        row = c.execute("SELECT * FROM community_feedback WHERE id=?", (feedback_id,)).fetchone()
    if not row or (row["profile_id"] != user["id"] and not user.get("is_admin")):
        raise HTTPException(status_code=404, detail="Report not found.")
    with db.session() as c:
        issue = c.execute("SELECT * FROM community_issues WHERE number=?", (row["issue_number"],)).fetchone()
    return render(request, "feedback_detail.html", page="feedback", page_title="Your report", report=dict(row),
                  issue=_issue_row(issue) if issue else None, github_url=repository_url())


@router.post("/community/reports/{feedback_id}/withdraw")
async def feedback_withdraw(request: Request, feedback_id: str):
    user = sessions.require_user(request)
    with db.session() as c:
        row = c.execute("SELECT profile_id,delivery FROM community_feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row or (row["profile_id"] != user["id"] and not user.get("is_admin")):
            raise HTTPException(status_code=404, detail="Report not found.")
        withdrawn = c.execute("UPDATE community_feedback SET delivery='withdrawn',updated_at=? "
                              "WHERE id=? AND delivery='queued'", (time.time(), feedback_id))
        if withdrawn.rowcount != 1:
            return redirect(f"/community/reports/{feedback_id}", "This report is already published or its delivery is being checked. Contact the maintainer for removal.", "warn")
    return redirect(f"/community/reports/{feedback_id}", "Report withdrawn before publication.", "ok")


def require_admin(request: Request) -> dict:
    user = sessions.require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


@router.get("/community/admin")
async def community_admin(request: Request):
    user = require_admin(request)
    return render(request, "feedback_admin.html", page="community", page_title="Community administration",
                  reports=feedback_for(user["id"], all_profiles=True), sync=sync_state(), connected=configured(),
                  github_url=repository_url())


@router.post("/community/admin/sync")
async def community_sync(request: Request):
    require_admin(request)
    await sync_once(force=True)
    return redirect("/community/admin", "GitHub synchronization checked. Review the delivery status below.")


@router.post("/community/admin/{feedback_id}/retry")
async def community_retry(request: Request, feedback_id: str):
    require_admin(request)
    form = await request.form()
    with db.session() as c:
        row = c.execute("SELECT * FROM community_feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Report not found.")
        if row["delivery"] == "ambiguous" and form.get("checked_missing") != "yes":
            return redirect("/community/admin", "Check that no matching issue exists before retrying an unconfirmed delivery.", "warn")
        if row["delivery"] not in ("queued", "ambiguous"):
            return redirect("/community/admin", "This report is not waiting for a retry.", "warn")
        retried = c.execute("UPDATE community_feedback SET delivery='queued',next_attempt_at=0,problem='',updated_at=? "
                            "WHERE id=? AND delivery=?", (time.time(), feedback_id, row["delivery"]))
        if retried.rowcount != 1:
            return redirect("/community/admin", "Delivery changed while this report was being checked. Refresh before retrying.", "warn")
    await sync_once()
    return redirect("/community/admin", "Delivery checked and retried where safe.")


@router.post("/community/admin/issues/{issue_number}/visibility")
async def community_visibility(request: Request, issue_number: int):
    require_admin(request)
    form = await request.form()
    hidden = form.get("hidden") == "yes"
    with db.session() as c:
        row = c.execute("SELECT * FROM community_issues WHERE number=?", (issue_number,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Issue not found.")
    labels = json.loads(row["labels_json"])
    labels = [label for label in labels if label != "platform:hidden"]
    if hidden:
        labels.append("platform:hidden")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10",
               "User-Agent": "AstraCore community integration"}
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            response = await github_request(client, "PATCH", f"/repos/{repository()}/issues/{issue_number}", payload={"labels": labels})
        cache_issue(response.json())
    except (GitHubError, ValueError):
        return redirect("/community/admin", "GitHub did not confirm this visibility change. Try again later.", "warn")
    return redirect("/community/admin", "Platform visibility updated. The issue itself remains public on GitHub.")


@router.post("/api/community/github/webhook")
async def github_webhook(request: Request):
    secret = config.env("ASTRACORE_GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook is not configured.")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 2_000_000:
            raise HTTPException(status_code=413, detail="Payload too large.")
        chunks.append(chunk)
    body = b"".join(chunks)
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("x-hub-signature-256", ""), expected):
        raise HTTPException(status_code=403, detail="Invalid webhook signature.")
    delivery_id = request.headers.get("x-github-delivery", "")
    if not delivery_id or len(delivery_id) > 100:
        raise HTTPException(status_code=400, detail="Missing delivery identifier.")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    event = request.headers.get("x-github-event", "")
    if event == "ping":
        return {"accepted": True, "ping": True}
    if not isinstance(payload.get("repository"), dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    repo_name = payload["repository"].get("full_name")
    if not isinstance(repo_name, str) or repo_name.lower() != repository().lower():
        raise HTTPException(status_code=403, detail="Unexpected repository.")
    with db.session() as c:
        if c.execute("SELECT 1 FROM community_webhooks WHERE delivery_id=?", (delivery_id,)).fetchone():
            return {"accepted": True, "duplicate": True}
    if event == "issues" and isinstance(payload.get("issue"), dict):
        if payload.get("action") in ("deleted", "transferred"):
            with db.session() as c:
                c.execute("DELETE FROM community_issues WHERE number=?", (payload["issue"].get("number"),))
        else:
            cache_issue(payload["issue"])
    elif event in ("issue_comment", "label"):
        with db.session() as c:
            c.execute("UPDATE community_sync SET next_poll_at=0 WHERE id=1")
    with db.session() as c:
        c.execute("INSERT OR IGNORE INTO community_webhooks(delivery_id,received_at) VALUES(?,?)", (delivery_id, time.time()))
        c.execute("DELETE FROM community_webhooks WHERE received_at<?", (time.time() - 30 * 86400,))
    return {"accepted": True}
