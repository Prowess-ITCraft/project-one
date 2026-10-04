"""The BOQ estimate: straight from the PrismSuite report and the questionnaire, before any gate
is approved. It saves nothing and moves nothing; the official BOQ still waits for the gates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.modules.boq.seed import seed_boq
from app.modules.boq.tests.test_boq_flow import fresh_prices
from app.modules.identity.permissions import Role
from app.modules.infra.models import GapRegister, InfraState
from tests.helpers import (
    BRIEF,
    idem,
    make_user,
    make_workspace,
    seed_reference_data,
    upload_sample_report,
)

API = "/api/v1"


async def test_estimate_from_a_report_still_in_review(client: Any) -> None:
    await seed_reference_data()
    async with get_sessionmaker()() as s:
        await seed_boq(s)
    ws = await make_workspace(client)
    await fresh_prices(client, ws.sales)
    pid = ws.project_id
    url = f"{API}/projects/{pid}/boq/estimate"

    # Nothing to estimate from yet.
    none = await client.get(url, headers=ws.sales.headers)
    assert none.status_code == 422 and none.json()["code"] == "brief_required"
    r = await client.put(f"{API}/projects/{pid}/brief", json=BRIEF, headers=ws.sales.headers)
    assert r.status_code == 200, r.text
    no_report = await client.get(url, headers=ws.sales.headers)
    assert no_report.status_code == 404 and no_report.json()["code"] == "no_audit"

    # The report is read but nobody has reviewed or approved it.
    f = await upload_sample_report(client, ws.auditor, pid)
    imp = await client.post(
        f"{API}/prismsuite/imports",
        json={"project_id": pid, "file_id": f["id"]},
        headers={**ws.auditor.headers, **idem()},
    )
    assert imp.status_code in (200, 201), imp.text

    est = await client.get(url, headers=ws.sales.headers)
    assert est.status_code == 200, est.text
    e = est.json()
    assert (
        e["basis"]["audit_approved"] is False
        and e["basis"]["company_size"] == BRIEF["company_size"]
    )
    assert e["gaps"] and e["lines"], "the sample audit has gaps, so the estimate has lines"
    assert any(x["title"].startswith("Sophos XGS-108") for x in e["lines"])
    assert not any(x["title"].startswith("Verify on site") for x in e["lines"])
    assert e["totals"]["total_max"] and float(e["totals"]["total_max"]) > 0

    # Saved nowhere: no BOQ, no infrastructure state, no gap register, and the project has not
    # moved past audit intake.
    assert (
        await client.get(f"{API}/projects/{pid}/boq", headers=ws.sales.headers)
    ).status_code == 404
    async with get_sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(InfraState)) == 0
        assert await s.scalar(select(func.count()).select_from(GapRegister)) == 0
    proj = (await client.get(f"{API}/projects/{pid}", headers=ws.sales.headers)).json()
    assert proj["current_stage"] == "audit_intake"

    # The spreadsheet is labelled as an estimate.
    x = await client.get(url, params={"fmt": "xlsx"}, headers=ws.sales.headers)
    assert x.status_code == 200 and b"ESTIMATE, NOT APPROVED" in _xlsx_text(x.content)

    # The audit engineer who read the report may draft the estimate too (ADR 0024); people
    # outside sales and the audit may not.
    assert (await client.get(url, headers=ws.auditor.headers)).status_code == 200
    lead = await make_user(client, Role.TECHNICAL_LEAD)
    assert (await client.get(url, headers=lead.headers)).status_code == 403


async def test_one_person_can_go_from_report_to_estimate(client: Any) -> None:
    """The "Upload report and draft BOQ" button: sales and audit engineers can each upload the
    report, save the questionnaire and draft the estimate without anyone else (ADR 0024)."""
    await seed_reference_data()
    async with get_sessionmaker()() as s:
        await seed_boq(s)
    ws = await make_workspace(client)
    await fresh_prices(client, ws.sales)
    pid = ws.project_id
    for who in (ws.sales, ws.auditor):
        f = await upload_sample_report(client, who, pid)
        imp = await client.post(
            f"{API}/prismsuite/imports",
            json={"project_id": pid, "file_id": f["id"]},
            headers={**who.headers, **idem()},
        )
        if who is ws.sales:
            assert imp.status_code == 201, imp.text
            first = imp.json()
        else:  # the same file again: refused, and the button carries on with the first import
            assert imp.status_code == 409 and imp.json()["code"] == "already_imported"
        cur = (await client.get(f"{API}/projects/{pid}/brief", headers=who.headers)).json()
        body = {**BRIEF, "version": cur["version"]} if cur else BRIEF
        r = await client.put(f"{API}/projects/{pid}/brief", json=body, headers=who.headers)
        assert r.status_code == 200, r.text
        est = await client.get(f"{API}/projects/{pid}/boq/estimate", headers=who.headers)
        assert est.status_code == 200 and est.json()["lines"], est.text
    # Reviewing and approving the audit still belongs to the audit side.
    approve = await client.post(
        f"{API}/prismsuite/imports/{first['id']}/approve",
        json={},
        headers=ws.sales.headers,
    )
    assert approve.status_code == 403


def _xlsx_text(data: bytes) -> bytes:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return b"".join(z.read(n) for n in z.namelist() if n.endswith(".xml"))
