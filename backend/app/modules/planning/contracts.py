"""Public surface of the planning module. Other modules import only from here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.customers.contracts import get_project_ref
from app.modules.identity.contracts import P, Principal
from app.modules.planning.models import ConfigBaseline, Plan, PlanTask
from app.modules.planning.service import ARTIFACT

ARTIFACT_PLAN = ARTIFACT


@dataclass(frozen=True)
class TaskRef:
    id: uuid.UUID
    ref: str
    kind: str
    title: str
    asset: str | None
    minutes: int
    depends_on: tuple[str, ...]
    assignee_id: uuid.UUID | None
    start_at: datetime
    end_at: datetime
    requires_downtime: bool
    device_type: str | None
    steps: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    boq_line_ref: str | None


@dataclass(frozen=True)
class BaselineRef:
    id: uuid.UUID
    task_ref: str | None
    device_type: str
    device_label: str
    fields: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PlanRef:
    id: uuid.UUID
    number: int
    boq_quote_ref: str
    tasks: tuple[TaskRef, ...]
    baselines: tuple[BaselineRef, ...]


async def get_baselined_plan(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> PlanRef:
    """The locked plan that field work runs from. Tasks carry no prices. Needs `plan:read`."""
    principal.require(P.PLAN_READ)
    await get_project_ref(session, principal, project_id)
    plan = await session.scalar(
        select(Plan).where(Plan.project_id == project_id, Plan.status == "baselined")
    )
    if plan is None:
        raise NotFound("There is no locked plan for this project yet.")
    tasks = await session.scalars(
        select(PlanTask).where(PlanTask.plan_id == plan.id).order_by(PlanTask.sequence)
    )
    base = await session.scalars(select(ConfigBaseline).where(ConfigBaseline.plan_id == plan.id))
    return PlanRef(
        plan.id,
        plan.number,
        plan.boq_quote_ref,
        tuple(
            TaskRef(
                t.id,
                t.ref,
                t.kind,
                t.title,
                t.asset,
                t.minutes,
                tuple(t.depends_on),
                t.assignee_id,
                t.start_at,  # type: ignore[arg-type]
                t.end_at,  # type: ignore[arg-type]
                t.requires_downtime,
                t.device_type,
                tuple(t.steps),
                tuple(t.evidence),
                t.boq_line_ref,
            )
            for t in tasks
        ),
        tuple(
            BaselineRef(b.id, b.task_ref, b.device_type, b.device_label, tuple(b.fields))
            for b in base
        ),
    )


__all__ = ["ARTIFACT_PLAN", "BaselineRef", "PlanRef", "TaskRef", "get_baselined_plan"]
