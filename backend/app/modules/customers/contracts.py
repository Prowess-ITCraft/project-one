"""Public surface of the customers module. Other modules import only from here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent
from app.modules.customers import service as _service
from app.modules.customers.stages import STAGE_LABELS, STAGE_ORDER, Stage
from app.modules.identity.contracts import Principal

ARTIFACT_LOCKED = _service.ARTIFACT_LOCKED
GATE_APPROVED = _service.GATE_APPROVED


@dataclass(frozen=True)
class ProjectRef:
    id: uuid.UUID
    code: str
    name: str
    customer_id: uuid.UUID
    current_stage: Stage
    status: str


@dataclass(frozen=True)
class CustomerRef:
    id: uuid.UUID
    code: str
    legal_name: str
    display_name: str
    gstin: str | None
    address_lines: tuple[str, ...]


async def get_project_ref(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> ProjectRef:
    """Raises NotFound when the project does not exist or the caller cannot see it."""
    p = await _service.get_project(session, principal, project_id)
    return ProjectRef(p.id, p.code, p.name, p.customer_id, Stage(p.current_stage), p.status)


async def get_customer_ref(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID
) -> CustomerRef:
    c = await _service.get_customer(session, principal, customer_id)
    lines = tuple(
        x for x in (c.address_line1, c.address_line2, f"{c.city}, {c.state} {c.pincode}") if x
    )
    return CustomerRef(c.id, c.code, c.legal_name, c.display_name, c.gstin, lines)


@dataclass(frozen=True)
class BriefRef:
    company_size: str
    budget_tier: str
    users_now: int | None
    users_12m: int | None
    sites: int
    preferred_brands: tuple[str, ...]
    excluded_brands: tuple[str, ...]
    budget_ceiling: Decimal | None
    category_budgets: dict[str, str]
    keep_assets: tuple[str, ...]
    compliance: tuple[str, ...]


async def get_brief_ref(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> BriefRef | None:
    """The intake questionnaire, or None when it has not been filled in."""
    b = await _service.get_brief(session, principal, project_id)
    if b is None:
        return None
    return BriefRef(
        b.company_size,
        b.budget_tier,
        b.users_now,
        b.users_12m,
        b.sites,
        tuple(b.preferred_brands),
        tuple(b.excluded_brands),
        b.budget_ceiling,
        {k: str(v) for k, v in b.category_budgets.items()},
        tuple(b.keep_assets),
        tuple(b.compliance),
    )


@dataclass(frozen=True)
class MemberRef:
    user_id: uuid.UUID
    full_name: str | None
    project_role: str


async def get_project_members(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[MemberRef]:
    """Who is on the project team. Raises NotFound when the caller cannot see the project."""
    rows = await _service.list_members(session, principal, project_id)
    return [MemberRef(m.user_id, name, m.project_role) for m, name in rows]


@dataclass(frozen=True)
class ContactRef:
    id: uuid.UUID
    full_name: str
    email: str
    can_sign_off: bool
    is_primary: bool


async def get_sign_off_contacts(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[ContactRef]:
    """Customer contacts with an email who can confirm a visit, best choice first."""
    rows = await _service.sign_off_contacts(session, principal, project_id)
    return [
        ContactRef(c.id, c.full_name, c.email or "", c.can_sign_off, c.is_primary) for c in rows
    ]


def artifact_locked_event(
    *,
    project_id: uuid.UUID,
    stage: Stage,
    artifact_type: str,
    artifact_id: str,
    artifact_version: int,
    title: str,
    locked_by: uuid.UUID | None,
) -> DomainEvent:
    """Build the event a module publishes (via the outbox) when it locks a gate-able output."""
    return DomainEvent(
        event_type=ARTIFACT_LOCKED,
        aggregate_type=artifact_type,
        aggregate_id=artifact_id,
        actor_id=locked_by,
        payload={
            "project_id": str(project_id),
            "stage": stage.value,
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "artifact_version": artifact_version,
            "title": title,
            "locked_by": str(locked_by) if locked_by else None,
        },
    )


async def list_visible_projects(
    session: AsyncSession, principal: Principal, *, status: str | None = "active"
) -> list[ProjectRef]:
    """Projects the caller may see, newest first (for portfolio views such as the dashboard)."""
    stmt = _service.projects_query(
        principal, customer_id=None, stage=None, status=status, include_deleted=False
    )
    return [
        ProjectRef(p.id, p.code, p.name, p.customer_id, Stage(p.current_stage), p.status)
        for p in await session.scalars(stmt)
    ]


@dataclass(frozen=True)
class StageSignoff:
    """Whether a stage gate was approved, by whom, and whether the customer acknowledged it."""

    approved: bool
    decided_by: uuid.UUID | None
    decided_by_name: str | None
    decided_by_roles: tuple[str, ...]
    decided_at: datetime | None
    customer_ack_at: datetime | None
    customer_ack_name: str | None
    pending_submission: bool


async def get_stage_signoff(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, stage: Stage
) -> StageSignoff:
    from sqlalchemy import select

    from app.modules.customers.models import CustomerAck

    _project, decisions, pending = await _service.tracker(session, principal, project_id)
    d = decisions.get(stage.value)
    sub_id = d.submission_id if d else (pending[stage.value].id if stage.value in pending else None)
    ack = None
    if sub_id is not None:
        ack = await session.scalar(
            select(CustomerAck)
            .where(CustomerAck.submission_id == sub_id, CustomerAck.acknowledged_at.is_not(None))
            .order_by(CustomerAck.acknowledged_at.desc())
            .limit(1)
        )
    return StageSignoff(
        approved=d is not None,
        decided_by=d.decided_by if d else None,
        decided_by_name=d.decided_by_name if d else None,
        decided_by_roles=tuple(d.decided_by_roles) if d else (),
        decided_at=d.decided_at if d else None,
        customer_ack_at=ack.acknowledged_at if ack else None,
        customer_ack_name=ack.acknowledged_name if ack else None,
        pending_submission=stage.value in pending,
    )


__all__ = [
    "ARTIFACT_LOCKED",
    "GATE_APPROVED",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "BriefRef",
    "ContactRef",
    "CustomerRef",
    "MemberRef",
    "ProjectRef",
    "Stage",
    "StageSignoff",
    "artifact_locked_event",
    "get_brief_ref",
    "get_customer_ref",
    "get_project_members",
    "get_project_ref",
    "get_sign_off_contacts",
    "get_stage_signoff",
    "list_visible_projects",
]
