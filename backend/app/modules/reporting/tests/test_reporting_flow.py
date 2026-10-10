"""Completion end to end (phase 10, ADR 0019): waivers approved by the Director and acknowledged
by the customer, the release conditions, the locked completion report, and the "Certified by
IITPL" certificate that only a Director signs, verifiable by anyone and revocable."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.modules.fieldops.tests.test_field_flow import _png, field_ready
from app.modules.identity.permissions import Role
from app.modules.notifications.models import Notification
from app.modules.prismsuite.tests.test_rescan_json import _snapshot_json, _upload_json
from app.modules.reporting.models import Certificate
from app.modules.reporting.service import signature_ok
from app.modules.verification.seed import seed_verification
from tests.helpers import drain_outbox, idem, make_user

API = "/api/v1"
REP = f"{API}/reporting"


@pytest.fixture(autouse=True)
def pdf_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    """WeasyPrint renders in the container. On a laptop without its system libraries the
    report and certificate still need a PDF to lock, so a stand-in returns the HTML as bytes;
    every rule around it runs unchanged."""
    import hashlib

    from app.core.documents import RenderedDocument, pdf_available
    from app.modules.reporting import render

    if pdf_available():
        return

    def fake(html: str) -> RenderedDocument:
        data = b"%PDF-1.7 stand-in\n" + html.encode()
        return RenderedDocument(data, hashlib.sha256(data).hexdigest(), 1)

    monkeypatch.setattr(render, "render_pdf", fake)


async def _close_runs(run_ids: list[str], verifier: uuid.UUID) -> None:
    """The field walk itself is covered by the fieldops tests; here the work is simply done."""
    async with get_sessionmaker()() as s:
        for rid in run_ids:
            await s.execute(
                text(
                    "UPDATE task_runs SET state = 'closed', checked_in_at = now(), "
                    "closed_at = now(), verified_by = :v WHERE id = :r"
                ),
                {"v": verifier, "r": rid},
            )
        await s.commit()


async def _set_stage(pid: str, stage: str) -> None:
    async with get_sessionmaker()() as s:
        await s.execute(
            text("UPDATE projects SET current_stage = :s WHERE id = :p"), {"s": stage, "p": pid}
        )
        await s.commit()


async def _waiver_token(waiver_id: str) -> str:
    async with get_sessionmaker()() as s:
        n = await s.scalar(
            select(Notification)
            .where(Notification.related_id == waiver_id, Notification.template == "waiver_ack")
            .limit(1)
        )
    assert n is not None
    m = re.search(r"/ack/waiver/([A-Za-z0-9_\-]{20,})", n.body)
    assert m, n.body
    return m.group(1)


async def _conditions(client: Any, user: Any, pid: str) -> dict[str, dict[str, Any]]:
    r = await client.get(f"{REP}/projects/{pid}/conditions", headers=user.headers)
    assert r.status_code == 200, r.text
    return {c["key"]: c for c in r.json()}


async def _waive(client: Any, p: Any, director: Any, scope: str, target: str) -> dict[str, Any]:
    r = await client.post(
        f"{REP}/projects/{p.pid}/waivers",
        json={
            "scope": scope,
            "target_id": target,
            "kind": "deferred_by_customer",
            "reason": "The customer moves this to next quarter's budget.",
        },
        headers=p.pm.headers,
    )
    assert r.status_code == 201, r.text
    w = r.json()
    r = await client.post(
        f"{REP}/waivers/{w['id']}/decision",
        json={"decision": "approve", "note": "Agreed on the review call"},
        headers=director.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and "*" in r.json()["sent_to"]
    token = await _waiver_token(w["id"])
    view = await client.get(f"{API}/public/waivers/{token}")
    assert view.status_code == 200 and view.json()["already_acknowledged"] is False
    assert "price" not in view.text.lower() and "meera@" not in view.text
    ok = await client.post(
        f"{API}/public/waivers/{token}", json={"full_name": "Meera Shah", "accept": True}
    )
    assert ok.status_code == 204, ok.text
    return dict(w)


async def _approved_rescan(client: Any, p: Any) -> None:
    ws = p.c.ws
    f = await _upload_json(client, ws.auditor, p.pid, _snapshot_json("71.2", "PS-RESCAN-1"))
    r = await client.post(
        f"{API}/prismsuite/imports",
        json={"project_id": p.pid, "file_id": f["id"], "kind": "rescan"},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    imp = r.json()
    r = await client.post(
        f"{API}/prismsuite/imports/{imp['id']}/approve",
        json={"version": imp["version"]},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 200, r.text


async def _upload_stamp(client: Any, user: Any) -> Any:
    return await client.post(
        f"{REP}/settings/stamp",
        files={"file": ("iitpl-stamp.png", _png(), "image/png")},
        headers=user.headers,
    )


async def _completion_signoff(client: Any, p: Any, director: Any) -> None:
    """The completion gate: the PM submits the locked report, the customer acknowledges it by
    link, and a Director approves (the final check)."""
    await drain_outbox()
    arts = (await client.get(f"{API}/projects/{p.pid}/artifacts", headers=p.pm.headers)).json()
    art = next(a for a in arts if a["artifact_type"] == "completion_report")
    r = await client.post(
        f"{API}/projects/{p.pid}/stages/completion/submit",
        json={"artifact_id": art["id"]},
        headers={**p.pm.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    sub = r.json()
    contacts = (
        await client.get(
            f"{API}/customers/{p.c.ws.customer['id']}/contacts", headers=p.c.sm.headers
        )
    ).json()
    contact = next(c for c in contacts if c["full_name"] == "Meera Shah")
    r = await client.post(
        f"{API}/projects/{p.pid}/submissions/{sub['id']}/customer-ack",
        json={"contact_id": contact["id"]},
        headers=p.c.sm.headers,
    )
    assert r.status_code == 201, r.text
    token = re.search(r"([A-Za-z0-9_\-]{20,})$", r.json()["url"]).group(1)  # type: ignore[union-attr]
    r = await client.post(
        f"{API}/public/acks/{token}", json={"full_name": "Meera Shah", "accept": True}
    )
    assert r.status_code == 204, r.text
    r = await client.post(
        f"{API}/projects/{p.pid}/submissions/{sub['id']}/approve",
        json={"comment": "Final check done"},
        headers={**director.headers, **idem()},
    )
    assert r.status_code == 200, r.text


async def test_waiver_report_and_certificate(client: Any) -> None:
    async with get_sessionmaker()() as s:
        await seed_verification(s)
    p, _both, runs = await field_ready(client)
    director = p.c.director

    cond = await _conditions(client, p.pm, p.pid)
    assert not cond["work"]["met"] and not cond["rescan"]["met"] and not cond["stamp"]["met"]
    assert cond["deviations"]["met"] and cond["waivers"]["met"]

    # all but one task done; the last one is deferred by the customer through a waiver
    *done, last = runs
    await _close_runs([r["id"] for r in done], p.lead.id)
    assert last["task_ref"] in (await _conditions(client, p.pm, p.pid))["work"]["detail"]
    r = await client.post(
        f"{REP}/projects/{p.pid}/field-summary", headers={**p.pm.headers, **idem()}
    )
    assert r.status_code == 409 and r.json()["code"] == "not_ready"

    w = await _waive(client, p, director, "task", last["id"])
    again = await client.post(
        f"{REP}/projects/{p.pid}/waivers",
        json={
            "scope": "task",
            "target_id": last["id"],
            "kind": "not_applicable",
            "reason": "Asked a second time by mistake",
        },
        headers=p.pm.headers,
    )
    assert again.status_code == 409 and again.json()["code"] == "already_waived"
    listed = (await client.get(f"{REP}/projects/{p.pid}/waivers", headers=p.pm.headers)).json()
    assert [(x["id"], x["status"]) for x in listed] == [(w["id"], "acknowledged")]
    assert listed[0]["acknowledged_name"] == "Meera Shah"
    cond = await _conditions(client, p.pm, p.pid)
    assert cond["work"]["met"] and cond["waivers"]["met"]

    r = await client.post(
        f"{REP}/projects/{p.pid}/field-summary", headers={**p.pm.headers, **idem()}
    )
    assert r.status_code == 200, r.text

    # the completion stage: the report waits for the rescan and the stamp
    await _set_stage(p.pid, "completion")
    r = await client.post(f"{REP}/projects/{p.pid}/reports", headers={**p.pm.headers, **idem()})
    assert r.status_code == 409 and r.json()["code"] == "not_ready"
    assert len(r.json()["missing"]) == 2
    await _approved_rescan(client, p)
    assert (await _upload_stamp(client, p.pm)).status_code == 403
    await get_redis().flushall()
    admin = await make_user(client, Role.ADMIN)
    r = await _upload_stamp(client, admin)
    assert r.status_code == 200 and r.json()["stamp_uploaded"] is True, r.text
    assert (
        (await client.get(f"{REP}/settings/stamp", headers=p.pm.headers))
        .json()["data_url"]
        .startswith("data:image/png;base64,")
    )

    preview = await client.get(
        f"{REP}/projects/{p.pid}/report/preview", params={"fmt": "json"}, headers=p.pm.headers
    )
    body = preview.json()
    assert "price" not in preview.text.lower() and "rate" not in body
    assert len(body["delivered"]) == len(done) and len(body["exclusions"]) == 1
    sec = next(x for x in body["lenses"] if x["key"] == "security")
    assert sec["after"] == "71.2" and sec["before"] is not None and body["rescan_ref"]
    html = await client.get(f"{REP}/projects/{p.pid}/report/preview", headers=p.pm.headers)
    assert html.status_code == 200 and "Completion report" in html.text

    r = await client.post(f"{REP}/projects/{p.pid}/reports", headers={**p.pm.headers, **idem()})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["number"] == 1
    pdf = await client.get(f"{REP}/reports/{rep['id']}/pdf", headers=p.pm.headers)
    assert pdf.content.startswith(b"%PDF") and pdf.headers["x-content-sha256"] == rep["pdf_sha256"]

    # nobody issues a certificate before the customer and the Director signed off the stage
    assert (
        await client.post(
            f"{REP}/projects/{p.pid}/certificates", headers={**p.pm.headers, **idem()}
        )
    ).status_code == 403
    r = await client.post(
        f"{REP}/projects/{p.pid}/certificates", headers={**director.headers, **idem()}
    )
    assert r.status_code == 409 and r.json()["code"] == "not_ready"
    assert {m for m in r.json()["missing"] if "customer" in m or "Director" in m}

    await _completion_signoff(client, p, director)
    cond = await _conditions(client, p.pm, p.pid)
    assert all(c["met"] for c in cond.values()), cond

    r = await client.post(
        f"{REP}/projects/{p.pid}/certificates", headers={**director.headers, **idem()}
    )
    assert r.status_code == 201, r.text
    cert = r.json()
    assert re.fullmatch(r"IITPL-\d{4}-\d{4}", cert["number"]) and cert["status"] == "valid"
    r = await client.post(
        f"{REP}/projects/{p.pid}/certificates", headers={**director.headers, **idem()}
    )
    assert r.status_code == 409 and r.json()["code"] == "already_issued"
    pdf = await client.get(f"{REP}/certificates/{cert['id']}/pdf", headers=p.pm.headers)
    assert pdf.content.startswith(b"%PDF")

    # anyone with the QR code can check it; nothing sensitive is shown
    pub = await client.get(f"{API}/public/certificates/{cert['number']}")
    assert pub.status_code == 200, pub.text
    v = pub.json()
    assert v["status"] == "valid" and v["intact"] is True
    assert 0 < len(v["scope"]) <= len(done) and len(v["exclusions"]) == 1
    assert "price" not in pub.text.lower() and "meera@" not in pub.text
    assert (await client.get(f"{API}/public/certificates/IITPL-0000-9999")).status_code == 404

    # the signed payload cannot change, and a changed copy no longer verifies
    async with get_sessionmaker()() as s:
        row = await s.scalar(select(Certificate).where(Certificate.number == cert["number"]))
        assert row is not None and signature_ok(row)
        row.payload = {**row.payload, "customer": "Someone else"}
        assert not signature_ok(row)
        await s.rollback()
    with pytest.raises(DBAPIError):
        async with get_sessionmaker()() as s:
            await s.execute(
                text("UPDATE certificates SET payload_sha256 = 'x' WHERE id = :i"),
                {"i": cert["id"]},
            )
            await s.commit()

    r = await client.post(
        f"{REP}/certificates/{cert['id']}/revoke",
        json={"reason": "Issued against the wrong purchase order"},
        headers=director.headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "revoked", r.text
    v = (await client.get(f"{API}/public/certificates/{cert['number']}")).json()
    assert v["status"] == "revoked" and v["revoked_on"] and v["intact"] is True
    r = await client.post(
        f"{REP}/certificates/{cert['id']}/revoke",
        json={"reason": "Revoked a second time"},
        headers=director.headers,
    )
    assert r.status_code == 409
    with pytest.raises(DBAPIError):  # not even straight in the database
        async with get_sessionmaker()() as s:
            await s.execute(
                text("UPDATE certificates SET status = 'valid' WHERE id = :i"), {"i": cert["id"]}
            )
            await s.commit()


async def test_deviation_waivers_rejections_and_settings(client: Any) -> None:
    async with get_sessionmaker()() as s:
        await seed_verification(s)
    p, _both, runs = await field_ready(client)
    director = p.c.director
    r = await client.put(
        f"{API}/verification/policy",
        json={"certificate_blocking": ["critical", "major"]},
        headers=director.headers,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"{API}/verification/deviations",
        json={
            "run_id": runs[0]["id"],
            "label": "Spare uplink not cabled",
            "severity": "major",
            "note": "Second uplink port left empty",
        },
        headers=p.lead.headers,
    )
    assert r.status_code == 201, r.text
    dev = r.json()
    cond = await _conditions(client, p.pm, p.pid)
    assert not cond["deviations"]["met"] and "Spare uplink" in cond["deviations"]["detail"]

    # the Director turns one request down; the requester cannot decide their own
    r = await client.post(
        f"{REP}/projects/{p.pid}/waivers",
        json={
            "scope": "deviation",
            "target_id": dev["id"],
            "kind": "not_applicable",
            "reason": "The customer has no second uplink",
        },
        headers=p.pm.headers,
    )
    assert r.status_code == 201, r.text
    first = r.json()
    assert "Spare uplink" in first["target_label"] and "(major)" in first["target_label"]
    assert not (await _conditions(client, p.pm, p.pid))["waivers"]["met"]
    r = await client.post(
        f"{REP}/waivers/{first['id']}/decision", json={"decision": "approve"}, headers=p.pm.headers
    )
    assert r.status_code == 403
    r = await client.post(
        f"{REP}/waivers/{first['id']}/decision",
        json={"decision": "reject", "note": "Cable it, the port is there"},
        headers=director.headers,
    )
    assert r.json()["status"] == "rejected"
    r = await client.post(
        f"{REP}/waivers/{first['id']}/decision",
        json={"decision": "approve"},
        headers=director.headers,
    )
    assert r.status_code == 409

    # a second request is approved and acknowledged; the deviation is waived, not open
    await _waive(client, p, director, "deviation", dev["id"])
    devs = (
        await client.get(f"{API}/verification/projects/{p.pid}/deviations", headers=p.lead.headers)
    ).json()
    assert next(d for d in devs if d["id"] == dev["id"])["status"] == "waived"
    cond = await _conditions(client, p.pm, p.pid)
    assert cond["deviations"]["met"] and cond["waivers"]["met"]
    r = await client.post(
        f"{REP}/projects/{p.pid}/waivers",
        json={
            "scope": "deviation",
            "target_id": dev["id"],
            "kind": "not_applicable",
            "reason": "Waived already, asking again",
        },
        headers=p.pm.headers,
    )
    assert r.status_code == 409

    # bad links say so without telling anything
    assert (await client.get(f"{API}/public/waivers/{'x' * 40}")).status_code == 404
    assert (await client.get(f"{API}/public/waivers/short")).status_code == 404

    # certificate settings: the Director words it; a stamp must be an image
    r = await client.put(
        f"{REP}/settings/wording",
        json={"wording": "This certifies the listed work was delivered and verified by ITCraft."},
        headers=director.headers,
    )
    assert r.status_code == 200 and r.json()["wording"].startswith("This certifies the listed")
    assert (
        await client.put(
            f"{REP}/settings/wording",
            json={"wording": "Changed by someone who may not"},
            headers=p.pm.headers,
        )
    ).status_code == 403
    r = await client.post(
        f"{REP}/settings/stamp",
        files={"file": ("stamp.txt", b"not an image at all", "text/plain")},
        headers=director.headers,
    )
    assert r.status_code in (415, 422), r.text
    settings = (await client.get(f"{REP}/settings", headers=p.pm.headers)).json()
    assert settings["stamp_uploaded"] is False
