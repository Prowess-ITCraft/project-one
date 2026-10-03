"""Projects, the eight-stage gate model, doer != verifier, and the audit trail it leaves."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.core import outbox
from app.core.db import get_sessionmaker
from app.modules.audit_log.models import AuditEntry
from app.modules.identity.permissions import Role
from tests.helpers import (
    Workspace,
    idem,
    make_customer,
    make_user,
    make_workspace,
    upload_sample_report,
)

API = "/api/v1"


async def _audit_artifact(client: Any, ws: Workspace) -> str:
    """Import and approve the sample audit so the project has a locked prismsuite_audit."""
    f = await upload_sample_report(client, ws.auditor, ws.project_id)
    r = await client.post(
        f"{API}/prismsuite/imports",
        json={"project_id": ws.project_id, "file_id": f["id"]},
        headers={**ws.auditor.headers, **idem()},
    )
    imp = r.json()
    r = await client.post(
        f"{API}/prismsuite/imports/{imp['id']}/resolutions",
        json={
            "path": "/devices[firewall]/high_availability",
            "reason": "Confirmed on site.",
            "version": imp["version"],
        },
        headers=ws.auditor.headers,
    )
    r = await client.post(
        f"{API}/prismsuite/imports/{imp['id']}/approve",
        json={"version": r.json()["version"]},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    await outbox.dispatch_batch(get_sessionmaker())
    arts = (
        await client.get(f"{API}/projects/{ws.project_id}/artifacts", headers=ws.auditor.headers)
    ).json()
    assert len(arts) == 1
    return str(arts[0]["id"])


async def _lead(client: Any, ws: Workspace) -> Any:
    lead = await make_user(client, Role.TECHNICAL_LEAD)
    r = await client.put(
        f"{API}/projects/{ws.project_id}/members",
        json={"user_id": str(lead.id), "project_role": "technical_lead"},
        headers=ws.head.headers,
    )
    assert r.status_code == 200, r.text
    return lead


async def test_project_starts_at_audit_intake(client: Any) -> None:
    ws = await make_workspace(client)
    t = (
        await client.get(f"{API}/projects/{ws.project_id}/tracker", headers=ws.sales.headers)
    ).json()
    assert [s["state"] for s in t["stages"]] == ["current"] + ["locked"] * 7
    assert t["project"]["current_stage"] == "audit_intake"


async def test_gate_needs_a_locked_artifact(client: Any) -> None:
    ws = await make_workspace(client)
    r = await client.post(
        f"{API}/projects/{ws.project_id}/stages/audit_intake/submit",
        json={"note": "ready"},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code == 422 and r.json()["code"] == "artifact_required"
    r = await client.post(
        f"{API}/projects/{ws.project_id}/stages/current_infra/submit",
        json={},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code == 409 and r.json()["code"] == "wrong_stage"


async def test_submitter_cannot_approve_their_own_gate(client: Any) -> None:
    ws = await make_workspace(client)
    art = await _audit_artifact(client, ws)
    # The architect submits and then tries to approve it too.
    r = await client.post(
        f"{API}/projects/{ws.project_id}/stages/audit_intake/submit",
        json={"artifact_id": art},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    sub = r.json()
    r = await client.post(
        f"{API}/projects/{ws.project_id}/submissions/{sub['id']}/approve",
        json={},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "segregation_of_duties"


async def test_approval_advances_the_stage_and_locks_the_decision(client: Any) -> None:
    ws = await make_workspace(client)
    art = await _audit_artifact(client, ws)
    lead = await make_user(client, Role.TECHNICAL_LEAD)
    await client.put(
        f"{API}/projects/{ws.project_id}/members",
        json={"user_id": str(lead.id), "project_role": "technical_lead"},
        headers=ws.head.headers,
    )
    r = await client.post(
        f"{API}/projects/{ws.project_id}/stages/audit_intake/submit",
        json={"artifact_id": art, "note": "audit reviewed"},
        headers={**ws.auditor.headers, **idem()},
    )
    sub = r.json()
    # A second submission while one is pending is refused.
    dup = await client.post(
        f"{API}/projects/{ws.project_id}/stages/audit_intake/submit",
        json={"artifact_id": art},
        headers={**ws.auditor.headers, **idem()},
    )
    assert dup.status_code == 409 and dup.json()["code"] == "submission_pending"
    # The sales manager is not an approver for this gate.
    r = await client.post(
        f"{API}/projects/{ws.project_id}/submissions/{sub['id']}/approve",
        json={},
        headers={**ws.sales.headers, **idem()},
    )
    assert r.status_code == 403
    r = await client.post(
        f"{API}/projects/{ws.project_id}/submissions/{sub['id']}/approve",
        json={"comment": "Looks right."},
        headers={**lead.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["artifact_type"] == "prismsuite_audit"
    t = (await client.get(f"{API}/projects/{ws.project_id}/tracker", headers=lead.headers)).json()
    assert t["project"]["current_stage"] == "current_infra"
    assert [s["state"] for s in t["stages"]][:2] == ["done", "current"]


async def test_rejection_keeps_the_stage(client: Any) -> None:
    ws = await make_workspace(client)
    art = await _audit_artifact(client, ws)
    r = await client.post(
        f"{API}/projects/{ws.project_id}/stages/audit_intake/submit",
        json={"artifact_id": art},
        headers={**ws.auditor.headers, **idem()},
    )
    sub = r.json()
    r = await client.post(
        f"{API}/projects/{ws.project_id}/submissions/{sub['id']}/reject",
        json={"comment": "Missing the second site."},
        headers={**(await _lead(client, ws)).headers, **idem()},
    )
    assert r.status_code == 200, r.text
    t = (
        await client.get(f"{API}/projects/{ws.project_id}/tracker", headers=ws.head.headers)
    ).json()
    assert t["project"]["current_stage"] == "audit_intake"


async def test_every_mutation_leaves_an_audit_entry_and_the_chain_verifies(client: Any) -> None:
    ws = await make_workspace(client)
    art = await _audit_artifact(client, ws)
    await client.post(
        f"{API}/projects/{ws.project_id}/stages/audit_intake/submit",
        json={"artifact_id": art},
        headers={**ws.auditor.headers, **idem()},
    )
    async with get_sessionmaker()() as s:
        actions = set(
            (
                await s.scalars(select(AuditEntry.action).where(AuditEntry.entity_type != "user"))
            ).all()
        )
    assert {"create", "import", "resolve_field", "approve", "gate_submitted", "upload"} <= actions
    admin = await make_user(client, Role.ADMIN)
    r = await client.get(f"{API}/audit-log/verify", headers=admin.headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


async def test_customer_rules(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    c = await make_customer(client, sm.headers, gstin="27AAPCP3476M1ZL")
    dup = await client.post(
        f"{API}/customers",
        json={
            "legal_name": "Another Co",
            "address_line1": "1 Street",
            "city": "Pune",
            "state": "Maharashtra",
            "pincode": "411001",
            "gstin": "27AAPCP3476M1ZL",
        },
        headers=sm.headers,
    )
    assert dup.status_code == 409
    bad_pin = await client.post(
        f"{API}/customers",
        json={
            "legal_name": "Bad Pin",
            "address_line1": "1 Street",
            "city": "Pune",
            "state": "Maharashtra",
            "pincode": "12",
        },
        headers=sm.headers,
    )
    assert bad_pin.status_code == 422
    ok = await client.patch(
        f"{API}/customers/{c['id']}",
        json={"city": "Thane East", "version": c["version"]},
        headers=sm.headers,
    )
    again = await client.patch(
        f"{API}/customers/{c['id']}",
        json={"city": "Mumbai", "version": c["version"]},
        headers=sm.headers,
    )
    assert ok.status_code == 200 and again.status_code == 409


async def test_soft_delete_and_restore_are_admin_only(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    admin = await make_user(client, Role.ADMIN)
    c = await make_customer(client, sm.headers)
    assert (
        await client.delete(f"{API}/customers/{c['id']}", headers=sm.headers)
    ).status_code == 403
    assert (
        await client.delete(f"{API}/customers/{c['id']}", headers=admin.headers)
    ).status_code == 204
    assert (await client.get(f"{API}/customers/{c['id']}", headers=sm.headers)).status_code == 404
    assert (
        await client.post(f"{API}/customers/{c['id']}/restore", headers=admin.headers)
    ).status_code == 200
    assert (await client.get(f"{API}/customers/{c['id']}", headers=sm.headers)).status_code == 200


async def test_unassigned_staff_do_not_see_the_project(client: Any) -> None:
    ws = await make_workspace(client)
    stranger = await make_user(client, Role.PROJECT_MANAGER)
    r = await client.get(f"{API}/projects/{ws.project_id}", headers=stranger.headers)
    assert r.status_code == 404
    listed = (await client.get(f"{API}/projects", headers=stranger.headers)).json()
    assert listed["total"] == 0
    async with get_sessionmaker()() as s:
        assert (await s.scalar(select(func.count()).select_from(AuditEntry)) or 0) > 0
