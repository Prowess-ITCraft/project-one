from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.modules.identity.contracts import P, Principal, require
from app.modules.planning import render, service
from app.modules.planning.schemas import (
    BaselineOut,
    BaselinePatchIn,
    ConfigTemplateOut,
    GenerateIn,
    LeaveIn,
    LeaveOut,
    PlanDetailOut,
    PlanOut,
    ScheduleIn,
    TaskCreateIn,
    TaskOut,
    TaskPatchIn,
    TaskTemplateOut,
    TaskTemplatePatchIn,
    WindowIn,
    WindowOut,
)

project_router = APIRouter(prefix="/projects/{project_id}/plan", tags=["planning"])
library_router = APIRouter(prefix="/planning", tags=["planning"])
Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]
Reader = Annotated[Principal, Depends(require(P.PLAN_READ))]
Writer = Annotated[Principal, Depends(require(P.PLAN_WRITE))]
Baseliner = Annotated[Principal, Depends(require(P.PLAN_BASELINE))]
TemplateEditor = Annotated[Principal, Depends(require(P.TEMPLATE_EDIT))]


def _detail(plan: Any, tasks: list[Any], base: list[Any], wins: list[Any]) -> PlanDetailOut:
    ends = max((t.end_at for t in tasks if t.end_at), default=None)
    return PlanDetailOut(
        plan=PlanOut.model_validate(plan, from_attributes=True),
        tasks=[TaskOut.model_validate(t, from_attributes=True) for t in tasks],
        baselines=[BaselineOut.model_validate(b, from_attributes=True) for b in base],
        windows=[WindowOut.model_validate(w, from_attributes=True) for w in wins],
        ends_at=ends,
        total_minutes=sum(t.minutes for t in tasks),
    )


@project_router.get("", response_model=PlanDetailOut | None)
async def get_plan(
    session: Session, principal: Reader, project_id: uuid.UUID
) -> PlanDetailOut | None:
    got = await service.get_plan(session, principal, project_id)
    return _detail(*got) if got else None


@project_router.get("/render")
async def render_plan(
    session: Session,
    principal: Reader,
    project_id: uuid.UUID,
    fmt: Literal["html", "pdf"] = "pdf",
) -> Response:
    """The plan and schedule as a document: one table per day, downtime windows and the target
    configuration per device. No prices."""
    ctx = await render.plan_context(session, principal, project_id)
    if ctx is None:
        raise NotFound("There is no plan for this project yet.")
    if fmt == "html":
        return Response(content=render.render_html(ctx), media_type="text/html; charset=utf-8")
    doc = render.render_plan_pdf(ctx)
    name = f"{ctx['project_code']}-plan-{ctx['plan_number']}.pdf"
    return Response(
        content=doc.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-SHA256": doc.sha256,
        },
    )


@project_router.post("/generate", response_model=PlanDetailOut, status_code=status.HTTP_201_CREATED)
async def generate(
    session: Session, principal: Writer, project_id: uuid.UUID, body: GenerateIn
) -> PlanDetailOut:
    """Draft the plan from the accepted BOQ: one task per unit of work, with dependencies."""
    await service.generate_plan(
        session,
        principal,
        project_id,
        replace=body.replace,
        settings=body.settings.model_dump() if body.settings else None,
    )
    got = await service.get_plan(session, principal, project_id)
    assert got is not None
    return _detail(*got)


@project_router.post("/schedule", response_model=PlanDetailOut)
async def schedule(
    session: Session, principal: Writer, project_id: uuid.UUID, body: ScheduleIn
) -> PlanDetailOut:
    """Assign engineers (optional) and place every task in working time."""
    await service.schedule_plan(
        session,
        principal,
        project_id,
        start_date=body.start_date,
        auto_assign=body.auto_assign,
        settings=body.settings.model_dump() if body.settings else None,
    )
    got = await service.get_plan(session, principal, project_id)
    assert got is not None
    return _detail(*got)


@project_router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    session: Session, principal: Writer, project_id: uuid.UUID, body: TaskCreateIn
) -> TaskOut:
    t = await service.add_task(
        session,
        principal,
        project_id,
        reason=body.reason,
        title=body.title,
        minutes=body.minutes,
        depends_on=body.depends_on,
        steps=body.steps,
        evidence=[e.model_dump() for e in body.evidence],
        requires_downtime=body.requires_downtime,
        device_type=body.device_type,
    )
    return TaskOut.model_validate(t, from_attributes=True)


@project_router.patch("/tasks/{task_id}", response_model=TaskOut)
async def patch_task(
    session: Session,
    principal: Writer,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskPatchIn,
) -> TaskOut:
    changes = body.model_dump(exclude_unset=True, exclude={"version", "reason"})
    t = await service.update_task(
        session,
        principal,
        project_id,
        task_id,
        version=body.version,
        reason=body.reason,
        changes=changes,
    )
    return TaskOut.model_validate(t, from_attributes=True)


@project_router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_task(
    session: Session,
    principal: Writer,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    reason: Annotated[str, Query(min_length=3, max_length=300)],
) -> Response:
    await service.delete_task(session, principal, project_id, task_id, reason=reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@project_router.patch("/baselines/{baseline_id}", response_model=BaselineOut)
async def patch_baseline(
    session: Session,
    principal: Writer,
    project_id: uuid.UUID,
    baseline_id: uuid.UUID,
    body: BaselinePatchIn,
) -> BaselineOut:
    b = await service.update_baseline(
        session,
        principal,
        project_id,
        baseline_id,
        version=body.version,
        reason=body.reason,
        fields=[f.model_dump() for f in body.fields],
    )
    return BaselineOut.model_validate(b, from_attributes=True)


@project_router.post("/downtime", response_model=WindowOut, status_code=status.HTTP_201_CREATED)
async def add_window(
    session: Session, principal: Writer, project_id: uuid.UUID, body: WindowIn
) -> WindowOut:
    w = await service.add_window(
        session, principal, project_id, start_at=body.start_at, end_at=body.end_at, note=body.note
    )
    return WindowOut.model_validate(w, from_attributes=True)


@project_router.delete("/downtime/{window_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_window(
    session: Session, principal: Writer, project_id: uuid.UUID, window_id: uuid.UUID
) -> Response:
    await service.delete_window(session, principal, project_id, window_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@project_router.post("/{plan_id}/baseline", response_model=PlanOut)
async def baseline(
    session: Session, principal: Baseliner, project_id: uuid.UUID, plan_id: uuid.UUID, guard: Idem
) -> Any:
    """Lock the plan and its target configurations as the stage output."""

    async def work() -> PlanOut:
        return PlanOut.model_validate(
            await service.baseline_plan(session, principal, project_id, plan_id),
            from_attributes=True,
        )

    return await run_idempotent(guard, str(principal.user_id), 200, work)


# ------------------------------------------------------------------ shared libraries


@library_router.get("/leaves", response_model=list[LeaveOut])
async def leaves(
    session: Session, principal: Reader, user_id: uuid.UUID | None = None
) -> list[LeaveOut]:
    return [
        LeaveOut.model_validate(x, from_attributes=True)
        for x in await service.list_leaves(session, principal, user_id)
    ]


@library_router.post("/leaves", response_model=LeaveOut, status_code=status.HTTP_201_CREATED)
async def add_leave(session: Session, principal: Writer, body: LeaveIn) -> LeaveOut:
    row = await service.add_leave(
        session,
        principal,
        user_id=body.user_id,
        date_from=body.date_from,
        date_to=body.date_to,
        reason=body.reason,
    )
    return LeaveOut.model_validate(row, from_attributes=True)


@library_router.delete("/leaves/{leave_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_leave(session: Session, principal: Writer, leave_id: uuid.UUID) -> Response:
    await service.delete_leave(session, principal, leave_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@library_router.get("/task-templates", response_model=list[TaskTemplateOut])
async def task_templates(session: Session, principal: Reader) -> list[TaskTemplateOut]:
    return [
        TaskTemplateOut.model_validate(t, from_attributes=True)
        for t in await service.list_task_templates(session, principal)
    ]


@library_router.patch("/task-templates/{key}", response_model=TaskTemplateOut)
async def patch_task_template(
    session: Session, principal: TemplateEditor, key: str, body: TaskTemplatePatchIn
) -> TaskTemplateOut:
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    t = await service.update_task_template(
        session, principal, key, version=body.version, changes=changes
    )
    return TaskTemplateOut.model_validate(t, from_attributes=True)


@library_router.get("/config-templates", response_model=list[ConfigTemplateOut])
async def config_templates(session: Session, principal: Reader) -> list[ConfigTemplateOut]:
    return [
        ConfigTemplateOut.model_validate(c, from_attributes=True)
        for c in await service.list_config_templates(session, principal)
    ]


routers = [project_router, library_router]
