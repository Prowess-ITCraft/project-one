"""Public surface of the infra module. Other modules import only from here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.contracts import Principal
from app.modules.infra import service as _service

ARTIFACT_GAPS = _service.ARTIFACT_GAPS


@dataclass(frozen=True)
class GapRef:
    id: uuid.UUID
    code: str  # GAP-001
    gap_type: str
    component: str
    lens: str
    title: str
    priority: str  # high | consider
    status: str
    affected: tuple[str, ...]
    qty_hint: int | None
    recommendation: str | None
    source: str


@dataclass(frozen=True)
class GapSet:
    register_id: uuid.UUID
    number: int
    facts: dict[str, Any]
    gaps: tuple[GapRef, ...] = field(default_factory=tuple)


async def get_locked_gaps(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> GapSet:
    """The latest locked gap register: open and accepted gaps plus the audit facts they came
    from. Raises NotFound when no register is locked."""
    reg, gaps = await _service.locked_register(session, principal, project_id)
    return GapSet(
        register_id=reg.id,
        number=reg.number,
        facts=dict(reg.facts),
        gaps=tuple(
            GapRef(
                g.id,
                f"GAP-{g.number:03d}",
                g.gap_type,
                g.component,
                g.lens,
                g.title,
                g.priority,
                g.status,
                tuple(g.affected),
                g.qty_hint,
                g.recommendation,
                g.source,
            )
            for g in gaps
        ),
    )


__all__ = ["ARTIFACT_GAPS", "GapRef", "GapSet", "get_locked_gaps"]
