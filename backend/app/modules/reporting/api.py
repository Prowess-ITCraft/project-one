from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.core.ratelimit import Limit, check
from app.modules.files.contracts import read_limited
from app.modules.identity.contracts import P, Principal, require
from app.modules.reporting import render, service

router = APIRouter(prefix="/reporting", tags=["reporting"])
public_certificates = APIRouter(prefix="/public/certificates", tags=["public"])
public_waivers = APIRouter(prefix="/public/waivers", tags=["public"])
Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]
Reader = Annotated[Principal, Depends(require(P.REPORT_READ))]
Writer = Annotated[Principal, Depends(require(P.REPORT_WRITE))]
Approver = Annotated[Principal, Depends(require(P.WAIVER_APPROVE))]
Issuer = Annotated[Principal, Depends(require(P.CERT_ISSUE))]
Settings = Annotated[Principal, Depends(require(P.CERT_SETTINGS))]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WaiverIn(_In):
    scope: Literal["task", "deviation"]
    target_id: uuid.UUID
    kind: Literal["not_applicable", "deferred_by_customer"]
    reason: Text


class DecisionIn(_In):
    decision: Literal["approve", "reject"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class WaiverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    target_id: uuid.UUID
    target_label: str
    kind: str
    reason: str
    status: str
    requested_by: uuid.UUID
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    sent_to: str | None
    acknowledged_at: datetime | None
    acknowledged_name: str | None
    created_at: datetime


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    pdf_sha256: str
    locked_by: uuid.UUID
    locked_at: datetime


class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    status: str
    issued_by: uuid.UUID
    issued_at: datetime
    payload_sha256: str
    pdf_sha256: str
    revoked_at: datetime | None
    revoke_reason: str | None


class RevokeIn(_In):
    reason: Text


class WordingIn(_In):
    wording: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=600)]


class AckIn(_In):
    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)
    ]
    accept: Literal[True]


def _pdf(data: bytes, name: str, digest: str) -> Response:
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-SHA256": digest,
        },
    )


# ------------------------------------------------------------------ project level


@router.get("/projects/{project_id}/conditions")
async def release_conditions(
    session: Session, principal: Reader, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every condition the certificate needs, met or not, with what is missing."""
    return await service.conditions(session, principal, project_id)


@router.get("/projects/{project_id}/waivers", response_model=list[WaiverOut])
async def waivers(session: Session, principal: Reader, project_id: uuid.UUID) -> list[WaiverOut]:
    return [
        WaiverOut.model_validate(w, from_attributes=True)
        for w in await service.list_waivers(session, principal, project_id)
    ]


@router.post(
    "/projects/{project_id}/waivers", response_model=WaiverOut, status_code=status.HTTP_201_CREATED
)
async def request_waiver(
    session: Session, principal: Writer, project_id: uuid.UUID, body: WaiverIn
) -> WaiverOut:
    """Ask the Director to excuse a task or an open deviation. The customer acknowledges it next."""
    w = await service.request_waiver(
        session,
        principal,
        project_id,
        scope=body.scope,
        target_id=body.target_id,
        kind=body.kind,
        reason=body.reason,
    )
    return WaiverOut.model_validate(w, from_attributes=True)


@router.post("/waivers/{waiver_id}/decision", response_model=WaiverOut)
async def decide_waiver(
    session: Session, principal: Approver, waiver_id: uuid.UUID, body: DecisionIn
) -> WaiverOut:
    w = await service.decide_waiver(
        session, principal, waiver_id, approve=body.decision == "approve", note=body.note
    )
    return WaiverOut.model_validate(w, from_attributes=True)


@router.post("/projects/{project_id}/field-summary")
async def lock_field_summary(
    session: Session, principal: Writer, project_id: uuid.UUID, guard: Idem
) -> Any:
    """Field work is finished: lock its summary so the field work stage can be submitted."""

    async def work() -> dict[str, Any]:
        return await service.lock_field_summary(session, principal, project_id)

    return await run_idempotent(guard, str(principal.user_id), 200, work)


@router.get("/projects/{project_id}/report/preview")
async def report_preview(
    session: Session,
    principal: Reader,
    project_id: uuid.UUID,
    fmt: Literal["html", "pdf", "json"] = "html",
) -> Any:
    """The completion report as it would be locked now."""
    content = await service.preview(session, principal, project_id)
    if fmt == "json":
        return content
    ctx = await render.report_context(session, content)
    if fmt == "html":
        return Response(
            content=render.render_report_html(ctx), media_type="text/html; charset=utf-8"
        )
    doc = render.render_report_pdf(ctx)
    return _pdf(doc.pdf, f"{content['project']['code']}-completion-preview.pdf", doc.sha256)


@router.get("/projects/{project_id}/reports", response_model=list[ReportOut])
async def reports(session: Session, principal: Reader, project_id: uuid.UUID) -> list[ReportOut]:
    return [
        ReportOut.model_validate(r, from_attributes=True)
        for r in await service.list_reports(session, principal, project_id)
    ]


@router.post(
    "/projects/{project_id}/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED
)
async def lock_report(
    session: Session, principal: Writer, project_id: uuid.UUID, guard: Idem
) -> Any:
    """Lock the completion report as the completion stage output. Needs every task closed or
    waived, no blocking deviation, the rescan approved and the stamp uploaded."""

    async def work() -> ReportOut:
        return ReportOut.model_validate(
            await service.lock_report(session, principal, project_id), from_attributes=True
        )

    return await run_idempotent(guard, str(principal.user_id), 201, work)


@router.get("/reports/{report_id}/pdf")
async def report_pdf(session: Session, principal: Reader, report_id: uuid.UUID) -> Response:
    rep, data = await service.report_pdf(session, principal, report_id)
    return _pdf(data, f"completion-report-{rep.number}.pdf", rep.pdf_sha256)


@router.get("/projects/{project_id}/certificates", response_model=list[CertificateOut])
async def certificates(
    session: Session, principal: Reader, project_id: uuid.UUID
) -> list[CertificateOut]:
    return [
        CertificateOut.model_validate(c, from_attributes=True)
        for c in await service.list_certificates(session, principal, project_id)
    ]


@router.post(
    "/projects/{project_id}/certificates",
    response_model=CertificateOut,
    status_code=status.HTTP_201_CREATED,
)
async def issue(session: Session, principal: Issuer, project_id: uuid.UUID, guard: Idem) -> Any:
    """Sign the "Certified by IITPL" certificate.

    Director only, every condition met, no override."""

    async def work() -> CertificateOut:
        return CertificateOut.model_validate(
            await service.issue_certificate(session, principal, project_id), from_attributes=True
        )

    return await run_idempotent(guard, str(principal.user_id), 201, work)


@router.post("/certificates/{certificate_id}/revoke", response_model=CertificateOut)
async def revoke(
    session: Session, principal: Issuer, certificate_id: uuid.UUID, body: RevokeIn
) -> CertificateOut:
    c = await service.revoke_certificate(session, principal, certificate_id, reason=body.reason)
    return CertificateOut.model_validate(c, from_attributes=True)


@router.get("/certificates/{certificate_id}/pdf")
async def certificate_pdf(
    session: Session, principal: Reader, certificate_id: uuid.UUID
) -> Response:
    c, data = await service.certificate_pdf(session, principal, certificate_id)
    return _pdf(data, f"{c.number}.pdf", c.pdf_sha256)


# ------------------------------------------------------------------ certificate settings


@router.get("/settings")
async def certificate_settings(session: Session, principal: Reader) -> dict[str, Any]:
    s = await service.cert_settings(session)
    return {
        "wording": s["wording"],
        "stamp_uploaded": bool(s.get("stamp_file_id")),
        "stamp_updated_at": s.get("stamp_updated_at"),
    }


@router.put("/settings/wording")
async def put_wording(session: Session, principal: Settings, body: WordingIn) -> dict[str, Any]:
    s = await service.set_wording(session, principal, body.wording)
    return {"wording": s["wording"], "stamp_uploaded": bool(s.get("stamp_file_id"))}


@router.post("/settings/stamp")
async def put_stamp(
    request: Request, session: Session, principal: Settings, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """The IITPL stamp image (PNG or JPEG) printed on every certificate."""
    data = await read_limited(file, 5 * 1024 * 1024)
    s = await service.upload_stamp(
        session,
        principal,
        data=data,
        filename=file.filename or "stamp.png",
        client_ip=request.state.client_ip,
    )
    return {
        "wording": s["wording"],
        "stamp_uploaded": True,
        "stamp_updated_at": s.get("stamp_updated_at"),
    }


@router.get("/settings/stamp")
async def get_stamp(session: Session, principal: Reader) -> dict[str, Any]:
    """The stamp as a data URL, for the settings preview."""
    url = await service.stamp_data_url(session)
    if url is None:
        raise NotFound("No stamp is uploaded yet.", code="no_stamp")
    return {"data_url": url}


# ------------------------------------------------------------------ public


async def _limit(request: Request) -> None:
    await check(f"ip:{request.state.client_ip}", Limit("public", 30, strict=True))


@public_certificates.get("/{number}")
async def verify_certificate(request: Request, session: Session, number: str) -> dict[str, Any]:
    """Anyone with the QR code: is this certificate genuine and still valid?

    No prices or contacts."""
    await _limit(request)
    if len(number) > 30:
        raise NotFound("No certificate has this number.", code="certificate_unknown")
    return await service.public_certificate(session, number)


@public_waivers.get("/{token}")
async def view_waiver(request: Request, session: Session, token: str) -> dict[str, Any]:
    await _limit(request)
    if not 20 <= len(token) <= 100:
        raise NotFound("This link is not valid or has expired.", code="ack_link_invalid")
    return await service.view_waiver(session, token)


@public_waivers.post("/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_waiver(
    request: Request, session: Session, token: str, body: AckIn
) -> Response:
    await _limit(request)
    if not 20 <= len(token) <= 100:
        raise NotFound("This link is not valid or has expired.", code="ack_link_invalid")
    await service.acknowledge_waiver(
        session, token, name=body.full_name, ip=request.state.client_ip
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


routers = [router, public_certificates, public_waivers]
