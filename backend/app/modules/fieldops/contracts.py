"""Public surface of the fieldops module. Other modules import only from here.

Verification (phase 9) and the completion report (phase 10) read field work through this file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.contracts import get_project_ref
from app.modules.fieldops.engine import (
    BLOCKING,
    DRIVERS,
    AnswerDriver,
    CheckResult,
    ConfigCheckDriver,
    ExportFile,
    FieldResult,
    passes,
)
from app.modules.fieldops.models import FLOW, RunCheck, TaskRun
from app.modules.fieldops.service import CHECK_COMPLETED
from app.modules.identity.contracts import P, Principal


@dataclass(frozen=True)
class FieldStatus:
    """Where field work stands for a project, for the completion gate."""

    total: int
    closed: int
    open_refs: tuple[str, ...]
    open_critical_deviations: int

    @property
    def complete(self) -> bool:
        return self.total > 0 and self.closed == self.total


async def field_status(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> FieldStatus:
    principal.require(P.FIELD_READ)
    await get_project_ref(session, principal, project_id)
    runs = list(await session.scalars(select(TaskRun).where(TaskRun.project_id == project_id)))
    critical = 0
    for r in runs:
        if r.state == "closed":
            continue
        last = await session.scalar(
            select(RunCheck)
            .where(RunCheck.run_id == r.id)
            .order_by(RunCheck.attempt.desc())
            .limit(1)
        )
        critical += last.critical_open if last else 0
    return FieldStatus(
        total=len(runs),
        closed=sum(1 for r in runs if r.state == "closed"),
        open_refs=tuple(sorted(r.task_ref for r in runs if r.state != "closed")),
        open_critical_deviations=critical,
    )


@dataclass(frozen=True)
class RunRef:
    id: uuid.UUID
    project_id: uuid.UUID
    task_ref: str
    title: str
    asset: str | None
    state: str
    assignee_id: uuid.UUID
    device_type: str | None = None
    checked_in_at: datetime | None = None
    closed_at: datetime | None = None
    verified_by: uuid.UUID | None = None


def _run_ref(r: TaskRun) -> RunRef:
    return RunRef(
        r.id,
        r.project_id,
        r.task_ref,
        r.title,
        r.asset,
        r.state,
        r.assignee_id,
        r.device_type,
        r.checked_in_at,
        r.closed_at,
        r.verified_by,
    )


async def get_run_ref(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> RunRef:
    """One field task, for modules that act on it (verification). Raises NotFound."""
    from app.core.errors import NotFound

    principal.require(P.FIELD_READ)
    r = await session.get(TaskRun, run_id)
    if r is None:
        raise NotFound("Task not found.")
    await get_project_ref(session, principal, r.project_id)
    return _run_ref(r)


async def list_run_refs(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[RunRef]:
    principal.require(P.FIELD_READ)
    await get_project_ref(session, principal, project_id)
    runs = await session.scalars(
        select(TaskRun).where(TaskRun.project_id == project_id).order_by(TaskRun.planned_start)
    )
    return [_run_ref(r) for r in runs]


async def check_summaries(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> dict[uuid.UUID, dict[str, Any]]:
    """Per task: how many configuration checks ran and the outcome counts of the last one."""
    principal.require(P.FIELD_READ)
    await get_project_ref(session, principal, project_id)
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for c in await session.scalars(
        select(RunCheck).where(RunCheck.project_id == project_id).order_by(RunCheck.attempt)
    ):
        fields = c.result.get("fields", [])
        out[c.run_id] = {
            "attempts": c.attempt,
            "passed": c.passed,
            "driver": c.driver,
            "pass": sum(1 for f in fields if f.get("outcome") == "pass"),
            "fail": sum(1 for f in fields if f.get("outcome") == "fail"),
            "not_checked": sum(1 for f in fields if f.get("outcome") == "not_checked"),
        }
    return out


async def field_snapshot(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> dict[str, Any]:
    """For the Director's dashboard: counts by state, blocked with reasons, late, overdue,
    check-ins today and time against plan."""
    from datetime import datetime, time

    from sqlalchemy import func

    from app.core.timeutil import IST, today_ist
    from app.modules.fieldops import service as _service
    from app.modules.fieldops.models import RunEvent

    s = await _service.summary(session, principal, project_id)
    runs = list(await session.scalars(select(TaskRun).where(TaskRun.project_id == project_id)))
    start_today = datetime.combine(today_ist(), time(0), tzinfo=IST)
    checkins = await session.scalar(
        select(func.count())
        .select_from(RunEvent)
        .where(
            RunEvent.project_id == project_id,
            RunEvent.action == "check_in",
            RunEvent.at >= start_today,
        )
    )
    planned_end = max((r.planned_end for r in runs), default=None)
    return {
        "counts": s["counts"],
        "total": s["total"],
        "closed_share": s["closed_share"],
        "rework": s["rework"],
        "blocked": [
            {
                "run_id": str(r.id),
                "task_ref": r.task_ref,
                "title": r.title,
                "reason": r.block_reason,
            }
            for r in s["blocked"]
        ],
        "late": [r.task_ref for r in s["late"]],
        "overdue": [r.task_ref for r in s["overdue"]],
        "failing_checks": [r.task_ref for r in s["failing_checks"]],
        "checkins_today": int(checkins or 0),
        "planned_end": planned_end.isoformat() if planned_end else None,
    }


def register_driver(device_type: str, driver: ConfigCheckDriver) -> None:
    """Phase 9 adds brand drivers (SonicWall, Sophos, Fortinet, Cisco) here."""
    DRIVERS[device_type] = driver


__all__ = [
    "BLOCKING",
    "CHECK_COMPLETED",
    "FLOW",
    "AnswerDriver",
    "CheckResult",
    "ConfigCheckDriver",
    "ExportFile",
    "FieldResult",
    "FieldStatus",
    "RunRef",
    "check_summaries",
    "field_snapshot",
    "field_status",
    "get_run_ref",
    "list_run_refs",
    "passes",
    "register_driver",
]
