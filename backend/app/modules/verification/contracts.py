"""Public surface of the verification module. Other modules import only from here.

The completion report and certificate (phase 10) read deviations and the severity policy here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.contracts import get_project_ref
from app.modules.identity.contracts import P, Principal
from app.modules.verification import service as _service
from app.modules.verification.models import Deviation


@dataclass(frozen=True)
class DeviationRef:
    id: uuid.UUID
    run_id: uuid.UUID
    task_ref: str
    device: str | None
    label: str
    severity: str
    expected: str | None
    actual: str | None
    status: str
    resolution: str | None
    opened_at: datetime
    resolved_at: datetime | None


def _ref(d: Deviation) -> DeviationRef:
    return DeviationRef(
        d.id,
        d.run_id,
        d.task_ref,
        d.device,
        d.label,
        d.severity,
        d.expected,
        d.actual,
        d.status,
        d.resolution,
        d.created_at,
        d.resolved_at,
    )


async def project_deviations(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[DeviationRef]:
    """Every deviation of a project, any status."""
    if not principal.has(P.FIELD_READ):
        principal.require(P.REPORT_READ)
    await get_project_ref(session, principal, project_id)
    rows = await session.scalars(
        select(Deviation).where(Deviation.project_id == project_id).order_by(Deviation.created_at)
    )
    return [_ref(d) for d in rows]


async def severity_policy(session: AsyncSession) -> dict[str, Any]:
    return await _service.get_policy(session)


async def waive_deviation(
    session: AsyncSession, deviation_id: uuid.UUID, *, waiver: str, by: uuid.UUID
) -> None:
    """Close an open deviation as waived. Reporting calls this when the waiver is approved by the
    Director and acknowledged by the customer. The caller commits."""
    await _service.mark_waived(session, deviation_id, waiver=waiver, by=by)


__all__ = ["DeviationRef", "project_deviations", "severity_policy", "waive_deviation"]
