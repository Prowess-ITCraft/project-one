"""A task walks from assigned to closed (ADR 0015): nothing skipped, customer codes at check-in
and hand over, the configuration check, a verifier who did not do the work, and a message to the
customer and the Director at every step."""

from __future__ import annotations

import io
import re
import uuid
from typing import Any

from PIL import Image
from sqlalchemy import select, text

from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.modules.identity.permissions import Role
from app.modules.notifications.models import Notification
from app.modules.planning.tests.test_plan_flow import (
    Plan,
    add_window,
    generate,
    schedule,
    workspace,
)
from tests.helpers import idem, make_user

API = "/api/v1"
FIELD = f"{API}/field"


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 80, 200)).save(out, format="PNG")
    return out.getvalue()


async def _code(run_id: str, template: str) -> str:
    async with get_sessionmaker()() as s:
        n = await s.scalar(
            select(Notification)
            .where(Notification.related_id == run_id, Notification.template == template)
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
    assert n is not None
    m = re.search(r"\b(\d{6})\b", n.body)
    assert m, n.body
    return m.group(1)


async def field_ready(client: Any) -> tuple[Plan, Any, list[dict[str, Any]]]:
    """A baselined plan, the project at the field work stage, a customer contact who can sign
    off, and an engineer who is also a technical lead (to prove they cannot verify their work)."""
    p = await workspace(client, engineers=1)
    await generate(client, p)
    await add_window(client, p)
    assert (await schedule(client, p)).status_code == 200
    plan = (await client.get(p.base, headers=p.pm.headers)).json()["plan"]
    r = await client.post(f"{p.base}/{plan['id']}/baseline", headers={**p.lead.headers, **idem()})
    assert r.status_code == 200, r.text

    early = await client.post(
        f"{API}/projects/{p.pid}/field/start", headers={**p.pm.headers, **idem()}
    )
    assert early.status_code == 409 and early.json()["code"] == "plan_not_approved"
    async with get_sessionmaker()() as s:  # the plan gate itself is covered by the gate tests
        await s.execute(
            text("UPDATE projects SET current_stage = 'field_work' WHERE id = :p"), {"p": p.pid}
        )
        await s.commit()

    cust = p.c.ws.customer["id"]
    r = await client.post(
        f"{API}/customers/{cust}/contacts",
        json={"full_name": "Meera Shah", "email": "meera@shakti.example", "can_sign_off": True},
        headers=p.c.sm.headers,
    )
    assert r.status_code == 201, r.text

    await get_redis().flushall()
    both = await make_user(client, Role.FIELD_ENGINEER, Role.TECHNICAL_LEAD)
    await get_redis().flushall()
    r = await client.put(
        f"{API}/projects/{p.pid}/members",
        json={"user_id": str(both.id), "project_role": "field_engineer"},
        headers=p.c.ws.head.headers,
    )
    assert r.status_code == 200, r.text

    r = await client.post(f"{API}/projects/{p.pid}/field/start", headers={**p.pm.headers, **idem()})
    assert r.status_code == 201, r.text
    return p, both, list(r.json())


def _judgeable(f: dict[str, Any]) -> bool:
    return f["severity"] in ("critical", "major") and f["expected"] in ("Enabled", "Configured")


async def _post(client: Any, user: Any, path: str, body: dict[str, Any] | None = None) -> Any:
    return await client.post(f"{FIELD}/runs/{path}", json=body or {}, headers=user.headers)


async def _evidence(
    client: Any, user: Any, run: dict[str, Any], index: int, cid: str | None = None
) -> Any:
    req = run["evidence_reqs"][index]
    data: dict[str, str] = {"requirement_index": str(index), "client_id": cid or str(uuid.uuid4())}
    files = None
    if req["type"] in ("photo", "screenshot"):
        files = {"file": ("e.png", _png(), "image/png")}
    elif req["type"] == "config_export":
        files = {"file": ("fw.txt", b"set admin mfa enable\n", "text/plain")}
    elif req["type"] == "serial":
        data["text_value"] = "SN-12345"
    else:
        data["text_value"] = "Done with the customer's IT contact"
    return await client.post(
        f"{FIELD}/runs/{run['id']}/evidence", data=data, files=files, headers=user.headers
    )


async def test_a_task_walks_from_assigned_to_closed(client: Any) -> None:
    p, both, runs = await field_ready(client)
    assert all("price" not in str(r).lower() for r in runs)  # field work never carries prices
    # a task the engine can judge: a critical or major setting with a yes/no target
    run = next(r for r in runs if not r["depends_on"] and any(_judgeable(f) for f in r["baseline"]))
    rid = run["id"]

    # the project manager hands it to the engineer who is also a technical lead
    r = await _post(
        client, p.pm, f"{rid}/reassign", {"assignee_id": str(both.id), "reason": "Closer to site"}
    )
    assert r.status_code == 200, r.text
    eng = both

    # nothing can be skipped
    assert (await _post(client, eng, f"{rid}/configured")).json()["code"] == "bad_state"
    first = str(uuid.uuid4())
    r = await _post(client, eng, f"{rid}/accept", {"client_event_id": first})
    assert r.status_code == 200 and r.json()["run"]["state"] == "accepted"
    again = await _post(client, eng, f"{rid}/accept", {"client_event_id": first})  # resent offline
    assert again.status_code == 200
    assert sum(1 for e in again.json()["events"] if e["action"] == "accept") == 1
    assert r.json()["next_action"] == "Add: Photo of the site on arrival."

    # check-in: arrival photo, then the customer's code
    assert (
        await client.post(f"{FIELD}/runs/{rid}/codes/check_in", headers=eng.headers)
    ).status_code == 200
    no_photo = await _post(client, eng, f"{rid}/check-in", {"code": "000000"})
    assert no_photo.json()["code"] == "evidence_missing"
    cid = str(uuid.uuid4())
    ev = await _evidence(client, eng, run, 0, cid)
    assert ev.status_code == 201, ev.text
    resent = await _evidence(client, eng, run, 0, cid)  # a dropped upload sent again
    assert resent.json()["id"] == ev.json()["id"]
    code = await _code(rid, "otp_check_in")
    wrong = "111111" if code != "111111" else "222222"
    bad = await _post(client, eng, f"{rid}/check-in", {"code": wrong})
    assert bad.status_code == 422 and bad.json()["code"] == "otp_invalid"
    r = await _post(client, eng, f"{rid}/check-in", {"code": code, "lat": 19.07, "lng": 72.87})
    assert r.status_code == 200 and r.json()["run"]["state"] == "checked_in"

    # prechecks: backup and access, with evidence
    assert (await _post(client, eng, f"{rid}/prechecks-done")).json()["code"] == "evidence_missing"
    for i in (1, 2):
        assert (await _evidence(client, eng, run, i)).status_code == 201
    r = await _post(client, eng, f"{rid}/prechecks-done")
    assert r.json()["run"]["state"] == "prechecks_done"

    # steps go in order; then a value for every target setting
    if len(run["steps"]) > 1:
        assert (await _post(client, eng, f"{rid}/steps/1")).json()["code"] == "step_order"
    for i in range(len(run["steps"])):
        assert (await _post(client, eng, f"{rid}/steps/{i}")).status_code == 200
    assert (await _post(client, eng, f"{rid}/configured")).json()["code"] == "work_incomplete"
    critical = next(f for f in run["baseline"] if _judgeable(f))
    good = {f["key"]: "enabled" for f in run["baseline"]}
    for f in run["baseline"]:
        if f["expected"].lower().startswith(("at least", "above")):
            good[f["key"]] = "99"
    bad_values = {**good, critical["key"]: "disabled"}
    r = await _post(client, eng, f"{rid}/values", {"values": bad_values})
    assert r.status_code == 200, r.text
    r = await _post(client, eng, f"{rid}/configured")
    assert r.json()["run"]["state"] == "configured"

    # evidence, then the engine check fails on the critical setting and sends it back
    r = await _post(client, eng, f"{rid}/submit-evidence")
    assert r.json()["code"] == "evidence_missing"
    for i in range(3, len(run["evidence_reqs"])):
        assert (await _evidence(client, eng, run, i)).status_code == 201
    r = await _post(client, eng, f"{rid}/submit-evidence")
    body = r.json()
    assert body["run"]["state"] == "configured" and body["run"]["rework_count"] == 1
    assert body["checks"][0]["passed"] is False and body["checks"][0]["deviations"] >= 1
    assert body["next_action"].startswith("Fix what was sent back")
    assert [e["action"] for e in body["events"]][-3:] == [
        "evidence_uploaded",
        "engine_check",
        "engine_mismatch",
    ]

    # fixed: the check passes and the task waits for the customer's hand over code
    await _post(client, eng, f"{rid}/values", {"values": good})
    r = await _post(client, eng, f"{rid}/submit-evidence")
    assert r.json()["run"]["state"] == "engine_check" and r.json()["checks"][-1]["passed"] is True
    assert (
        await client.post(f"{FIELD}/runs/{rid}/codes/handover", headers=eng.headers)
    ).status_code == 200
    r = await _post(client, eng, f"{rid}/hand-over", {"code": await _code(rid, "otp_handover")})
    assert r.status_code == 200 and r.json()["run"]["state"] == "verifier_review"

    # the person who did the work cannot verify it, even holding the verifier role
    own = await _post(client, eng, f"{rid}/decision", {"decision": "approve"})
    assert own.status_code == 403 and own.json()["code"] == "segregation_of_duties"
    queue = (await client.get(f"{FIELD}/review-queue", headers=p.lead.headers)).json()
    assert [q["id"] for q in queue] == [rid]
    assert (await client.get(f"{FIELD}/review-queue", headers=eng.headers)).json() == []

    # the verifier sends it back once, then closes it
    no_reason = await _post(client, p.lead, f"{rid}/decision", {"decision": "reject"})
    assert no_reason.json()["code"] == "reason_required"
    r = await _post(
        client,
        p.lead,
        f"{rid}/decision",
        {"decision": "reject", "reason": "Photo of the label is blurred"},
    )
    assert r.json()["run"]["state"] == "configured" and r.json()["run"]["rework_count"] == 2
    r = await _post(client, eng, f"{rid}/submit-evidence")
    assert r.json()["run"]["state"] == "engine_check"
    await client.post(f"{FIELD}/runs/{rid}/codes/handover", headers=eng.headers)
    await _post(client, eng, f"{rid}/hand-over", {"code": await _code(rid, "otp_handover")})
    r = await _post(client, p.lead, f"{rid}/decision", {"decision": "approve"})
    assert r.json()["run"]["state"] == "closed" and r.json()["run"]["verified_by"] == str(p.lead.id)
    assert r.json()["next_action"] == "Done. Nothing more to do."

    # every state change told the customer and the Director
    async with get_sessionmaker()() as s:
        updates = list(
            await s.scalars(
                select(Notification).where(
                    Notification.related_id == rid, Notification.template == "task_update"
                )
            )
        )
    to = {n.to_address for n in updates}
    assert "meera@shakti.example" in to and p.c.director.email in to
    states = {re.search(r"is now (.*)$", n.subject).group(1) for n in updates}  # type: ignore[union-attr]
    assert {"accepted by the engineer", "checked in on site", "closed and verified"} <= states
    assert all("₹" not in n.body and "price" not in n.body.lower() for n in updates)

    # the live feed, the Director's summary and the printable record
    events = (
        await client.get(
            f"{API}/projects/{p.pid}/field/events", params={"after": 0}, headers=p.pm.headers
        )
    ).json()
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(seqs) > 15
    later = (
        await client.get(
            f"{API}/projects/{p.pid}/field/events", params={"after": seqs[-2]}, headers=p.pm.headers
        )
    ).json()
    assert [e["seq"] for e in later] == seqs[-1:]
    summary = (
        await client.get(f"{API}/projects/{p.pid}/field/summary", headers=p.pm.headers)
    ).json()
    assert summary["counts"]["closed"] == 1 and summary["rework"] == 2
    html = (
        await client.get(
            f"{FIELD}/runs/{rid}/render", params={"fmt": "html"}, headers=p.lead.headers
        )
    ).text
    assert "Timeline" in html and "Configuration check 1" in html and "Failed" in html
    assert "data:image/png;base64," in html  # photos are embedded, never fetched


async def test_blocking_dependencies_and_access(client: Any) -> None:
    p, _both, runs = await field_ready(client)
    eng = p.eng[0]
    mine = [r for r in runs if r["assignee_id"] == str(eng.id)]
    assert mine
    run = mine[0]
    rid = run["id"]

    # an engineer only sees their own tasks; another engineer cannot touch them
    await get_redis().flushall()
    other = await make_user(client, Role.FIELD_ENGINEER)
    assert (await client.get(f"{FIELD}/runs/{rid}", headers=other.headers)).status_code == 404
    assert {r["id"] for r in (await client.get(f"{FIELD}/my", headers=eng.headers)).json()} == {
        r["id"] for r in mine
    }

    # block and unblock: back to where it was
    await _post(client, eng, f"{rid}/accept")
    r = await _post(client, eng, f"{rid}/block", {"reason": "Customer office is closed today"})
    assert r.json()["run"]["state"] == "blocked"
    assert (await _post(client, eng, f"{rid}/unblock", {"note": "Rescheduled"})).status_code == 403
    r = await _post(client, p.pm, f"{rid}/unblock", {"note": "Rescheduled to Monday"})
    assert r.json()["run"]["state"] == "accepted"

    # a task whose prerequisite is not handed over cannot be checked in
    dependent = next((r for r in runs if r["depends_on"]), None)
    if dependent is not None:
        owner = eng if dependent["assignee_id"] == str(eng.id) else _both
        await _post(client, owner, f"{dependent['id']}/accept")
        r = await client.post(
            f"{FIELD}/runs/{dependent['id']}/codes/check_in", headers=owner.headers
        )
        assert r.status_code == 409 and r.json()["code"] == "dependencies_open"

    # captured too long ago is refused
    from datetime import timedelta

    from app.core.timeutil import utcnow

    old = (utcnow() - timedelta(hours=80)).isoformat()
    r = await _post(client, eng, f"{rid}/depart", {"captured_at": old})
    assert r.status_code == 422 and r.json()["code"] == "too_old"

    # starting twice is refused
    r = await client.post(f"{API}/projects/{p.pid}/field/start", headers={**p.pm.headers, **idem()})
    assert r.status_code == 409 and r.json()["code"] == "already_started"


async def test_the_completion_gate_reads_field_status(client: Any) -> None:
    """Phase 10 asks the fieldops contract whether field work is finished."""
    import uuid as _uuid

    from app.modules.fieldops.contracts import field_status
    from app.modules.identity.contracts import P, system_principal

    p, _both, runs = await field_ready(client)
    reader = system_principal(
        "completion", frozenset({P.FIELD_READ, P.PROJECT_READ, P.PROJECT_READ_ALL})
    )
    async with get_sessionmaker()() as s:
        st = await field_status(s, reader, _uuid.UUID(p.pid))
    assert st.total == len(runs) and st.closed == 0 and not st.complete
    assert sorted(st.open_refs) == sorted(r["task_ref"] for r in runs)
    assert st.open_critical_deviations == 0
