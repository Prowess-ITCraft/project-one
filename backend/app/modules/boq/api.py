from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.modules.boq import draft as d
from app.modules.boq import render, service
from app.modules.boq.generate import rank_category
from app.modules.boq.recommend import Context
from app.modules.boq.schemas import (
    BoqOut,
    CompareOut,
    EditRowOut,
    VersionRowOut,
    VersionViewOut,
)
from app.modules.customers.contracts import get_brief_ref
from app.modules.identity.contracts import P, Principal, require

router = APIRouter(prefix="/boq", tags=["boq"])
project_router = APIRouter(prefix="/projects/{project_id}/boq", tags=["boq"])
Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]
Reader = Annotated[Principal, Depends(require(P.BOQ_READ))]
Editor = Annotated[Principal, Depends(require(P.BOQ_EDIT))]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GenerateIn(_In):
    replace: bool = False


class EditIn(_In):
    draft_rev: int = Field(ge=1)
    reason: Reason
    ops: list[dict[str, Any]] = Field(min_length=1, max_length=60)


class AddItemIn(_In):
    draft_rev: int = Field(ge=1)
    reason: Reason
    item_code: str = Field(min_length=2, max_length=40)
    section_id: str
    qty: int = Field(default=1, ge=0, le=1_000_000)
    option_group: Annotated[str, StringConstraints(max_length=40)] | None = None


class RefreshIn(_In):
    draft_rev: int = Field(ge=1)
    reason: Reason = "Refreshed prices from the price book"


class DecisionIn(_In):
    approve: bool
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


class AcceptIn(_In):
    po_number: Annotated[str, StringConstraints(min_length=3, max_length=60)]
    po_date: date
    po_file_id: uuid.UUID | None = None
    selected_options: dict[str, str] = Field(default_factory=dict)
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None


class ReopenIn(_In):
    reason: Reason


class TemplateIn(_In):
    title: Annotated[str, StringConstraints(min_length=3, max_length=200)]
    lines: list[dict[str, Any]] = Field(min_length=1, max_length=30)
    active: bool = True
    version: int | None = Field(default=None, ge=1)


class CompanyIn(_In):
    data: dict[str, Any]
    version: int | None = Field(default=None, ge=1)


class WeightsIn(_In):
    weights: dict[str, float]


# ------------------------------------------------------------------ master data


@router.get("/company")
async def get_company(session: Session, _: Reader) -> dict[str, Any]:
    return await service.company(session)


@router.put("/company")
async def put_company(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.SETTINGS_EDIT))],
    body: CompanyIn,
) -> dict[str, Any]:
    """Letterhead, default terms, signature and quote prefix. Admin only."""
    return await service.save_company(session, principal, body.data, body.version)


@router.get("/weights/{segment}")
async def get_weights(
    session: Session, _: Reader, segment: Literal["default", "micro", "small", "medium", "large"]
) -> dict[str, float]:
    return await service.weights_for(session, segment)


@router.put("/weights/{segment}")
async def put_weights(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.SETTINGS_EDIT))],
    segment: Literal["default", "micro", "small", "medium", "large"],
    body: WeightsIn,
) -> dict[str, float]:
    return await service.save_weights(session, principal, segment, body.weights)


@router.get("/templates")
async def list_templates(session: Session, _: Reader) -> list[dict[str, Any]]:
    return [
        {
            "id": str(t.id),
            "gap_type": t.gap_type,
            "title": t.title,
            "lines": t.lines,
            "active": t.active,
            "revision": t.revision,
            "version": t.version,
        }
        for t in await service.list_templates(session)
    ]


@router.put("/templates/{gap_type}")
async def put_template(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.TEMPLATE_EDIT))],
    gap_type: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{2,59}$")],
    body: TemplateIn,
) -> dict[str, Any]:
    t = await service.save_template(
        session,
        principal,
        gap_type=gap_type,
        body={"title": body.title, "lines": body.lines},
        active=body.active,
        version=body.version,
    )
    return {
        "id": str(t.id),
        "gap_type": t.gap_type,
        "title": t.title,
        "lines": t.lines,
        "active": t.active,
        "revision": t.revision,
        "version": t.version,
    }


# ------------------------------------------------------------------ project BOQ


@project_router.post("/generate", status_code=status.HTTP_201_CREATED, response_model=BoqOut)
async def generate(
    session: Session, principal: Editor, project_id: uuid.UUID, body: GenerateIn
) -> dict[str, Any]:
    """Draft the BOQ from the locked gap register. Prices come from the price book only."""
    b = await service.generate(session, principal, project_id, replace=body.replace)
    return service.view(b, principal)


ESTIMATE_REF = "ESTIMATE, NOT APPROVED"


@project_router.get("/estimate")
async def estimate(
    session: Session,
    principal: Editor,
    project_id: uuid.UUID,
    fmt: Literal["json", "pdf", "xlsx"] = "json",
    kind: Literal["quotation", "summary"] = "quotation",
) -> Any:
    """A BOQ worked out straight from the PrismSuite report and the questionnaire, before the
    gates are approved. Saved nowhere; documents carry "ESTIMATE, NOT APPROVED" as their ref."""
    draft, report, gapset, basis = await service.estimate(session, principal, project_id)
    if fmt == "json":
        return service.estimate_view(draft, report, gapset, basis, principal)
    comp = await service.company(session)
    name = f"estimate-{kind}.{fmt}"
    if fmt == "xlsx":
        data = render.render_xlsx(draft, comp, quote_ref=ESTIMATE_REF, kind=kind)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        doc = render.render_pdf(render.render_html(draft, comp, quote_ref=ESTIMATE_REF, kind=kind))
        data, mime = doc.pdf, "application/pdf"
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@project_router.get("", response_model=BoqOut)
async def get_project_boq(
    session: Session, principal: Reader, project_id: uuid.UUID
) -> dict[str, Any]:
    return service.view(await service.for_project(session, principal, project_id), principal)


# ------------------------------------------------------------------ editing


@router.get("/{boq_id}", response_model=BoqOut)
async def get_boq(session: Session, principal: Reader, boq_id: uuid.UUID) -> dict[str, Any]:
    return service.view(await service._load(session, principal, boq_id), principal)


@router.post("/{boq_id}/edit", response_model=BoqOut)
async def edit(
    session: Session, principal: Editor, boq_id: uuid.UUID, body: EditIn
) -> dict[str, Any]:
    """Add, change, delete or move anything: lines, sections, groups, options, terms, settings.
    All operations apply together or not at all, and the reason is kept."""
    return service.view(
        await service.edit(
            session, principal, boq_id, draft_rev=body.draft_rev, reason=body.reason, ops=body.ops
        ),
        principal,
    )


@router.post("/{boq_id}/add-item", response_model=BoqOut)
async def add_item(
    session: Session, principal: Editor, boq_id: uuid.UUID, body: AddItemIn
) -> dict[str, Any]:
    b = await service.add_from_catalogue(
        session,
        principal,
        boq_id,
        draft_rev=body.draft_rev,
        reason=body.reason,
        item_code=body.item_code,
        section_id=body.section_id,
        qty=body.qty,
        option_group=body.option_group,
    )
    return service.view(b, principal)


@router.post("/{boq_id}/refresh-prices", response_model=BoqOut)
async def refresh_prices(
    session: Session, principal: Editor, boq_id: uuid.UUID, body: RefreshIn
) -> dict[str, Any]:
    """Pull the current price book price into lines that came from it. Hand-priced lines stay."""
    b, changes = await service.refresh_prices(
        session, principal, boq_id, draft_rev=body.draft_rev, reason=body.reason
    )
    return {**service.view(b, principal), "changes": changes}


@router.get("/{boq_id}/lines/{line_id}/history")
async def line_history(
    session: Session, principal: Reader, boq_id: uuid.UUID, line_id: str
) -> dict[str, Any]:
    """What past BOQs in the library say about this line. Advice only."""
    return await service.line_history(session, principal, boq_id, line_id)


@router.get("/{boq_id}/recommend")
async def recommend(
    session: Session,
    principal: Reader,
    boq_id: uuid.UUID,
    category: Annotated[str, Query(min_length=2, max_length=40)],
) -> dict[str, Any]:
    """Rank the catalogue for a category with reasons: use it to swap a product by hand."""
    b = await service._load(session, principal, boq_id)
    brief = await get_brief_ref(session, principal, b.project_id)
    users = (brief.users_12m or brief.users_now) if brief else None
    ctx = Context(
        users=users,
        preferred=brief.preferred_brands if brief else (),
        excluded=brief.excluded_brands if brief else (),
    )
    ranked, rejected = await rank_category(
        session,
        principal,
        category,
        ctx,
        await service.weights_for(session, brief.company_size if brief else None),
    )
    return {
        "category": category,
        "ranked": [
            {
                "item_id": str(r.candidate.item.id),
                "code": r.candidate.item.code,
                "name": r.candidate.item.name,
                "score": r.score,
                "criteria": r.criteria,
                "reasons": r.reasons,
                "price": str(r.candidate.price.selling)
                if r.candidate.price
                and r.candidate.price.usable
                and r.candidate.price.selling is not None
                else None,
            }
            for r in ranked
        ],
        "rejected": [
            {"code": x.item.code, "name": x.item.name, "reason": x.reason} for x in rejected
        ],
    }


@router.get("/{boq_id}/edits", response_model=list[EditRowOut])
async def edits(session: Session, principal: Reader, boq_id: uuid.UUID) -> list[dict[str, Any]]:
    return [
        {
            "at": e.at.isoformat(),
            "by": str(e.by),
            "action": e.action,
            "reason": e.reason,
            "detail": e.detail,
        }
        for e in await service.edit_log(session, principal, boq_id)
    ]


# ------------------------------------------------------------------ pricing review, issue, acceptance


@router.post("/{boq_id}/submit", response_model=BoqOut)
async def submit(session: Session, principal: Editor, boq_id: uuid.UUID) -> dict[str, Any]:
    """Send the BOQ for pricing review. Missing or expired prices must be fixed first."""
    return service.view(await service.submit_for_pricing(session, principal, boq_id), principal)


@router.post("/{boq_id}/pricing-decision", response_model=BoqOut)
async def pricing_decision(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.BOQ_APPROVE_PRICING))],
    boq_id: uuid.UUID,
    body: DecisionIn,
) -> dict[str, Any]:
    """Approve or send back the pricing. Not the person who drafted or edited it."""
    return service.view(
        await service.decide_pricing(
            session, principal, boq_id, approve=body.approve, note=body.note
        ),
        principal,
    )


@router.post("/{boq_id}/issue", status_code=status.HTTP_201_CREATED)
async def issue(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.BOQ_ISSUE))],
    boq_id: uuid.UUID,
    guard: Idem,
) -> Any:
    async def work() -> dict[str, Any]:
        v = await service.issue(session, principal, boq_id)
        return service.version_view(v, principal)

    return await run_idempotent(guard, str(principal.user_id), 201, work)


@router.get("/{boq_id}/versions", response_model=list[VersionRowOut])
async def versions(session: Session, principal: Reader, boq_id: uuid.UUID) -> list[dict[str, Any]]:
    return [
        {
            "number": v.number,
            "state": v.state,
            "quote_ref": v.quote_ref,
            "change_summary": v.change_summary,
            "issued_at": v.issued_at.isoformat(),
            "totals": v.totals,
            "po_number": v.po_number,
        }
        for v in await service.list_versions(session, principal, boq_id)
    ]


@router.get("/{boq_id}/versions/{number}", response_model=VersionViewOut)
async def get_version(
    session: Session, principal: Reader, boq_id: uuid.UUID, number: int
) -> dict[str, Any]:
    return service.version_view(
        await service.get_version(session, principal, boq_id, number), principal
    )


@router.get("/{boq_id}/compare", response_model=CompareOut)
async def compare(
    session: Session,
    principal: Reader,
    boq_id: uuid.UUID,
    older: Annotated[int, Query(ge=1)],
    newer: Annotated[int, Query(ge=1)],
) -> dict[str, Any]:
    """Lines added, removed and changed between two issued versions, with both totals."""
    return await service.compare_versions(session, principal, boq_id, older, newer)


@router.post("/{boq_id}/versions/{number}/accept")
async def accept(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.BOQ_ACCEPT))],
    boq_id: uuid.UUID,
    number: int,
    body: AcceptIn,
    guard: Idem,
) -> Any:
    """The customer accepted. Locks the version with the purchase order and the chosen options."""

    async def work() -> dict[str, Any]:
        v = await service.accept(
            session,
            principal,
            boq_id,
            number,
            po_number=body.po_number,
            po_date=body.po_date,
            po_file_id=body.po_file_id,
            selected=body.selected_options,
            note=body.note,
        )
        return service.version_view(v, principal)

    return await run_idempotent(guard, str(principal.user_id), 200, work)


@router.post("/{boq_id}/reopen", response_model=BoqOut)
async def reopen(
    session: Session, principal: Editor, boq_id: uuid.UUID, body: ReopenIn
) -> dict[str, Any]:
    """After the project is returned to the BOQ stage, start a new draft from the accepted version."""
    return service.view(await service.reopen(session, principal, boq_id, body.reason), principal)


# ------------------------------------------------------------------ documents


@router.get("/{boq_id}/render")
async def render_doc(
    session: Session,
    principal: Reader,
    boq_id: uuid.UUID,
    fmt: Literal["html", "pdf", "xlsx"] = "pdf",
    kind: Literal["quotation", "summary"] = "quotation",
    version: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    """The quotation or the summary BOQ. Without `version` you get the current draft, marked Draft."""
    b = await service._load(session, principal, boq_id)
    ref: str | None
    if version is not None:
        v = await service.get_version(session, principal, boq_id, version)
        draft, ref = d.Draft.model_validate(v.content), v.quote_ref
    else:
        draft, ref = d.Draft.model_validate(b.draft), b.quote_ref
    comp = await service.company(session)
    digest = ""
    if fmt == "xlsx":
        data, mime = (
            render.render_xlsx(draft, comp, quote_ref=ref, kind=kind),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        html = render.render_html(draft, comp, quote_ref=ref, kind=kind)
        if fmt == "html":
            return Response(content=html, media_type="text/html; charset=utf-8")
        doc = render.render_pdf(html)
        data, mime, digest = doc.pdf, "application/pdf", doc.sha256
    name = f"{(ref or 'draft').replace('/', '-')}-{kind}.{fmt}"
    if not data:
        raise NotFound("Nothing to render.")
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if fmt == "pdf":
        headers["X-Content-SHA256"] = digest
    return Response(content=data, media_type=mime, headers=headers)


routers = [router, project_router]
