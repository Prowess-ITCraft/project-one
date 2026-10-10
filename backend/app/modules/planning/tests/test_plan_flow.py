"""From an accepted BOQ to a locked, scheduled plan with target configurations."""

from __future__ import annotations

from datetime import timedelta
from itertools import pairwise
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.core.timeutil import IST, today_ist, utcnow
from app.modules.boq.tests.test_boq_flow import Ctx, _approved, ready
from app.modules.identity.permissions import Role
from app.modules.planning.seed import seed_planning
from tests.helpers import drain_outbox, idem, make_user

API = "/api/v1"


class Plan:
    def __init__(self, c: Ctx, pm: Any, lead: Any, eng: list[Any]) -> None:
        self.c, self.pm, self.lead, self.eng = c, pm, lead, eng
        self.pid = c.pid
        self.base = f"{API}/projects/{c.pid}/plan"


async def accepted_boq(client: Any) -> Ctx:
    c = await ready(client)
    b = await _approved(client, c)
    await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    cur = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    chosen = {ln["option_group"]: "A" for ln in cur["lines"] if ln["option_group"]}
    r = await client.post(
        f"{API}/boq/{b['id']}/versions/1/accept",
        json={
            "po_number": "SHK/PO/2026/001",
            "po_date": str(today_ist()),
            "selected_options": chosen,
        },
        headers={**c.sm.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    return c


async def workspace(client: Any, engineers: int = 2) -> Plan:
    c = await accepted_boq(client)
    async with get_sessionmaker()() as s:
        await seed_planning(s)
    await get_redis().flushall()
    pm = await make_user(client, Role.PROJECT_MANAGER)
    await get_redis().flushall()
    lead = await make_user(client, Role.TECHNICAL_LEAD)
    eng = []
    for _ in range(engineers):
        await get_redis().flushall()
        eng.append(await make_user(client, Role.FIELD_ENGINEER))
    await get_redis().flushall()
    for u, role in [
        (pm, "project_manager"),
        (lead, "technical_lead"),
        *[(e, "field_engineer") for e in eng],
    ]:
        r = await client.put(
            f"{API}/projects/{c.pid}/members",
            json={"user_id": str(u.id), "project_role": role},
            headers=c.ws.head.headers,
        )
        assert r.status_code == 200, r.text
    return Plan(c, pm, lead, eng)


async def generate(client: Any, p: Plan) -> dict[str, Any]:
    r = await client.post(f"{p.base}/generate", json={}, headers=p.pm.headers)
    assert r.status_code == 201, r.text
    return dict(r.json())


async def add_window(client: Any, p: Plan, days: int = 30) -> None:
    start = (
        (utcnow() + timedelta(days=1))
        .astimezone(IST)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    r = await client.post(
        f"{p.base}/downtime",
        json={
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(days=days)).isoformat(),
            "note": "Nights and Sundays",
        },
        headers=p.pm.headers,
    )
    assert r.status_code == 201, r.text


async def schedule(client: Any, p: Plan, **body: Any) -> Any:
    return await client.post(
        f"{p.base}/schedule",
        json={"start_date": str(today_ist() + timedelta(days=1)), "auto_assign": True, **body},
        headers=p.pm.headers,
    )


# ------------------------------------------------------------------ generation


async def test_plan_needs_an_accepted_boq(client: Any) -> None:
    from tests.helpers import make_workspace

    ws = await make_workspace(client)
    pm = await make_user(client, Role.PROJECT_MANAGER)
    await client.put(
        f"{API}/projects/{ws.project_id}/members",
        json={"user_id": str(pm.id), "project_role": "project_manager"},
        headers=ws.head.headers,
    )
    r = await client.post(
        f"{API}/projects/{ws.project_id}/plan/generate", json={}, headers=pm.headers
    )
    assert r.status_code == 404
    got = await client.get(f"{API}/projects/{ws.project_id}/plan", headers=pm.headers)
    assert got.status_code == 200 and got.json() is None


async def test_generate_makes_tasks_dependencies_and_baselines(client: Any) -> None:
    p = await workspace(client)
    d = await generate(client, p)
    tasks = d["tasks"]
    assert tasks and d["plan"]["status"] == "draft" and d["plan"]["boq_quote_ref"]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        by_kind.setdefault(t["kind"], []).append(t)
    # the BOQ sanitizes every endpoint (ADR 0001): one task per system, each with its own evidence
    assert len(by_kind["sanitize"]) >= 6
    refs = {t["ref"] for t in tasks}
    assert all(set(t["depends_on"]) <= refs for t in tasks)
    eps = by_kind["eps-service"][0]
    assert {t["ref"] for t in by_kind["sanitize"]} <= set(eps["depends_on"])
    assert all(t["steps"] and t["evidence"] for t in tasks)
    assert all(t["start_at"] is None for t in tasks)
    kinds = {b["device_type"] for b in d["baselines"]}
    assert {"firewall", "switch", "endpoint"} <= kinds
    assert all(b["fields"] for b in d["baselines"])
    # a second generate is refused unless it replaces the draft
    again = await client.post(f"{p.base}/generate", json={}, headers=p.pm.headers)
    assert again.status_code == 409 and again.json()["code"] == "plan_exists"
    repl = await client.post(f"{p.base}/generate", json={"replace": True}, headers=p.pm.headers)
    assert repl.status_code == 201 and repl.json()["plan"]["number"] == 2


# ------------------------------------------------------------------ scheduling


async def test_schedule_needs_engineers_and_downtime_windows(client: Any) -> None:
    p = await workspace(client, engineers=0)
    await generate(client, p)
    r = await schedule(client, p)
    assert r.status_code == 409 and r.json()["code"] == "no_engineers"
    eng = await make_user(client, Role.FIELD_ENGINEER)
    await client.put(
        f"{API}/projects/{p.pid}/members",
        json={"user_id": str(eng.id), "project_role": "field_engineer"},
        headers=p.c.ws.head.headers,
    )
    r = await schedule(client, p)
    assert r.status_code == 409 and r.json()["code"] == "downtime_windows_missing"
    past = await schedule(client, p, start_date=str(today_ist() - timedelta(days=1)))
    assert past.status_code == 422


async def test_schedule_places_every_task_in_order_without_double_booking(client: Any) -> None:
    p = await workspace(client)
    await generate(client, p)
    await add_window(client, p)
    r = await schedule(client, p)
    assert r.status_code == 200, r.text
    d = r.json()
    tasks = {t["ref"]: t for t in d["tasks"]}
    assert all(t["start_at"] and t["assignee_id"] for t in tasks.values())
    for t in tasks.values():
        for dep in t["depends_on"]:
            assert tasks[dep]["end_at"] <= t["start_at"]
    by_eng: dict[str, list[dict[str, Any]]] = {}
    for t in tasks.values():
        by_eng.setdefault(t["assignee_id"], []).append(t)
    assert len(by_eng) == 2  # both engineers get work
    for lst in by_eng.values():
        lst.sort(key=lambda x: x["start_at"])
        for a, b in pairwise(lst):
            assert a["end_at"] <= b["start_at"]
    from datetime import datetime

    for t in tasks.values():
        if not t["requires_downtime"]:
            s = datetime.fromisoformat(t["start_at"]).astimezone(IST)
            assert s.weekday() != 6 and 10 <= s.hour < 18
    assert d["ends_at"] and d["total_minutes"] > 0


async def test_leave_pushes_an_engineers_work_later(client: Any) -> None:
    p = await workspace(client, engineers=1)
    await generate(client, p)
    await add_window(client, p, 60)
    first_day = today_ist() + timedelta(days=1)
    r = await client.post(
        f"{API}/planning/leaves",
        json={
            "user_id": str(p.eng[0].id),
            "date_from": str(first_day),
            "date_to": str(first_day + timedelta(days=2)),
            "reason": "Wedding",
        },
        headers=p.pm.headers,
    )
    assert r.status_code == 201, r.text
    lv = r.json()
    listed = await client.get(
        f"{API}/planning/leaves", params={"user_id": str(p.eng[0].id)}, headers=p.pm.headers
    )
    assert [x["id"] for x in listed.json()] == [lv["id"]]
    s = await schedule(client, p, start_date=str(first_day))
    assert s.status_code == 200, s.text
    from datetime import datetime

    earliest = min(
        datetime.fromisoformat(t["start_at"]).astimezone(IST).date()
        for t in s.json()["tasks"]
        if not t["requires_downtime"]
    )
    assert earliest > first_day + timedelta(days=2)
    bad = await client.post(
        f"{API}/planning/leaves",
        json={
            "user_id": str(p.eng[0].id),
            "date_from": str(first_day),
            "date_to": str(first_day - timedelta(days=1)),
        },
        headers=p.pm.headers,
    )
    assert bad.status_code == 422
    assert (
        await client.delete(f"{API}/planning/leaves/{lv['id']}", headers=p.pm.headers)
    ).status_code == 204
    assert (
        await client.delete(f"{API}/planning/leaves/{lv['id']}", headers=p.pm.headers)
    ).status_code == 404


# ------------------------------------------------------------------ editing


async def test_editing_tasks_validates_and_clears_the_schedule(client: Any) -> None:
    p = await workspace(client)
    d = await generate(client, p)
    await add_window(client, p)
    s = (await schedule(client, p)).json()
    t = next(x for x in s["tasks"] if x["kind"] == "eps-service")
    url = f"{p.base}/tasks/{t['id']}"
    # reason required
    assert (
        await client.patch(
            url, json={"version": t["version"], "minutes": 200}, headers=p.pm.headers
        )
    ).status_code == 422
    ok = await client.patch(
        url,
        json={"version": t["version"], "reason": "Customer has more machines", "minutes": 200},
        headers=p.pm.headers,
    )
    assert ok.status_code == 200 and ok.json()["minutes"] == 200 and ok.json()["start_at"] is None
    cur = (await client.get(p.base, headers=p.pm.headers)).json()
    assert all(x["start_at"] is None for x in cur["tasks"])  # needs scheduling again
    stale = await client.patch(
        url,
        json={"version": t["version"], "reason": "again please", "minutes": 210},
        headers=p.pm.headers,
    )
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    v = ok.json()["version"]
    # sanitization must come before the service that depends on it: making it wait for the
    # service would be a circle
    san = next(x for x in d["tasks"] if x["kind"] == "sanitize")
    san_now = next(
        x
        for x in (await client.get(p.base, headers=p.pm.headers)).json()["tasks"]
        if x["id"] == san["id"]
    )
    loop = await client.patch(
        f"{p.base}/tasks/{san['id']}",
        json={"version": san_now["version"], "reason": "make a loop", "depends_on": [t["ref"]]},
        headers=p.pm.headers,
    )
    assert loop.status_code == 422 and loop.json()["code"] == "dependency_cycle"
    unknown = await client.patch(
        url,
        json={"version": v, "reason": "no such task", "depends_on": ["T99"]},
        headers=p.pm.headers,
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_dependency"
    tiny = await client.patch(
        url, json={"version": v, "reason": "too short", "minutes": 5}, headers=p.pm.headers
    )
    assert tiny.status_code == 422
    # only field engineers on the team can be assigned
    stranger = await make_user(client, Role.FIELD_ENGINEER)
    not_member = await client.patch(
        url,
        json={"version": v, "reason": "assign", "assignee_id": str(stranger.id)},
        headers=p.pm.headers,
    )
    assert not_member.status_code == 422
    wrong_role = await client.patch(
        url,
        json={"version": v, "reason": "assign", "assignee_id": str(p.lead.id)},
        headers=p.pm.headers,
    )
    assert wrong_role.status_code == 422
    good = await client.patch(
        url,
        json={
            "version": v,
            "reason": "Ravi knows this site",
            "assignee_id": str(p.eng[0].id),
            "notes": "Bring a spare cable",
        },
        headers=p.pm.headers,
    )
    assert good.status_code == 200 and good.json()["assignee_id"] == str(p.eng[0].id)
    # extra fields are refused
    assert (
        await client.patch(
            url,
            json={"version": good.json()["version"], "reason": "sneaky", "ref": "T99"},
            headers=p.pm.headers,
        )
    ).status_code == 422


async def test_add_and_delete_tasks_and_edit_baselines(client: Any) -> None:
    p = await workspace(client)
    d = await generate(client, p)
    new = await client.post(
        f"{p.base}/tasks",
        json={
            "reason": "Customer asked for a label printer test",
            "title": "Label and document the patch panel",
            "minutes": 90,
            "depends_on": [d["tasks"][0]["ref"]],
            "steps": ["Label every port"],
            "evidence": [{"type": "photo", "label": "Labelled panel", "required": True}],
        },
        headers=p.pm.headers,
    )
    assert new.status_code == 201, new.text
    t = new.json()
    assert t["source"] == "manual" and t["kind"] == "manual"
    bad = await client.post(
        f"{p.base}/tasks",
        json={"reason": "bad link", "title": "X", "depends_on": ["T99"]},
        headers=p.pm.headers,
    )
    assert bad.status_code == 422
    short = await client.post(
        f"{p.base}/tasks",
        json={"reason": "too short", "title": "X", "minutes": 1},
        headers=p.pm.headers,
    )
    assert short.status_code == 422
    # deleting a task removes it from the tasks that waited for it
    victim = d["tasks"][0]
    assert (
        await client.delete(
            f"{p.base}/tasks/{victim['id']}",
            params={"reason": "Customer already did this"},
            headers=p.pm.headers,
        )
    ).status_code == 204
    cur = (await client.get(p.base, headers=p.pm.headers)).json()
    assert all(victim["ref"] not in x["depends_on"] for x in cur["tasks"])
    assert (
        await client.delete(
            f"{p.base}/tasks/{victim['id']}",
            params={"reason": "Customer already did this"},
            headers=p.pm.headers,
        )
    ).status_code == 404
    # baselines: the Director-level expertise is to tune what "correct" means
    b = cur["baselines"][0]
    fields = [
        *b["fields"][:-1],
        {**b["fields"][-1], "expected": "Changed on purpose", "severity": "minor"},
    ]
    ok = await client.patch(
        f"{p.base}/baselines/{b['id']}",
        json={"version": b["version"], "reason": "Customer policy", "fields": fields},
        headers=p.pm.headers,
    )
    assert ok.status_code == 200 and ok.json()["fields"][-1]["expected"] == "Changed on purpose"
    stale = await client.patch(
        f"{p.base}/baselines/{b['id']}",
        json={"version": b["version"], "reason": "Customer policy", "fields": fields},
        headers=p.pm.headers,
    )
    assert stale.status_code == 409
    for bad_fields in ([], [{**fields[0], "severity": "huge"}], [fields[0], fields[0]]):
        r = await client.patch(
            f"{p.base}/baselines/{b['id']}",
            json={
                "version": ok.json()["version"],
                "reason": "Customer policy",
                "fields": bad_fields,
            },
            headers=p.pm.headers,
        )
        assert r.status_code == 422, bad_fields


# ------------------------------------------------------------------ locking


async def test_baseline_needs_a_complete_schedule_then_locks_everything(client: Any) -> None:
    p = await workspace(client)
    d = await generate(client, p)
    pid = d["plan"]["id"]
    early = await client.post(f"{p.base}/{pid}/baseline", headers={**p.pm.headers, **idem()})
    assert early.status_code == 409 and early.json()["code"] == "plan_incomplete"
    await add_window(client, p)
    assert (await schedule(client, p)).status_code == 200
    # the lead may lock but the gate still needs someone else to approve it
    ok = await client.post(f"{p.base}/{pid}/baseline", headers={**p.lead.headers, **idem()})
    assert ok.status_code == 200 and ok.json()["status"] == "baselined"
    again = await client.post(f"{p.base}/{pid}/baseline", headers={**p.lead.headers, **idem()})
    assert again.status_code == 409 and again.json()["code"] == "plan_locked"
    task = (await client.get(p.base, headers=p.pm.headers)).json()["tasks"][0]
    locked = await client.patch(
        f"{p.base}/tasks/{task['id']}",
        json={"version": task["version"], "reason": "too late", "minutes": 30},
        headers=p.pm.headers,
    )
    assert locked.status_code == 409 and locked.json()["code"] == "plan_locked"
    regen = await client.post(f"{p.base}/generate", json={"replace": True}, headers=p.pm.headers)
    assert regen.status_code in (201, 409)
    # the database refuses even a direct change to a locked plan's tasks
    if regen.status_code == 409:
        async with get_sessionmaker()() as s:
            try:
                await s.execute(
                    text("UPDATE plan_tasks SET minutes = 15 WHERE plan_id = :p"), {"p": pid}
                )
                await s.commit()
                raised = False
            except DBAPIError:
                raised = True
        assert raised
    await drain_outbox()
    arts = (await client.get(f"{API}/projects/{p.pid}/artifacts", headers=p.pm.headers)).json()
    assert any(a["artifact_type"] == "implementation_plan" for a in arts)


async def test_roles_and_the_task_library(client: Any) -> None:
    p = await workspace(client)
    await generate(client, p)
    eng = p.eng[0]
    # field engineers can see the plan but never change it
    assert (await client.get(p.base, headers=eng.headers)).status_code == 200
    assert (
        await client.post(f"{p.base}/generate", json={"replace": True}, headers=eng.headers)
    ).status_code == 403
    assert (
        await client.post(
            f"{API}/planning/leaves",
            json={
                "user_id": str(eng.id),
                "date_from": str(today_ist()),
                "date_to": str(today_ist()),
            },
            headers=eng.headers,
        )
    ).status_code == 403
    # the plan carries no prices
    body = (await client.get(p.base, headers=eng.headers)).text.lower()
    assert "unit_price" not in body and "selling" not in body
    tpls = (await client.get(f"{API}/planning/task-templates", headers=p.lead.headers)).json()
    san = next(t for t in tpls if t["key"] == "sanitize")
    assert san["split_per_unit"] is True
    upd = await client.patch(
        f"{API}/planning/task-templates/sanitize",
        json={"version": san["version"], "minutes_per_unit": 60},
        headers=p.lead.headers,
    )
    assert upd.status_code == 200 and upd.json()["minutes_per_unit"] == 60
    stale = await client.patch(
        f"{API}/planning/task-templates/sanitize",
        json={"version": san["version"], "minutes_per_unit": 50},
        headers=p.lead.headers,
    )
    assert stale.status_code == 409
    assert (
        await client.patch(
            f"{API}/planning/task-templates/nope", json={"version": 1}, headers=p.lead.headers
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"{API}/planning/task-templates/sanitize",
            json={"version": upd.json()["version"], "minutes_per_unit": 60},
            headers=eng.headers,
        )
    ).status_code == 403
    cfg = (await client.get(f"{API}/planning/config-templates", headers=eng.headers)).json()
    assert {c["device_type"] for c in cfg} >= {"firewall", "switch", "nas", "server", "endpoint"}
    # the new library edit changes the next plan
    regen = await client.post(f"{p.base}/generate", json={"replace": True}, headers=p.pm.headers)
    san_minutes = {t["minutes"] for t in regen.json()["tasks"] if t["kind"] == "sanitize"}
    assert san_minutes == {60}


async def test_the_plan_prints_as_a_schedule_without_prices(client: Any) -> None:
    p = await workspace(client)
    assert (await client.get(f"{p.base}/render", headers=p.pm.headers)).status_code == 404
    await generate(client, p)
    await add_window(client, p)
    assert (await schedule(client, p)).status_code == 200
    r = await client.get(f"{p.base}/render", params={"fmt": "html"}, headers=p.pm.headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "Implementation plan 1" in html and "Target configuration per device" in html
    assert "Downtime" in html and "Not yet scheduled" not in html
    assert "₹" not in html and "Price" not in html  # plans never carry prices
    # an engineer on the project may read the plan document too
    eng = p.eng[0]
    assert (
        await client.get(f"{p.base}/render", params={"fmt": "html"}, headers=eng.headers)
    ).status_code == 200
    pdf = await client.get(f"{p.base}/render", headers=p.pm.headers)
    # WeasyPrint renders in the container; on a laptop without its libraries the API says so
    assert pdf.status_code in (200, 503)
    if pdf.status_code == 200:
        assert pdf.content.startswith(b"%PDF") and len(pdf.headers["x-content-sha256"]) == 64
    else:
        assert pdf.json()["code"] == "pdf_unavailable"
