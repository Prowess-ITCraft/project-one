from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.core.pagination import Page, PageParams, page_params, paginate_rows
from app.core.ratelimit import Limit, by_ip
from app.modules.customers import service
from app.modules.customers.models import Contact, Site
from app.modules.customers.schemas import (
    AckConfirmIn,
    AckIssueIn,
    AckIssueOut,
    AckViewOut,
    ArtifactOut,
    BriefIn,
    BriefOut,
    ContactIn,
    ContactOut,
    ContactUpdateIn,
    CustomerCreateIn,
    CustomerOut,
    CustomerUpdateIn,
    DecisionIn,
    DecisionOut,
    GateConfigIn,
    GateConfigOut,
    MemberIn,
    MemberOut,
    ProjectCreateIn,
    ProjectOut,
    ProjectStatus,
    ProjectTrackerOut,
    ProjectUpdateIn,
    RejectIn,
    RepresentativeIn,
    ReturnIn,
    SiteIn,
    SiteOut,
    SiteUpdateIn,
    StageStatusOut,
    SubmissionOut,
    SubmitIn,
)
from app.modules.customers.stages import STAGE_LABELS, STAGE_ORDER, Stage
from app.modules.identity.contracts import (
    P,
    Principal,
    Role,
    create_customer_representative,
    require,
)

Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]

customers_router = APIRouter(prefix="/customers", tags=["customers"])
projects_router = APIRouter(prefix="/projects", tags=["projects"])
gates_router = APIRouter(prefix="/gates", tags=["projects"])
public_router = APIRouter(
    prefix="/public/acks",
    tags=["public"],
    dependencies=[Depends(by_ip(Limit("public_ack", 20, strict=True)))],
)


def _out[M: BaseModel](model: type[M], obj: object) -> M:
    return model.model_validate(obj, from_attributes=True)


# ------------------------------------------------------------------ customers


@customers_router.get("", response_model=Page[CustomerOut])
async def list_customers(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_READ))],
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    include_deleted: bool = False,
) -> Page[CustomerOut]:
    stmt = service.customers_query(
        principal, q=q, include_deleted=include_deleted and principal.has(P.CUSTOMER_DELETE)
    )
    rows, total = await paginate_rows(session, stmt, params)
    return Page(
        items=[_out(CustomerOut, c) for c in rows], page=params.page, size=params.size, total=total
    )


@customers_router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    body: CustomerCreateIn,
) -> CustomerOut:
    return _out(CustomerOut, await service.create_customer(session, principal, body))


@customers_router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_READ))],
    customer_id: uuid.UUID,
) -> CustomerOut:
    return _out(CustomerOut, await service.get_customer(session, principal, customer_id))


@customers_router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    body: CustomerUpdateIn,
) -> CustomerOut:
    return _out(CustomerOut, await service.update_customer(session, principal, customer_id, body))


@customers_router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_DELETE))],
    customer_id: uuid.UUID,
) -> None:
    await service.delete_customer(session, principal, customer_id)


@customers_router.post("/{customer_id}/restore", response_model=CustomerOut)
async def restore_customer(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_DELETE))],
    customer_id: uuid.UUID,
) -> CustomerOut:
    return _out(CustomerOut, await service.restore_customer(session, principal, customer_id))


@customers_router.get("/{customer_id}/sites", response_model=list[SiteOut])
async def list_sites(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_READ))],
    customer_id: uuid.UUID,
) -> list[SiteOut]:
    return [
        _out(SiteOut, s) for s in await service.list_children(session, principal, Site, customer_id)
    ]


@customers_router.post(
    "/{customer_id}/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED
)
async def add_site(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    body: SiteIn,
) -> SiteOut:
    return _out(SiteOut, await service.add_site(session, principal, customer_id, body))


@customers_router.patch("/{customer_id}/sites/{site_id}", response_model=SiteOut)
async def update_site(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    site_id: uuid.UUID,
    body: SiteUpdateIn,
) -> SiteOut:
    return _out(SiteOut, await service.update_site(session, principal, customer_id, site_id, body))


@customers_router.delete("/{customer_id}/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    site_id: uuid.UUID,
) -> None:
    await service.soft_delete_child(session, principal, Site, customer_id, site_id)


@customers_router.post("/{customer_id}/sites/{site_id}/restore", response_model=SiteOut)
async def restore_site(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    site_id: uuid.UUID,
) -> SiteOut:
    return _out(
        SiteOut, await service.restore_child(session, principal, Site, customer_id, site_id)
    )


@customers_router.get("/{customer_id}/contacts", response_model=list[ContactOut])
async def list_contacts(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_READ))],
    customer_id: uuid.UUID,
) -> list[ContactOut]:
    return [
        _out(ContactOut, c)
        for c in await service.list_children(session, principal, Contact, customer_id)
    ]


@customers_router.post(
    "/{customer_id}/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED
)
async def add_contact(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    body: ContactIn,
) -> ContactOut:
    return _out(ContactOut, await service.add_contact(session, principal, customer_id, body))


@customers_router.patch("/{customer_id}/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: ContactUpdateIn,
) -> ContactOut:
    return _out(
        ContactOut, await service.update_contact(session, principal, customer_id, contact_id, body)
    )


@customers_router.delete(
    "/{customer_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_contact(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> None:
    await service.soft_delete_child(session, principal, Contact, customer_id, contact_id)


@customers_router.post("/{customer_id}/contacts/{contact_id}/restore", response_model=ContactOut)
async def restore_contact(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE))],
    customer_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> ContactOut:
    return _out(
        ContactOut,
        await service.restore_child(session, principal, Contact, customer_id, contact_id),
    )


@customers_router.post(
    "/{customer_id}/representatives",
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer representative account (sign-in stays off until the flag is on)",
)
async def add_representative(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_WRITE, P.USER_MANAGE))],
    customer_id: uuid.UUID,
    body: RepresentativeIn,
) -> dict[str, uuid.UUID]:
    customer = await service.get_customer(session, principal, customer_id)
    user_id = await create_customer_representative(
        session,
        principal,
        customer_id=customer.id,
        email=body.email,
        full_name=body.full_name,
        phone=body.phone,
        password=body.password,
    )
    return {"user_id": user_id}


# ------------------------------------------------------------------ projects


@projects_router.get("", response_model=Page[ProjectOut])
async def list_projects(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_READ))],
    params: Annotated[PageParams, Depends(page_params)],
    customer_id: uuid.UUID | None = None,
    stage: Stage | None = None,
    project_status: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    include_deleted: bool = False,
) -> Page[ProjectOut]:
    stmt = service.projects_query(
        principal,
        customer_id=customer_id,
        stage=stage,
        status=project_status,
        include_deleted=include_deleted and principal.has(P.PROJECT_DELETE),
    )
    rows, total = await paginate_rows(session, stmt, params)
    return Page(
        items=[_out(ProjectOut, p) for p in rows], page=params.page, size=params.size, total=total
    )


@projects_router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_WRITE))],
    body: ProjectCreateIn,
    guard: Idem,
) -> Any:
    async def work() -> ProjectOut:
        return _out(ProjectOut, await service.create_project(session, principal, body))

    return await run_idempotent(guard, str(principal.user_id), 201, work)


@projects_router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_READ))],
    project_id: uuid.UUID,
) -> ProjectOut:
    return _out(ProjectOut, await service.get_project(session, principal, project_id))


@projects_router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_WRITE))],
    project_id: uuid.UUID,
    body: ProjectUpdateIn,
) -> ProjectOut:
    return _out(ProjectOut, await service.update_project(session, principal, project_id, body))


@projects_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_DELETE))],
    project_id: uuid.UUID,
) -> None:
    await service.delete_project(session, principal, project_id)


@projects_router.post("/{project_id}/restore", response_model=ProjectOut)
async def restore_project(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_DELETE))],
    project_id: uuid.UUID,
) -> ProjectOut:
    return _out(ProjectOut, await service.restore_project(session, principal, project_id))


@projects_router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_READ))],
    project_id: uuid.UUID,
) -> list[MemberOut]:
    return [
        MemberOut(
            user_id=m.user_id, full_name=name, project_role=m.project_role, added_at=m.added_at
        )
        for m, name in await service.list_members(session, principal, project_id)
    ]


@projects_router.put("/{project_id}/members", response_model=MemberOut)
async def set_member(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_MEMBERS))],
    project_id: uuid.UUID,
    body: MemberIn,
) -> MemberOut:
    m = await service.add_member(session, principal, project_id, body.user_id, body.project_role)
    return MemberOut(
        user_id=m.user_id, full_name=None, project_role=m.project_role, added_at=m.added_at
    )


@projects_router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_MEMBERS))],
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    await service.remove_member(session, principal, project_id, user_id)


@projects_router.get(
    "/{project_id}/tracker", response_model=ProjectTrackerOut, summary="Stage tracker"
)
async def project_tracker(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_READ))],
    project_id: uuid.UUID,
) -> ProjectTrackerOut:
    project, decisions, pending = await service.tracker(session, principal, project_id)
    current_index = STAGE_ORDER.index(Stage(project.current_stage))
    stages = []
    for i, st in enumerate(STAGE_ORDER):
        done = i < current_index or project.status == "completed"
        d = decisions.get(st.value)
        p = pending.get(st.value)
        stages.append(
            StageStatusOut(
                stage=st,
                label=STAGE_LABELS[st],
                state="done" if done else ("current" if i == current_index else "locked"),
                decision=_out(DecisionOut, d) if d else None,
                pending_submission=_out(SubmissionOut, p) if p else None,
            )
        )
    return ProjectTrackerOut(project=_out(ProjectOut, project), stages=stages)


@projects_router.get("/{project_id}/artifacts", response_model=list[ArtifactOut])
async def list_artifacts(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_READ))],
    project_id: uuid.UUID,
) -> list[ArtifactOut]:
    return [
        _out(ArtifactOut, a) for a in await service.list_artifacts(session, principal, project_id)
    ]


@projects_router.get("/{project_id}/gate-history")
async def gate_history(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_READ))],
    project_id: uuid.UUID,
) -> dict[str, list[Any]]:
    subs, decs = await service.history(session, principal, project_id)
    return {
        "submissions": [_out(SubmissionOut, s).model_dump(mode="json") for s in subs],
        "decisions": [_out(DecisionOut, d).model_dump(mode="json") for d in decs],
    }


@projects_router.post(
    "/{project_id}/stages/{stage}/submit",
    response_model=SubmissionOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_stage(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.GATE_SUBMIT))],
    project_id: uuid.UUID,
    stage: Stage,
    body: SubmitIn,
    guard: Idem,
) -> Any:
    async def work() -> SubmissionOut:
        return _out(
            SubmissionOut,
            await service.submit_stage(
                session, principal, project_id, stage, body.note, body.artifact_id
            ),
        )

    return await run_idempotent(guard, str(principal.user_id), 201, work)


@projects_router.post(
    "/{project_id}/submissions/{submission_id}/approve", response_model=DecisionOut
)
async def approve(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.GATE_APPROVE))],
    project_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: DecisionIn,
    guard: Idem,
) -> Any:
    async def work() -> DecisionOut:
        return _out(
            DecisionOut,
            await service.approve(session, principal, project_id, submission_id, body.comment),
        )

    return await run_idempotent(guard, str(principal.user_id), 200, work)


@projects_router.post(
    "/{project_id}/submissions/{submission_id}/reject", response_model=DecisionOut
)
async def reject(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.GATE_APPROVE))],
    project_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: RejectIn,
    guard: Idem,
) -> Any:
    async def work() -> DecisionOut:
        return _out(
            DecisionOut,
            await service.reject(session, principal, project_id, submission_id, body.comment),
        )

    return await run_idempotent(guard, str(principal.user_id), 200, work)


@projects_router.post(
    "/{project_id}/submissions/{submission_id}/withdraw", response_model=SubmissionOut
)
async def withdraw(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.GATE_SUBMIT))],
    project_id: uuid.UUID,
    submission_id: uuid.UUID,
) -> SubmissionOut:
    return _out(
        SubmissionOut, await service.withdraw(session, principal, project_id, submission_id)
    )


@projects_router.post(
    "/{project_id}/submissions/{submission_id}/customer-ack",
    response_model=AckIssueOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a single-use acknowledgement link for a customer contact",
)
async def issue_ack(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.CUSTOMER_ACK_ISSUE))],
    project_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: AckIssueIn,
) -> AckIssueOut:
    ack, url = await service.issue_ack(
        session, principal, project_id, submission_id, body.contact_id, body.valid_hours
    )
    return AckIssueOut(ack_id=ack.id, url=url, expires_at=ack.expires_at)


# ------------------------------------------------------------------ gate configuration


@gates_router.get("", response_model=list[GateConfigOut])
async def list_gate_configs(
    session: Session, _: Annotated[Principal, Depends(require(P.PROJECT_READ))]
) -> list[GateConfigOut]:
    out = []
    for st in STAGE_ORDER:
        cfg = await service.gate_config(session, st)
        out.append(
            GateConfigOut(
                stage=st,
                label=STAGE_LABELS[st],
                approver_roles=[Role(r) for r in cfg.approver_roles],
                artifact_type=cfg.artifact_type,
                requires_artifact=cfg.requires_artifact,
                requires_customer_ack=cfg.requires_customer_ack,
                version=cfg.version,
            )
        )
    await session.commit()
    return out


@gates_router.put("/{stage}", response_model=GateConfigOut)
async def update_gate_config(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.GATE_CONFIGURE))],
    stage: Stage,
    body: GateConfigIn,
) -> GateConfigOut:
    cfg = await service.update_gate_config(
        session,
        principal,
        stage,
        version=body.version,
        approver_roles=body.approver_roles,
        requires_artifact=body.requires_artifact,
        requires_customer_ack=body.requires_customer_ack,
    )
    return GateConfigOut(
        stage=stage,
        label=STAGE_LABELS[stage],
        approver_roles=[Role(r) for r in cfg.approver_roles],
        artifact_type=cfg.artifact_type,
        requires_artifact=cfg.requires_artifact,
        requires_customer_ack=cfg.requires_customer_ack,
        version=cfg.version,
    )


@projects_router.get("/{project_id}/brief", response_model=BriefOut | None)
async def get_brief(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PROJECT_READ))],
    project_id: uuid.UUID,
) -> BriefOut | None:
    b = await service.get_brief(session, principal, project_id)
    return _out(BriefOut, b) if b else None


@projects_router.put("/{project_id}/brief", response_model=BriefOut)
async def put_brief(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.BRIEF_WRITE))],
    project_id: uuid.UUID,
    body: BriefIn,
) -> BriefOut:
    """The intake questionnaire. Send `version` to update an existing brief."""
    return _out(BriefOut, await service.upsert_brief(session, principal, project_id, body))


@projects_router.post("/{project_id}/return-to/{stage}", response_model=ProjectOut)
async def return_to_stage(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.GATE_APPROVE))],
    project_id: uuid.UUID,
    stage: Stage,
    body: ReturnIn,
) -> ProjectOut:
    """Send the project back to an earlier stage (a disputed gap, a customer change)."""
    project = await service.return_to_stage(session, principal, project_id, stage, body.reason)
    return _out(ProjectOut, project)


# ------------------------------------------------------------------ public acknowledgement links


@public_router.get("/{token}", response_model=AckViewOut)
async def view_ack(session: Session, token: str) -> AckViewOut:
    if not 20 <= len(token) <= 100:
        raise NotFound("This link is not valid or has expired.", code="ack_link_invalid")
    return AckViewOut(**await service.view_ack(session, token))


@public_router.post("/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_ack(request: Request, session: Session, token: str, body: AckConfirmIn) -> None:
    if not 20 <= len(token) <= 100:
        raise NotFound("This link is not valid or has expired.", code="ack_link_invalid")
    await service.confirm_ack(
        session, token, body.full_name, request.state.client_ip, request.headers.get("user-agent")
    )
