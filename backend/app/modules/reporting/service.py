"""Completion report, waivers and the "Certified by IITPL" certificate (phase 10, ADR 0019).

Release conditions, enforced here and nowhere else, with no override:
  1. every task is closed, or excluded by an acknowledged waiver;
  2. no open deviation of a certificate-blocking severity (policy; critical always);
  3. no waiver still waiting for the Director or the customer;
  4. the after-work PrismSuite rescan is approved;
  5. the IITPL stamp is uploaded;
  6. the completion report is locked;
  7. the customer acknowledged the completion stage;
  8. a Director approved the completion stage (the final check).
1 to 3 let the field work summary be locked; 1 to 5 let the report be locked; all 8 let a
Director issue the certificate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.sequences import next_value
from app.core.timeutil import financial_year_code, format_long_date, to_ist, today_ist, utcnow
from app.modules.audit_log.contracts import AuditContext, record
from app.modules.customers.contracts import (
    Stage,
    artifact_locked_event,
    get_project_ref,
    get_sign_off_contacts,
    get_stage_signoff,
)
from app.modules.fieldops.contracts import list_run_refs
from app.modules.files.contracts import read_file_system, store_upload
from app.modules.identity.contracts import (
    P,
    Principal,
    Role,
    audit_context,
    ensure_different_people,
    get_user_summary,
)
from app.modules.notifications.contracts import deliver_now, queue_email
from app.modules.prismsuite.contracts import get_approved_audit
from app.modules.reporting import storage
from app.modules.reporting.content import build_content
from app.modules.reporting.models import (
    WAIVER_KINDS,
    Certificate,
    CompletionReport,
    ReportSetting,
    Waiver,
)
from app.modules.verification.contracts import project_deviations, severity_policy, waive_deviation

ACK_DAYS = 14
DEFAULT_WORDING = (
    "This certifies that International Infocom Technologies Pvt Ltd (IITPL) has implemented all "
    "of the IT infrastructure work listed below, in full and to the agreed target configuration. "
    "Every item was checked against that configuration, verified, and accepted by the customer."
)
_UNIT = re.compile(r":\s*unit \d+ of \d+$")


def certificate_scope(delivered: list[dict[str, Any]]) -> list[str]:
    """The certificate's list of work: one line per kind of work, with a device count when the
    same work was done on several devices. The completion report keeps the task by task list."""
    groups: dict[str, list[str | None]] = {}
    for d in delivered:
        title, device = str(d["title"]), d.get("device")
        if device and title.endswith(f": {device}"):
            title = title[: -len(f": {device}")]
        title = _UNIT.sub("", title).strip()
        groups.setdefault(title, []).append(device)
    out = []
    for title, devices in groups.items():
        if len(devices) > 1:
            out.append(f"{title}, {len(devices)} devices")
        else:
            out.append(f"{title} ({devices[0]})" if devices[0] else title)
    return out


# ------------------------------------------------------------------ settings


async def cert_settings(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(ReportSetting, "certificate")
    base = {"wording": DEFAULT_WORDING, "stamp_file_id": None, "stamp_updated_at": None}
    return {**base, **(dict(row.value) if row else {})}


async def _save_settings(
    session: AsyncSession, principal: Principal, value: dict[str, Any]
) -> None:
    row = await session.get(ReportSetting, "certificate")
    if row is None:
        session.add(ReportSetting(key="certificate", value=value, updated_by=principal.user_id))
    else:
        row.value, row.updated_by, row.updated_at = value, principal.user_id, utcnow()


async def set_wording(session: AsyncSession, principal: Principal, wording: str) -> dict[str, Any]:
    principal.require(P.CERT_SETTINGS)
    cur = await cert_settings(session)
    new = {**cur, "wording": wording.strip()}
    await _save_settings(session, principal, new)
    await record(
        session,
        audit_context(principal),
        action="set_certificate_wording",
        entity_type="report_setting",
        entity_id="certificate",
        before={"wording": cur["wording"]},
        after={"wording": new["wording"]},
    )
    await session.commit()
    return new


async def upload_stamp(
    session: AsyncSession,
    principal: Principal,
    *,
    data: bytes,
    filename: str,
    client_ip: str | None,
) -> dict[str, Any]:
    """The IITPL stamp image (PNG or JPEG) printed on every certificate."""
    principal.require(P.CERT_SETTINGS)
    ref = await store_upload(
        session,
        principal,
        data=data,
        filename=filename,
        purpose="document",
        project_id=None,
        client_ip=client_ip,
    )
    if ref.kind not in ("png", "jpeg"):
        raise ValidationFailed("The stamp must be a PNG or JPEG image.", code="stamp_not_image")
    cur = await cert_settings(session)
    new = {**cur, "stamp_file_id": str(ref.id), "stamp_updated_at": utcnow().isoformat()}
    await _save_settings(session, principal, new)
    await record(
        session,
        audit_context(principal),
        action="upload_certificate_stamp",
        entity_type="report_setting",
        entity_id="certificate",
        after={"file": ref.original_name, "sha256": ref.sha256},
        only_changes=False,
    )
    await session.commit()
    return new


async def stamp_data_url(session: AsyncSession) -> str | None:
    s = await cert_settings(session)
    if not s.get("stamp_file_id"):
        return None
    ref, data = await read_file_system(session, uuid.UUID(s["stamp_file_id"]))
    mime = "image/png" if ref.kind == "png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


# ------------------------------------------------------------------ waivers


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}{'*' * max(len(name) - 1, 2)}@{domain}"


async def list_waivers(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[Waiver]:
    principal.require(P.REPORT_READ)
    await get_project_ref(session, principal, project_id)
    return list(
        await session.scalars(
            select(Waiver).where(Waiver.project_id == project_id).order_by(Waiver.created_at)
        )
    )


async def request_waiver(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    scope: str,
    target_id: uuid.UUID,
    kind: str,
    reason: str,
) -> Waiver:
    principal.require(P.REPORT_WRITE)
    await get_project_ref(session, principal, project_id)
    if kind not in WAIVER_KINDS:
        raise ValidationFailed("Kind must be not_applicable or deferred_by_customer.")
    if scope == "task":
        run = next(
            (r for r in await list_run_refs(session, principal, project_id) if r.id == target_id),
            None,
        )
        if run is None:
            raise NotFound("Task not found in this project.")
        if run.state == "closed":
            raise Conflict(
                "This task is already closed; it needs no waiver.", code="already_closed"
            )
        label = f"{run.task_ref} {run.title}"
    elif scope == "deviation":
        dev = next(
            (
                d
                for d in await project_deviations(session, principal, project_id)
                if d.id == target_id
            ),
            None,
        )
        if dev is None:
            raise NotFound("Deviation not found in this project.")
        if dev.status != "open":
            raise Conflict("Only an open deviation can be waived.", code="bad_state")
        label = f"{dev.task_ref} {dev.label} ({dev.severity})"
    else:
        raise ValidationFailed("Scope must be task or deviation.")
    active = await session.scalar(
        select(Waiver.id).where(
            Waiver.target_id == target_id,
            Waiver.status.in_(("requested", "approved", "acknowledged")),
        )
    )
    if active:
        raise Conflict("There is already a waiver for this.", code="already_waived")
    w = Waiver(
        project_id=project_id,
        scope=scope,
        target_id=target_id,
        target_label=label[:300],
        kind=kind,
        reason=reason,
        requested_by=principal.user_id,
    )
    session.add(w)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="request_waiver",
        entity_type="waiver",
        entity_id=w.id,
        after={"what": label, "kind": kind, "reason": reason},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(w)
    return w


async def decide_waiver(
    session: AsyncSession,
    principal: Principal,
    waiver_id: uuid.UUID,
    *,
    approve: bool,
    note: str | None,
) -> Waiver:
    """The Director approves (the customer is then asked to acknowledge) or rejects."""
    principal.require(P.WAIVER_APPROVE)
    w = await session.get(Waiver, waiver_id, with_for_update=True)
    if w is None:
        raise NotFound("Waiver not found.")
    project = await get_project_ref(session, principal, w.project_id)
    if w.status != "requested":
        raise Conflict("This waiver was already decided.", code="bad_state")
    ensure_different_people(w.requested_by, principal.user_id, "waiver request")
    w.decided_by, w.decided_at, w.decision_note = principal.user_id, utcnow(), note
    ids: list[uuid.UUID] = []
    if not approve:
        w.status = "rejected"
    else:
        contacts = await get_sign_off_contacts(session, principal, w.project_id)
        if not contacts:
            raise Conflict(
                "The customer has no sign-off contact with an email address.",
                code="customer_contact_missing",
            )
        c = contacts[0]
        token = secrets.token_urlsafe(32)
        w.status, w.contact_id, w.sent_to = "approved", c.id, _mask(c.email)
        w.ack_token_hash, w.ack_expires_at = _hash(token), utcnow() + timedelta(days=ACK_DAYS)
        director = await get_user_summary(session, principal.user_id)
        n = queue_email(
            session,
            to_address=c.email,
            template="waiver_ack",
            context={
                "name": c.full_name,
                "project": project.name,
                "what": w.target_label,
                "kind": w.kind.replace("_", " "),
                "reason": w.reason,
                "director": director.full_name if director else "the Director",
                "link": f"{get_settings().public_base_url}/ack/waiver/{token}",
                "days": ACK_DAYS,
            },
            related=("waiver", str(w.id)),
        )
        ids.append(n.id)
    await record(
        session,
        audit_context(principal),
        action="approve_waiver" if approve else "reject_waiver",
        entity_type="waiver",
        entity_id=w.id,
        after={"status": w.status, "note": note},
        only_changes=False,
    )
    await session.commit()
    await deliver_now(get_sessionmaker(), ids)
    await session.refresh(w)
    return w


async def _waiver_by_token(session: AsyncSession, token: str, *, lock: bool = False) -> Waiver:
    stmt = select(Waiver).where(Waiver.ack_token_hash == _hash(token))
    if lock:
        stmt = stmt.with_for_update()
    w = await session.scalar(stmt)
    if w is None or w.ack_expires_at is None or w.ack_expires_at <= utcnow():
        raise NotFound(
            "This link is not valid or has expired. Ask ITCraft for a new one.",
            code="ack_link_invalid",
        )
    return w


async def view_waiver(session: AsyncSession, token: str) -> dict[str, Any]:
    from app.modules.identity.contracts import system_principal

    w = await _waiver_by_token(session, token)
    reader = system_principal("waiver-link", frozenset({P.PROJECT_READ, P.PROJECT_READ_ALL}))
    project = await get_project_ref(session, reader, w.project_id)
    director = await get_user_summary(session, w.decided_by) if w.decided_by else None
    return {
        "project_name": project.name,
        "what": w.target_label,
        "kind": w.kind.replace("_", " "),
        "reason": w.reason,
        "approved_by": director.full_name if director else None,
        "expires_at": w.ack_expires_at,
        "already_acknowledged": w.status == "acknowledged",
    }


async def acknowledge_waiver(
    session: AsyncSession, token: str, *, name: str, ip: str | None
) -> None:
    w = await _waiver_by_token(session, token, lock=True)
    if w.status == "acknowledged":
        return
    if w.status != "approved":
        raise Conflict("This waiver is not waiting for your acknowledgement.", code="bad_state")
    w.status, w.acknowledged_at, w.acknowledged_name, w.acknowledged_ip = (
        "acknowledged",
        utcnow(),
        name,
        ip,
    )
    if w.scope == "deviation" and w.decided_by:
        await waive_deviation(session, w.target_id, waiver=f"waiver {w.id}", by=w.decided_by)
    await record(
        session,
        AuditContext.system("customer"),
        action="acknowledge_waiver",
        entity_type="waiver",
        entity_id=w.id,
        after={"name": name},
        only_changes=False,
    )
    await session.commit()


# ------------------------------------------------------------------ release conditions


async def conditions(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    principal.require(P.REPORT_READ)
    project = await get_project_ref(session, principal, project_id)
    runs = (
        await list_run_refs(session, principal, project_id) if principal.has(P.FIELD_READ) else []
    )
    waivers = list(await session.scalars(select(Waiver).where(Waiver.project_id == project_id)))
    waived = {w.target_id for w in waivers if w.status == "acknowledged"}
    open_tasks = [r.task_ref for r in runs if r.state != "closed" and r.id not in waived]
    policy = await severity_policy(session)
    blocking = set(policy.get("certificate_blocking", ["critical"])) | {"critical"}
    devs = await project_deviations(session, principal, project_id)
    open_blocking = [
        f"{d.task_ref} {d.label}" for d in devs if d.status == "open" and d.severity in blocking
    ]
    pending = [w.target_label for w in waivers if w.status in ("requested", "approved")]
    try:
        rescan = await get_approved_audit(session, principal, project_id, "rescan")
        rescan_ok, rescan_detail = (
            True,
            f"Approved rescan {rescan.snapshot.header.report_reference or ''}".strip(),
        )
    except NotFound:
        rescan_ok, rescan_detail = (
            False,
            "Upload the after-work PrismSuite report as a rescan and approve it.",
        )
    stamp = (await cert_settings(session)).get("stamp_file_id")
    report = await _latest_report(session, project_id)
    signoff = await get_stage_signoff(session, principal, project_id, Stage.COMPLETION)
    director_ok = signoff.approved and Role.DIRECTOR.value in signoff.decided_by_roles
    ack_detail = "Waiting for the customer's acknowledgement"
    if signoff.customer_ack_at:
        ack_on = format_long_date(to_ist(signoff.customer_ack_at).date())
        ack_detail = f"{signoff.customer_ack_name}, {ack_on}"
    return [
        {
            "key": "work",
            "label": "Every task is closed or excluded by an acknowledged waiver",
            "met": bool(runs) and not open_tasks,
            "detail": "No field work yet."
            if not runs
            else (f"Still open: {', '.join(open_tasks)}" if open_tasks else f"{len(runs)} tasks"),
        },
        {
            "key": "deviations",
            "label": f"No open {' or '.join(sorted(blocking))} deviation",
            "met": not open_blocking,
            "detail": "; ".join(open_blocking) or "None open",
        },
        {
            "key": "waivers",
            "label": "Every waiver is approved by the Director and acknowledged by the customer",
            "met": not pending,
            "detail": "; ".join(pending) or "None waiting",
        },
        {
            "key": "rescan",
            "label": "The after-work PrismSuite rescan is approved",
            "met": rescan_ok,
            "detail": rescan_detail,
        },
        {
            "key": "stamp",
            "label": "The IITPL stamp is uploaded",
            "met": bool(stamp),
            "detail": "Uploaded"
            if stamp
            else "A Director or Admin uploads it in certificate settings.",
        },
        {
            "key": "report",
            "label": "The completion report is locked",
            "met": report is not None,
            "detail": f"Report {report.number}, {format_long_date(to_ist(report.locked_at).date())}"
            if report
            else "Not locked yet",
        },
        {
            "key": "customer",
            "label": "The customer acknowledged the completion stage",
            "met": signoff.customer_ack_at is not None,
            "detail": ack_detail,
        },
        {
            "key": "director",
            "label": "A Director approved the completion stage (final check)",
            "met": director_ok,
            "detail": f"{signoff.decided_by_name}" if director_ok else "Waiting for the Director",
        },
        {
            "key": "stage",
            "label": "The project is at the completion stage",
            "met": project.current_stage == Stage.COMPLETION,
            "detail": project.current_stage.value.replace("_", " "),
        },
    ]


def _met(conds: list[dict[str, Any]], keys: tuple[str, ...]) -> list[str]:
    return [c["label"] for c in conds if c["key"] in keys and not c["met"]]


async def _latest_report(session: AsyncSession, project_id: uuid.UUID) -> CompletionReport | None:
    return await session.scalar(
        select(CompletionReport)
        .where(CompletionReport.project_id == project_id)
        .order_by(CompletionReport.number.desc())
        .limit(1)
    )


async def lock_field_summary(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> dict[str, Any]:
    """Field work is finished: lock its summary so the field work stage can be submitted."""
    principal.require(P.REPORT_WRITE)
    project = await get_project_ref(session, principal, project_id)
    if project.current_stage != Stage.FIELD_WORK:
        raise Conflict("The project is not at the field work stage.", code="wrong_stage")
    missing = _met(
        await conditions(session, principal, project_id), ("work", "deviations", "waivers")
    )
    if missing:
        raise Conflict(
            "Field work is not finished: " + "; ".join(missing) + ".",
            code="not_ready",
            extra={"missing": missing},
        )
    artifact = str(uuid.uuid4())
    outbox.publish(
        session,
        artifact_locked_event(
            project_id=project_id,
            stage=Stage.FIELD_WORK,
            artifact_type="field_work_summary",
            artifact_id=artifact,
            artifact_version=1,
            title="Field work summary",
            locked_by=principal.user_id,
        ),
    )
    await record(
        session,
        audit_context(principal),
        action="lock_field_summary",
        entity_type="project",
        entity_id=project_id,
        after={"artifact": artifact},
        only_changes=False,
    )
    await session.commit()
    return {"artifact_id": artifact}


# ------------------------------------------------------------------ the report


async def preview(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> dict[str, Any]:
    principal.require(P.REPORT_READ)
    waivers = list(await session.scalars(select(Waiver).where(Waiver.project_id == project_id)))
    return await build_content(session, principal, project_id, waivers)


async def lock_report(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> CompletionReport:
    from app.modules.reporting import render

    principal.require(P.REPORT_WRITE)
    project = await get_project_ref(session, principal, project_id)
    if project.current_stage != Stage.COMPLETION:
        raise Conflict("The project is not at the completion stage yet.", code="wrong_stage")
    missing = _met(
        await conditions(session, principal, project_id),
        ("work", "deviations", "waivers", "rescan", "stamp"),
    )
    if missing:
        raise Conflict(
            "The report cannot be locked yet: " + "; ".join(missing) + ".",
            code="not_ready",
            extra={"missing": missing},
        )
    content = await preview(session, principal, project_id)
    number = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(CompletionReport.number), 0)).where(
                    CompletionReport.project_id == project_id
                )
            )
            or 0
        )
        + 1
    )
    content["report_number"] = number
    doc = render.render_report_pdf(await render.report_context(session, content))
    key = f"reports/{project_id.hex}/completion-{number}.pdf"
    await storage.put_pdf(key, doc.pdf)
    rep = CompletionReport(
        project_id=project_id,
        number=number,
        content=content,
        pdf_key=key,
        pdf_sha256=doc.sha256,
        locked_by=principal.user_id,
    )
    session.add(rep)
    await session.flush()
    outbox.publish(
        session,
        artifact_locked_event(
            project_id=project_id,
            stage=Stage.COMPLETION,
            artifact_type="completion_report",
            artifact_id=str(rep.id),
            artifact_version=number,
            title=f"Completion report {number}",
            locked_by=principal.user_id,
        ),
    )
    await record(
        session,
        audit_context(principal),
        action="lock_completion_report",
        entity_type="project",
        entity_id=project_id,
        after={"number": number, "sha256": doc.sha256},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(rep)
    return rep


async def report_pdf(
    session: AsyncSession, principal: Principal, report_id: uuid.UUID
) -> tuple[CompletionReport, bytes]:
    principal.require(P.REPORT_READ)
    rep = await session.get(CompletionReport, report_id)
    if rep is None:
        raise NotFound("Report not found.")
    await get_project_ref(session, principal, rep.project_id)
    return rep, await storage.get_pdf(rep.pdf_key)


async def list_reports(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[CompletionReport]:
    principal.require(P.REPORT_READ)
    await get_project_ref(session, principal, project_id)
    return list(
        await session.scalars(
            select(CompletionReport)
            .where(CompletionReport.project_id == project_id)
            .order_by(CompletionReport.number)
        )
    )


# ------------------------------------------------------------------ the certificate


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sign(digest: str, key: str) -> str:
    k = hashlib.sha256(b"p1-certificate:" + key.encode()).digest()
    return hmac.new(k, digest.encode(), hashlib.sha256).hexdigest()


def signature_ok(cert: Certificate) -> bool:
    digest = hashlib.sha256(_canonical(cert.payload)).hexdigest()
    if digest != cert.payload_sha256:
        return False
    return any(
        hmac.compare_digest(_sign(digest, k), cert.signature) for k in get_settings().jwt_keys()
    )


async def issue_certificate(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> Certificate:
    """Only a Director, only when every release condition holds. There is no override."""
    from app.modules.reporting import render

    principal.require(P.CERT_ISSUE)
    me = await get_user_summary(session, principal.user_id)
    if me is None or Role.DIRECTOR not in me.roles:
        raise Forbidden("Only a Director signs the certificate.", code="director_only")
    project = await get_project_ref(session, principal, project_id)
    missing = _met(
        await conditions(session, principal, project_id),
        (
            "work",
            "deviations",
            "waivers",
            "rescan",
            "stamp",
            "report",
            "customer",
            "director",
            "stage",
        ),
    )
    if missing:
        raise Conflict(
            "The certificate cannot be issued: " + "; ".join(missing) + ".",
            code="not_ready",
            extra={"missing": missing},
        )
    if await session.scalar(
        select(Certificate.id).where(
            Certificate.project_id == project_id, Certificate.status == "valid"
        )
    ):
        raise Conflict(
            "This project already has a valid certificate. Revoke it first to issue a new one.",
            code="already_issued",
        )
    rep = await _latest_report(session, project_id)
    assert rep is not None  # condition "report" holds
    c = rep.content
    fy = financial_year_code(today_ist())
    number = f"IITPL-{fy}-{await next_value(session, f'certificate:{fy}'):04d}"
    payload = {
        "number": number,
        "customer": c["customer"]["legal_name"] or c["customer"]["name"],
        "project": project.name,
        "project_code": project.code,
        "quote_ref": c.get("quote_ref"),
        "po_number": c.get("po_number"),
        "scope": certificate_scope(c["delivered"]),
        "exclusions": [f"{x['what']}: {x['kind']}" for x in c["exclusions"]],
        "work_started": c.get("work_started"),
        "work_finished": c.get("work_finished"),
        "verifiers": c.get("verifiers", []),
        "director": me.full_name,
        "issued_on": format_long_date(today_ist()),
        "report_number": rep.number,
        "report_sha256": rep.pdf_sha256,
        "wording": (await cert_settings(session))["wording"],
    }
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    signature = _sign(digest, get_settings().jwt_keys()[0])
    verify_url = f"{get_settings().public_base_url}/verify/{number}"
    stamp = await stamp_data_url(session)
    doc = render.render_certificate_pdf(
        await render.certificate_context(session, payload, digest, verify_url, stamp)
    )
    key = f"certificates/{number}.pdf"
    await storage.put_pdf(key, doc.pdf)
    cert = Certificate(
        number=number,
        project_id=project_id,
        report_id=rep.id,
        payload=payload,
        payload_sha256=digest,
        signature=signature,
        pdf_key=key,
        pdf_sha256=doc.sha256,
        issued_by=principal.user_id,
    )
    session.add(cert)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="issue_certificate",
        entity_type="certificate",
        entity_id=cert.id,
        after={"number": number, "sha256": digest},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(cert)
    return cert


async def revoke_certificate(
    session: AsyncSession, principal: Principal, cert_id: uuid.UUID, *, reason: str
) -> Certificate:
    principal.require(P.CERT_ISSUE)
    cert = await session.get(Certificate, cert_id, with_for_update=True)
    if cert is None:
        raise NotFound("Certificate not found.")
    await get_project_ref(session, principal, cert.project_id)
    if cert.status != "valid":
        raise Conflict("This certificate is already revoked.", code="bad_state")
    cert.status, cert.revoked_at, cert.revoked_by, cert.revoke_reason = (
        "revoked",
        utcnow(),
        principal.user_id,
        reason,
    )
    await record(
        session,
        audit_context(principal),
        action="revoke_certificate",
        entity_type="certificate",
        entity_id=cert.id,
        after={"reason": reason},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(cert)
    return cert


async def list_certificates(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[Certificate]:
    principal.require(P.REPORT_READ)
    await get_project_ref(session, principal, project_id)
    return list(
        await session.scalars(
            select(Certificate)
            .where(Certificate.project_id == project_id)
            .order_by(Certificate.issued_at)
        )
    )


async def certificate_pdf(
    session: AsyncSession, principal: Principal, cert_id: uuid.UUID
) -> tuple[Certificate, bytes]:
    principal.require(P.REPORT_READ)
    cert = await session.get(Certificate, cert_id)
    if cert is None:
        raise NotFound("Certificate not found.")
    await get_project_ref(session, principal, cert.project_id)
    return cert, await storage.get_pdf(cert.pdf_key)


async def public_certificate(session: AsyncSession, number: str) -> dict[str, Any]:
    """What anyone scanning the QR code may see: no prices, no contacts, no internal notes."""
    cert = await session.scalar(select(Certificate).where(Certificate.number == number))
    if cert is None:
        raise NotFound("No certificate has this number.", code="certificate_unknown")
    p = cert.payload
    return {
        "number": cert.number,
        "status": cert.status,
        "intact": signature_ok(cert),
        "customer": p["customer"],
        "project": p["project"],
        "issued_on": p["issued_on"],
        "director": p["director"],
        "scope": p["scope"],
        "exclusions": p["exclusions"],
        "work_finished": p.get("work_finished"),
        "fingerprint": cert.payload_sha256[:16],
        "revoked_on": format_long_date(to_ist(cert.revoked_at).date()) if cert.revoked_at else None,
    }
