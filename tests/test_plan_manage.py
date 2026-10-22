"""Advanced saves its applied plan like the guided result; saved plans can be deleted, never the active one."""
from __future__ import annotations

import copy

from astracore.modules.pi import store
from astracore.modules.pi.settings import Settings
from test_plan_save import plan_client, suggest, save  # noqa: F401
from test_core import browser, csrf, eve, me, new_id, sso_login  # noqa: F401
from test_help import _guide_context
from test_planner import pi  # noqa: F401 (fixture)


def post(client, endpoint, **body):
    return client.post("/pi/api/" + endpoint, json=body, headers={"X-CSRF-Token": csrf(client)})


def delete(client, run_id, token=None):
    return client.post(f"/pi/plans/{run_id}/delete", follow_redirects=False,
                       data={"csrf_token": csrf(client) if token is None else token})


def test_advanced_apply_saves_the_applied_plan_and_makes_it_active(plan_client):
    client, pid, _, source, _ = plan_client
    first = save(client, suggest(client)["result_id"], active=True).json()
    preview = post(client, "preview", settings={"effort": 100}).json()
    applied = post(client, "apply", baseline=preview["baseline"], settings={"effort": 100}).json()
    shown = copy.deepcopy(applied)
    for key in ("result_id", "preview", "baseline"):
        shown.pop(key)
    source["totals"]["isk_per_day"] = 1   # a fresh solve would differ: the save must not solve again
    response = save(client, applied["result_id"], label="Advanced", active=True)
    assert response.status_code == 200 and response.json()["active"]
    active = store.active_plan(pid)
    assert active["id"] == response.json()["id"] != first["id"] and active["label"] == "Advanced"
    assert active["result"] == shown and active["settings"]["effort"] == 100


def test_advanced_preview_cannot_be_saved(plan_client):
    client, pid, _, _, _ = plan_client
    preview = post(client, "preview", settings={"effort": 100}).json()
    assert "result_id" not in preview
    assert save(client, preview.get("result_id")).status_code == 409
    assert not store.list_plan_runs(pid)


def test_advanced_page_offers_saving_and_explains_operate(plan_client, monkeypatch):
    client, _, _, _, _ = plan_client
    _guide_context(monkeypatch)
    html = client.get("/pi/plan?view=advanced").text
    assert 'id="planbar"' in html and "const PLANS = " in html
    assert "when built" not in html and "Operate tracks your saved active plan" in html


def test_delete_removes_an_inactive_plan_but_never_the_active_one(plan_client):
    client, pid, _, _, _ = plan_client
    active = store.save_plan_run(pid, "Active", Settings(), {"totals": {}}, active=True)
    spare = store.save_plan_run(pid, "Spare", Settings(), {"totals": {}})
    refused = delete(client, active)
    assert refused.status_code == 303 and "/pi/operate" in refused.headers["location"]
    assert store.get_plan_run(pid, active)
    assert not store.delete_plan_run(pid, active)
    done = delete(client, spare)
    assert done.status_code == 303 and "Deleted" in done.headers["location"]
    assert store.get_plan_run(pid, spare) is None
    assert [p["id"] for p in store.list_plan_runs(pid)] == [active]


def test_delete_needs_csrf_and_the_owning_profile(plan_client, browser, eve):
    client, pid, _, _, _ = plan_client
    spare = store.save_plan_run(pid, "Spare", Settings(), {"totals": {}})
    assert delete(client, spare, token="forged").status_code in (400, 403)
    other = browser()
    sso_login(other, eve, new_id(), "Other Delete Pilot")
    assert "Unknown" in delete(other, spare).headers["location"]
    assert store.get_plan_run(pid, spare)


def test_operate_lists_delete_forms_and_explains_the_limit(plan_client, monkeypatch, pi):  # noqa: F811
    from astracore.modules.pi import service
    client, pid, _, _, _ = plan_client

    async def context(profile_id, *a, **kw):
        return {"chars": service.planning_characters(profile_id), "pi": pi, "s": Settings(), "books": {},
                "area": None, "tpl": []}

    monkeypatch.setattr(service, "planning_context", context)
    store.save_plan_run(pid, "Active", Settings(), {"totals": {}}, active=True)
    spare = store.save_plan_run(pid, "Spare", Settings(), {"totals": {}})
    html = client.get("/pi/operate").text
    assert html.count('/delete"') == 1 and f'action="/pi/plans/{spare}/delete"' in html
    assert "data-confirm=\"Delete the saved plan Spare?" in html
    assert f"keeps your newest {store.MAX_PLANS} saved plans" in html


def test_trimming_keeps_max_plans_in_all_with_the_active_one(plan_client):
    _, pid, _, _, _ = plan_client
    active = store.save_plan_run(pid, "Active", Settings(), {"totals": {}}, active=True)
    for n in range(store.MAX_PLANS + 3):
        store.save_plan_run(pid, f"Plan {n}", Settings(), {"totals": {}})
    plans = store.list_plan_runs(pid, limit=1000)
    assert len(plans) == store.MAX_PLANS and plans[0]["id"] == active and plans[0]["active"]
    assert plans[-1]["label"] == "Plan 4"
