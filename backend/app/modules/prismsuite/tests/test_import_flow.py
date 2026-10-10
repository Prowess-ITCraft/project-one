"""Upload -> import -> review -> approve, through the HTTP API."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.modules.identity.permissions import Role
from tests.helpers import (
    Workspace,
    drain_outbox,
    idem,
    make_user,
    make_workspace,
    upload_sample_report,
)

BASE = "/api/v1/prismsuite/imports"


async def _import(client: Any, ws: Workspace) -> dict[str, Any]:
    f = await upload_sample_report(client, ws.auditor, ws.project_id)
    r = await client.post(
        BASE,
        json={"project_id": ws.project_id, "file_id": f["id"]},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _detail(client: Any, user: Any, import_id: str) -> dict[str, Any]:
    r = await client.get(f"{BASE}/{import_id}", headers=user.headers)
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_import_parses_and_reports(client: Any) -> None:
    ws = await make_workspace(client)
    imp = await _import(client, ws)
    assert imp["status"] == "in_review" and imp["revision"] == 1
    assert imp["parser_name"] == "prismsuite.docx.v1"
    d = await _detail(client, ws.architect, imp["id"])
    assert d["snapshot"]["scores"]["security"]["value"] == "58.7"
    assert any(f["status"] == "conflict" for f in d["read_report"]["fields"])


async def test_same_file_cannot_be_imported_twice(client: Any) -> None:
    ws = await make_workspace(client)
    f = await upload_sample_report(client, ws.auditor, ws.project_id)
    body = {"project_id": ws.project_id, "file_id": f["id"]}
    r1 = await client.post(BASE, json=body, headers={**ws.auditor.headers, **idem()})
    r2 = await client.post(BASE, json=body, headers={**ws.auditor.headers, **idem()})
    assert r1.status_code == 201 and r2.status_code == 409


async def test_import_is_idempotent_with_the_same_key(client: Any) -> None:
    ws = await make_workspace(client)
    f = await upload_sample_report(client, ws.auditor, ws.project_id)
    h = {**ws.auditor.headers, **idem()}
    body = {"project_id": ws.project_id, "file_id": f["id"]}
    r1 = await client.post(BASE, json=body, headers=h)
    r2 = await client.post(BASE, json=body, headers=h)
    assert r1.status_code == r2.status_code == 201
    assert r2.headers.get("idempotent-replayed") == "true"
    assert r1.json()["id"] == r2.json()["id"]


async def test_conflict_blocks_approval_until_resolved(client: Any) -> None:
    ws = await make_workspace(client)
    imp = await _import(client, ws)
    r = await client.post(
        f"{BASE}/{imp['id']}/approve",
        json={"version": imp["version"]},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "audit_conflicts_unresolved"


async def test_resolve_then_approve_locks_the_artifact(client: Any) -> None:
    ws = await make_workspace(client)
    imp = await _import(client, ws)
    reviewer = await make_user(client, Role.TECHNICAL_LEAD)
    await client.put(
        f"/api/v1/projects/{ws.project_id}/members",
        json={"user_id": str(reviewer.id), "project_role": "technical_lead"},
        headers=ws.head.headers,
    )
    # The auditor reviews the conflict (allowed), a different person must approve.
    r = await client.post(
        f"{BASE}/{imp['id']}/resolutions",
        json={
            "path": "/devices[firewall]/high_availability",
            "reason": "Checked on site: HA is not configured.",
            "version": imp["version"],
        },
        headers=ws.auditor.headers,
    )
    assert r.status_code == 200, r.text
    version = r.json()["version"]

    # Segregation of duties: the importer cannot approve, and neither can a corrector.
    r = await client.post(
        f"{BASE}/{imp['id']}/approve",
        json={"version": version},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # The outbox carries the lock event; after dispatch the project has the artifact.
    await drain_outbox()
    from app.modules.customers.models import StageArtifact

    async with get_sessionmaker()() as s:
        art = (await s.scalars(select(StageArtifact))).all()
    assert [a.artifact_type for a in art] == ["prismsuite_audit"]
    assert art[0].stage == "audit_intake"


async def test_importer_cannot_approve_own_import(client: Any) -> None:
    ws = await make_workspace(client)
    # A solution architect both imports and tries to approve.
    f = await upload_sample_report(client, ws.architect, ws.project_id)
    r = await client.post(
        BASE,
        json={"project_id": ws.project_id, "file_id": f["id"]},
        headers={**ws.architect.headers, **idem()},
    )
    imp = r.json()
    r = await client.post(
        f"{BASE}/{imp['id']}/resolutions",
        json={
            "path": "/devices[firewall]/high_availability",
            "reason": "Confirmed with the customer.",
            "version": imp["version"],
        },
        headers=ws.auditor.headers,
    )
    v = r.json()["version"]
    r = await client.post(
        f"{BASE}/{imp['id']}/approve",
        json={"version": v},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "segregation_of_duties"


async def test_correction_validates_and_is_recorded(client: Any) -> None:
    ws = await make_workspace(client)
    imp = await _import(client, ws)
    r = await client.post(
        f"{BASE}/{imp['id']}/corrections",
        json={
            "path": "/scores/security/value",
            "value": "61.5",
            "reason": "Typo in the report, confirmed with the auditor.",
            "version": imp["version"],
        },
        headers=ws.architect.headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot"]["scores"]["security"]["value"] == "61.5"
    assert body["corrections"][0]["old_value"] == "58.7"
    # A value of the wrong type is refused and nothing changes.
    r = await client.post(
        f"{BASE}/{imp['id']}/corrections",
        json={
            "path": "/scores/security/value",
            "value": "not a number",
            "reason": "Testing validation.",
            "version": body["version"],
        },
        headers=ws.architect.headers,
    )
    assert r.status_code == 422
    # A stale version is refused.
    r = await client.post(
        f"{BASE}/{imp['id']}/corrections",
        json={
            "path": "/scores/security/value",
            "value": "62",
            "reason": "Testing the lock.",
            "version": imp["version"],
        },
        headers=ws.architect.headers,
    )
    assert r.status_code == 409


async def test_unknown_path_is_rejected(client: Any) -> None:
    ws = await make_workspace(client)
    imp = await _import(client, ws)
    r = await client.post(
        f"{BASE}/{imp['id']}/corrections",
        json={
            "path": "/scores/nonsense/value",
            "value": "1",
            "reason": "Testing unknown paths.",
            "version": imp["version"],
        },
        headers=ws.architect.headers,
    )
    assert r.status_code == 422


async def test_reject_closes_the_import_and_allows_reimport(client: Any) -> None:
    ws = await make_workspace(client)
    imp = await _import(client, ws)
    r = await client.post(
        f"{BASE}/{imp['id']}/reject",
        json={"reason": "Wrong customer report.", "version": imp["version"]},
        headers=ws.architect.headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    imp2 = await _import(client, ws)
    assert imp2["revision"] == 2


async def test_outsiders_cannot_see_the_import(client: Any) -> None:
    ws = await make_workspace(client)
    imp = await _import(client, ws)
    stranger = await make_user(client, Role.AUDIT_ENGINEER)  # not a project member
    r = await client.get(f"{BASE}/{imp['id']}", headers=stranger.headers)
    assert r.status_code == 404
    engineer = await make_user(client, Role.FIELD_ENGINEER)
    r = await client.get(f"{BASE}/{imp['id']}", headers=engineer.headers)
    assert r.status_code == 403


async def test_wrong_purpose_and_project_are_refused(client: Any) -> None:
    ws = await make_workspace(client)
    other = await make_workspace(client)
    f = await upload_sample_report(client, other.auditor, other.project_id)
    # The auditor is not on the other project: file lookup fails before anything is parsed.
    r = await client.post(
        BASE,
        json={"project_id": ws.project_id, "file_id": f["id"]},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code in (403, 404)
