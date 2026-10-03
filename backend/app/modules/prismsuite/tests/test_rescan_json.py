"""Baseline and rescan reports, and the structured JSON export adapter."""

from __future__ import annotations

import json
from typing import Any

from app.modules.prismsuite.parsers import base, docx_v1, json_v1
from tests.helpers import Workspace, idem, make_workspace, sample_report_path, upload_sample_report

BASE = "/api/v1/prismsuite/imports"


def _snapshot_json(security: str = "58.7", reference: str = "PS-01102026-SHA") -> bytes:
    snap = docx_v1.PrismSuiteParserV1().parse(sample_report_path().read_bytes()).snapshot
    doc = snap.model_dump(mode="json")
    doc["scores"]["security"]["value"] = security
    doc["header"]["report_reference"] = reference
    return json.dumps(doc).encode()


async def _upload_json(client: Any, user: Any, project_id: str, data: bytes) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/files",
        files={"file": ("export.json", data, "application/json")},
        data={"purpose": "audit_report", "project_id": project_id},
        headers=user.headers,
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _approved_baseline(client: Any, ws: Workspace) -> dict[str, Any]:
    f = await upload_sample_report(client, ws.auditor, ws.project_id)
    imp = (
        await client.post(
            BASE,
            json={"project_id": ws.project_id, "file_id": f["id"]},
            headers={**ws.auditor.headers, **idem()},
        )
    ).json()
    r = await client.post(
        f"{BASE}/{imp['id']}/resolutions",
        json={
            "path": "/devices[firewall]/high_availability",
            "reason": "Confirmed on site.",
            "version": imp["version"],
        },
        headers=ws.auditor.headers,
    )
    r = await client.post(
        f"{BASE}/{imp['id']}/approve",
        json={"version": r.json()["version"]},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_json_adapter_detects_and_parses() -> None:
    data = _snapshot_json()
    assert json_v1.PrismSuiteJsonParserV1().detect(data) >= 0.9
    assert json_v1.PrismSuiteJsonParserV1().detect(b"not json") == 0.0
    assert json_v1.PrismSuiteJsonParserV1().detect(b'{"a": 1}') < 0.5
    p = base.pick(data, "json")
    assert p is not None and p.name == "prismsuite.json.v1"
    result = p.parse(data)
    assert result.snapshot.header.customer_name == "Shakti Equipments Pvt Ltd"
    assert result.report.blocking == []


def test_json_adapter_reports_missing_required_fields() -> None:
    doc = json.loads(_snapshot_json())
    doc["header"]["customer_name"] = None
    result = json_v1.PrismSuiteJsonParserV1().parse(json.dumps(doc).encode())
    assert [f.path for f in result.report.blocking] == ["/header/customer_name"]


async def test_json_export_imports_like_a_word_report(client: Any) -> None:
    ws = await make_workspace(client)
    f = await _upload_json(client, ws.auditor, ws.project_id, _snapshot_json())
    r = await client.post(
        BASE,
        json={"project_id": ws.project_id, "file_id": f["id"]},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    assert r.json()["parser_name"] == "prismsuite.json.v1" and r.json()["kind"] == "baseline"


async def test_rescan_needs_an_approved_baseline(client: Any) -> None:
    ws = await make_workspace(client)
    f = await _upload_json(client, ws.auditor, ws.project_id, _snapshot_json("71.2", "PS-RESCAN-1"))
    r = await client.post(
        BASE,
        json={"project_id": ws.project_id, "file_id": f["id"], "kind": "rescan"},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code == 409 and r.json()["code"] == "baseline_required"


async def test_rescan_is_kept_beside_the_baseline_and_does_not_supersede_it(client: Any) -> None:
    from app.core import outbox
    from app.core.db import get_sessionmaker

    ws = await make_workspace(client)
    await _approved_baseline(client, ws)
    f = await _upload_json(client, ws.auditor, ws.project_id, _snapshot_json("71.2", "PS-RESCAN-1"))
    r = await client.post(
        BASE,
        json={"project_id": ws.project_id, "file_id": f["id"], "kind": "rescan"},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["kind"] == "rescan" and imp["revision"] == 2
    r = await client.post(
        f"{BASE}/{imp['id']}/approve",
        json={"version": imp["version"]},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 200, r.text  # no firewall conflict in the JSON, so nothing blocks
    listed = (
        await client.get(f"{BASE}/by-project/{ws.project_id}", headers=ws.architect.headers)
    ).json()
    assert {(i["kind"], i["status"]) for i in listed} == {
        ("baseline", "approved"),
        ("rescan", "approved"),
    }

    # The rescan does not add a second Audit intake artifact; only the baseline locked one.
    await outbox.dispatch_batch(get_sessionmaker())
    arts = (
        await client.get(
            f"/api/v1/projects/{ws.project_id}/artifacts", headers=ws.architect.headers
        )
    ).json()
    assert [a["artifact_type"] for a in arts] == ["prismsuite_audit"]
