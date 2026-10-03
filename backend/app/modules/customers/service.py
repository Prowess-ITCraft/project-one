"""Customer, project and stage-gate rules."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotFound, StaleVersion, ValidationFailed
from app.core.events import DomainEvent
from app.core.sequences import next_value
from app.core.timeutil import financial_year_code, today_ist, utcnow
from app.modules.audit_log.contracts import AuditContext, record
from app.modules.customers.models import (
    Contact,
    Customer,
    CustomerAck,
    GateConfig,
    GateDecision,
    Project,
    ProjectBrief,
    ProjectMember,
    Site,
    StageArtifact,
    StageSubmission,
)
from app.modules.customers.schemas import (
    BriefIn,
    ContactIn,
    ContactUpdateIn,
    CustomerCreateIn,
    CustomerUpdateIn,
    ProjectCreateIn,
    ProjectUpdateIn,
    SiteIn,
    SiteUpdateIn,
)
from app.modules.customers.stages import (
    GATE_DEFAULTS,
    STAGE_LABELS,
    STAGE_ORDER,
    Stage,
    next_stage,
)
from app.modules.identity.contracts import (
    P,
    Principal,
    Role,
    audit_context,
    ensure_different_people,
    get_user_summary,
)

ARTIFACT_LOCKED = "stage.artifact_locked"
GATE_APPROVED = "customers.gate_approved"
GATE_REJECTED = "customers.gate_rejected"


def _snap(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


_CUSTOMER_FIELDS = [
    "code",
    "legal_name",
    "display_name",
    "gstin",
    "segment",
    "industry",
    "employee_count",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "pincode",
    "notes",
    "account_owner_id",
]
_SITE_FIELDS = ["name", "address_line1", "address_line2", "city", "state", "pincode", "is_primary"]
_CONTACT_FIELDS = [
    "full_name",
    "designation",
    "email",
    "phone",
    "site_id",
    "is_primary",
    "can_sign_off",
]
_PROJECT_FIELDS = [
    "code",
    "name",
    "description",
    "site_id",
    "current_stage",
    "status",
    "customer_id",
]


def _check_version(current: int, sent: int) -> None:
    if current != sent:
        raise StaleVersion()


# ------------------------------------------------------------------ visibility (object-level)


def project_visibility(principal: Principal) -> ColumnElement[bool]:
    if principal.has(P.PROJECT_READ_ALL):
        return true()
    if principal.is_customer:
        return Project.customer_id == principal.customer_id if principal.customer_id else false()
    member = exists().where(
        ProjectMember.project_id == Project.id, ProjectMember.user_id == principal.user_id
    )
    return or_(member, Project.created_by == principal.user_id)


def customer_visibility(principal: Principal) -> ColumnElement[bool]:
    if principal.has(P.CUSTOMER_READ_ALL):
        return true()
    if principal.is_customer:
        return Customer.id == principal.customer_id if principal.customer_id else false()
    via_project = exists().where(
        Project.customer_id == Customer.id,
        Project.deleted_at.is_(None),
        or_(
            Project.created_by == principal.user_id,
            exists().where(
                ProjectMember.project_id == Project.id, ProjectMember.user_id == principal.user_id
            ),
        ),
    )
    return or_(
        Customer.account_owner_id == principal.user_id,
        Customer.created_by == principal.user_id,
        via_project,
    )


async def get_customer(
    session: AsyncSession,
    principal: Principal,
    customer_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> Customer:
    stmt = select(Customer).where(Customer.id == customer_id, customer_visibility(principal))
    if not include_deleted:
        stmt = stmt.where(Customer.deleted_at.is_(None))
    c = await session.scalar(stmt)
    if c is None:
        raise NotFound("Customer not found.")  # also for customers you cannot see
    return c


async def get_project(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> Project:
    stmt = select(Project).where(Project.id == project_id, project_visibility(principal))
    if not include_deleted:
        stmt = stmt.where(Project.deleted_at.is_(None))
    p = await session.scalar(stmt)
    if p is None:
        raise NotFound("Project not found.")
    return p


def customers_query(
    principal: Principal, *, q: str | None, include_deleted: bool
) -> Select[Customer]:
    stmt = select(Customer).where(customer_visibility(principal)).order_by(Customer.display_name)
    if not include_deleted:
        stmt = stmt.where(Customer.deleted_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                Customer.legal_name.ilike(like),
                Customer.display_name.ilike(like),
                Customer.code.ilike(like),
            )
        )
    return stmt


def projects_query(
    principal: Principal,
    *,
    customer_id: uuid.UUID | None,
    stage: Stage | None,
    status: str | None,
    include_deleted: bool,
) -> Select[Project]:
    stmt = select(Project).where(project_visibility(principal)).order_by(Project.created_at.desc())
    if not include_deleted:
        stmt = stmt.where(Project.deleted_at.is_(None))
    if customer_id:
        stmt = stmt.where(Project.customer_id == customer_id)
    if stage:
        stmt = stmt.where(Project.current_stage == stage.value)
    if status:
        stmt = stmt.where(Project.status == status)
    return stmt


# ------------------------------------------------------------------ customers


async def create_customer(
    session: AsyncSession, principal: Principal, data: CustomerCreateIn
) -> Customer:
    if principal.is_customer:
        raise Forbidden()
    n = await next_value(session, "customer")
    c = Customer(
        code=f"CUS-{n:05d}",
        legal_name=data.legal_name,
        display_name=data.display_name or data.legal_name[:120],
        gstin=data.gstin,
        segment=data.segment,
        industry=data.industry,
        employee_count=data.employee_count,
        address_line1=data.address_line1,
        address_line2=data.address_line2,
        city=data.city,
        state=data.state,
        pincode=data.pincode,
        notes=data.notes,
        account_owner_id=data.account_owner_id or principal.user_id,
        created_by=principal.user_id,
    )
    await _ensure_gstin_free(session, data.gstin, None)
    session.add(c)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="create",
        entity_type="customer",
        entity_id=c.id,
        after=_snap(c, _CUSTOMER_FIELDS),
    )
    await session.commit()
    return c


async def _ensure_gstin_free(
    session: AsyncSession, gstin: str | None, exclude: uuid.UUID | None
) -> None:
    if not gstin:
        return
    stmt = select(Customer.id).where(Customer.gstin == gstin, Customer.deleted_at.is_(None))
    if exclude:
        stmt = stmt.where(Customer.id != exclude)
    if await session.scalar(stmt):
        raise Conflict("Another customer already has this GSTIN.", code="gstin_taken")


async def update_customer(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID, data: CustomerUpdateIn
) -> Customer:
    c = await get_customer(session, principal, customer_id)
    _check_version(c.version, data.version)
    before = _snap(c, _CUSTOMER_FIELDS)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "gstin" in changes:
        await _ensure_gstin_free(session, changes["gstin"], c.id)
    for k, v in changes.items():
        setattr(c, k, v)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="update",
        entity_type="customer",
        entity_id=c.id,
        before=before,
        after=_snap(c, _CUSTOMER_FIELDS),
    )
    await session.commit()
    return c


async def delete_customer(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID
) -> None:
    c = await get_customer(session, principal, customer_id)
    active = await session.scalar(
        select(Project.id).where(
            Project.customer_id == c.id,
            Project.deleted_at.is_(None),
            Project.status.in_(["active", "on_hold"]),
        )
    )
    if active:
        raise Conflict(
            "This customer has open projects. Close or delete them first.",
            code="customer_has_projects",
        )
    c.deleted_at = utcnow()
    await record(
        session,
        audit_context(principal),
        action="delete",
        entity_type="customer",
        entity_id=c.id,
        only_changes=False,
    )
    await session.commit()


async def restore_customer(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID
) -> Customer:
    c = await get_customer(session, principal, customer_id, include_deleted=True)
    if c.deleted_at is None:
        return c
    await _ensure_gstin_free(session, c.gstin, c.id)
    c.deleted_at = None
    await record(
        session,
        audit_context(principal),
        action="restore",
        entity_type="customer",
        entity_id=c.id,
        only_changes=False,
    )
    await session.commit()
    return c


# ------------------------------------------------------------------ sites and contacts


async def _unset_primary[M: (Site, Contact)](
    session: AsyncSession,
    model: type[M],
    customer_id: uuid.UUID,
    keep: uuid.UUID,
) -> None:
    rows = await session.scalars(
        select(model).where(
            model.customer_id == customer_id,
            model.is_primary.is_(True),
            model.id != keep,
            model.deleted_at.is_(None),
        )
    )
    for r in rows:
        r.is_primary = False


async def add_site(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID, data: SiteIn
) -> Site:
    c = await get_customer(session, principal, customer_id)
    site = Site(customer_id=c.id, **data.model_dump())
    session.add(site)
    await session.flush()
    if site.is_primary:
        await _unset_primary(session, Site, c.id, site.id)
    await record(
        session,
        audit_context(principal),
        action="create",
        entity_type="site",
        entity_id=site.id,
        after=_snap(site, _SITE_FIELDS),
    )
    await session.commit()
    return site


async def _get_child(
    session: AsyncSession,
    principal: Principal,
    model: type[Site] | type[Contact],
    customer_id: uuid.UUID,
    child_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> Any:
    await get_customer(session, principal, customer_id)
    stmt = select(model).where(model.id == child_id, model.customer_id == customer_id)
    if not include_deleted:
        stmt = stmt.where(model.deleted_at.is_(None))
    obj = await session.scalar(stmt)
    if obj is None:
        raise NotFound(f"{model.__name__} not found.")
    return obj


async def list_children(
    session: AsyncSession,
    principal: Principal,
    model: type[Site] | type[Contact],
    customer_id: uuid.UUID,
) -> list[Any]:
    await get_customer(session, principal, customer_id)
    rows = await session.scalars(
        select(model)
        .where(model.customer_id == customer_id, model.deleted_at.is_(None))
        .order_by(model.is_primary.desc(), model.created_at)
    )
    return list(rows)


async def update_site(
    session: AsyncSession,
    principal: Principal,
    customer_id: uuid.UUID,
    site_id: uuid.UUID,
    data: SiteUpdateIn,
) -> Site:
    site: Site = await _get_child(session, principal, Site, customer_id, site_id)
    _check_version(site.version, data.version)
    before = _snap(site, _SITE_FIELDS)
    for k, v in data.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(site, k, v)
    await session.flush()
    if site.is_primary:
        await _unset_primary(session, Site, customer_id, site.id)
    await record(
        session,
        audit_context(principal),
        action="update",
        entity_type="site",
        entity_id=site.id,
        before=before,
        after=_snap(site, _SITE_FIELDS),
    )
    await session.commit()
    return site


async def add_contact(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID, data: ContactIn
) -> Contact:
    c = await get_customer(session, principal, customer_id)
    if data.site_id:
        await _get_child(session, principal, Site, customer_id, data.site_id)
    contact = Contact(customer_id=c.id, **data.model_dump())
    session.add(contact)
    await session.flush()
    if contact.is_primary:
        await _unset_primary(session, Contact, c.id, contact.id)
    await record(
        session,
        audit_context(principal),
        action="create",
        entity_type="contact",
        entity_id=contact.id,
        after=_snap(contact, _CONTACT_FIELDS),
        subject_id=contact.id,
    )
    await session.commit()
    return contact


async def sign_off_contacts(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[Contact]:
    """People at the customer who may confirm an arrival or a hand over, best choice first:
    authorised sign-off contacts with an email, primary contact first."""
    project = await get_project(session, principal, project_id)
    rows = (
        await session.scalars(
            select(Contact).where(
                Contact.customer_id == project.customer_id,
                Contact.deleted_at.is_(None),
                Contact.email.is_not(None),
            )
        )
    ).all()
    return sorted(rows, key=lambda c: (not c.can_sign_off, not c.is_primary, c.full_name))


async def update_contact(
    session: AsyncSession,
    principal: Principal,
    customer_id: uuid.UUID,
    contact_id: uuid.UUID,
    data: ContactUpdateIn,
) -> Contact:
    contact: Contact = await _get_child(session, principal, Contact, customer_id, contact_id)
    _check_version(contact.version, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("site_id"):
        await _get_child(session, principal, Site, customer_id, changes["site_id"])
    before = _snap(contact, _CONTACT_FIELDS)
    for k, v in changes.items():
        setattr(contact, k, v)
    await session.flush()
    if contact.is_primary:
        await _unset_primary(session, Contact, customer_id, contact.id)
    await record(
        session,
        audit_context(principal),
        action="update",
        entity_type="contact",
        entity_id=contact.id,
        before=before,
        after=_snap(contact, _CONTACT_FIELDS),
        subject_id=contact.id,
    )
    await session.commit()
    return contact


async def soft_delete_child(
    session: AsyncSession,
    principal: Principal,
    model: type[Site] | type[Contact],
    customer_id: uuid.UUID,
    child_id: uuid.UUID,
) -> None:
    obj = await _get_child(session, principal, model, customer_id, child_id)
    if model is Site and await session.scalar(
        select(Project.id).where(Project.site_id == child_id, Project.deleted_at.is_(None))
    ):
        raise Conflict("Projects still use this site.", code="site_in_use")
    obj.deleted_at = utcnow()
    obj.is_primary = False
    await record(
        session,
        audit_context(principal),
        action="delete",
        entity_type=model.__name__.lower(),
        entity_id=child_id,
        only_changes=False,
    )
    await session.commit()


async def restore_child(
    session: AsyncSession,
    principal: Principal,
    model: type[Site] | type[Contact],
    customer_id: uuid.UUID,
    child_id: uuid.UUID,
) -> Any:
    obj = await _get_child(session, principal, model, customer_id, child_id, include_deleted=True)
    if obj.deleted_at is not None:
        obj.deleted_at = None
        await record(
            session,
            audit_context(principal),
            action="restore",
            entity_type=model.__name__.lower(),
            entity_id=child_id,
            only_changes=False,
        )
        await session.commit()
    return obj


# ------------------------------------------------------------------ projects


async def create_project(
    session: AsyncSession, principal: Principal, data: ProjectCreateIn
) -> Project:
    customer = await get_customer(session, principal, data.customer_id)
    if data.site_id:
        await _get_child(session, principal, Site, customer.id, data.site_id)
    fy = financial_year_code(today_ist())
    n = await next_value(session, f"project:{fy}")
    project = Project(
        code=f"P1-{fy}-{n:04d}",
        customer_id=customer.id,
        site_id=data.site_id,
        name=data.name,
        description=data.description,
        current_stage=Stage.AUDIT_INTAKE.value,
        status="active",
        created_by=principal.user_id,
    )
    session.add(project)
    await session.flush()
    creator_role = sorted(principal.roles)[0] if principal.roles else "member"
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=principal.user_id,
            project_role=str(creator_role),
            added_by=principal.user_id,
        )
    )
    await record(
        session,
        audit_context(principal),
        action="create",
        entity_type="project",
        entity_id=project.id,
        after=_snap(project, _PROJECT_FIELDS),
    )
    outbox.publish(
        session,
        DomainEvent(
            event_type="customers.project_created",
            aggregate_type="project",
            aggregate_id=str(project.id),
            actor_id=principal.user_id,
            payload={"code": project.code, "customer_id": str(customer.id)},
        ),
    )
    await session.commit()
    return project


async def update_project(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, data: ProjectUpdateIn
) -> Project:
    project = await get_project(session, principal, project_id)
    _check_version(project.version, data.version)
    if project.status in ("completed", "cancelled"):
        raise Conflict("Closed projects cannot be changed.", code="project_closed")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("site_id"):
        await _get_child(session, principal, Site, project.customer_id, changes["site_id"])
    before = _snap(project, _PROJECT_FIELDS)
    for k, v in changes.items():
        setattr(project, k, v)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="update",
        entity_type="project",
        entity_id=project.id,
        before=before,
        after=_snap(project, _PROJECT_FIELDS),
    )
    await session.commit()
    return project


async def delete_project(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> None:
    project = await get_project(session, principal, project_id)
    project.deleted_at = utcnow()
    await record(
        session,
        audit_context(principal),
        action="delete",
        entity_type="project",
        entity_id=project.id,
        only_changes=False,
    )
    await session.commit()


async def restore_project(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> Project:
    project = await get_project(session, principal, project_id, include_deleted=True)
    if project.deleted_at is not None:
        project.deleted_at = None
        await record(
            session,
            audit_context(principal),
            action="restore",
            entity_type="project",
            entity_id=project.id,
            only_changes=False,
        )
        await session.commit()
    return project


async def list_members(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[tuple[ProjectMember, str | None]]:
    await get_project(session, principal, project_id)
    rows = (
        await session.scalars(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.added_at)
        )
    ).all()
    out = []
    for m in rows:
        u = await get_user_summary(session, m.user_id)
        out.append((m, u.full_name if u else None))
    return out


async def add_member(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    project_role: Role,
) -> ProjectMember:
    project = await get_project(session, principal, project_id)
    user = await get_user_summary(session, user_id)
    if user is None or not user.is_active:
        raise ValidationFailed("That user does not exist or is inactive.")
    if project_role not in user.roles:
        raise ValidationFailed(
            "The user must hold this role to join the project in it.", code="role_not_held"
        )
    if Role.CUSTOMER_REP in user.roles:
        raise ValidationFailed("Customer representatives see their own projects automatically.")
    existing = await session.get(ProjectMember, (project.id, user_id))
    before = {"project_role": existing.project_role} if existing else None
    if existing:
        existing.project_role = project_role.value
        m = existing
    else:
        m = ProjectMember(
            project_id=project.id,
            user_id=user_id,
            project_role=project_role.value,
            added_by=principal.user_id,
        )
        session.add(m)
    await record(
        session,
        audit_context(principal),
        action="member_set",
        entity_type="project",
        entity_id=project.id,
        before=before,
        after={"user_id": str(user_id), "project_role": project_role.value},
    )
    await session.commit()
    return m


async def remove_member(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    project = await get_project(session, principal, project_id)
    m = await session.get(ProjectMember, (project.id, user_id))
    if m is None:
        raise NotFound("That person is not on this project.")
    await session.delete(m)
    await record(
        session,
        audit_context(principal),
        action="member_removed",
        entity_type="project",
        entity_id=project.id,
        before={"user_id": str(user_id), "project_role": m.project_role},
        only_changes=False,
    )
    await session.commit()


# ------------------------------------------------------------------ gates


async def gate_config(session: AsyncSession, stage: Stage) -> GateConfig:
    cfg = await session.get(GateConfig, stage.value)
    if cfg is None:
        d = GATE_DEFAULTS[stage]
        cfg = GateConfig(
            stage=stage.value,
            approver_roles=[r.value for r in d.approver_roles],
            artifact_type=d.artifact_type,
            requires_artifact=True,
            requires_customer_ack=d.requires_customer_ack,
        )
        session.add(cfg)
        await session.flush()
    return cfg


async def update_gate_config(
    session: AsyncSession,
    principal: Principal,
    stage: Stage,
    *,
    version: int,
    approver_roles: list[Role],
    requires_artifact: bool,
    requires_customer_ack: bool,
) -> GateConfig:
    cfg = await gate_config(session, stage)
    _check_version(cfg.version, version)
    before = {
        "approver_roles": list(cfg.approver_roles),
        "requires_artifact": cfg.requires_artifact,
        "requires_customer_ack": cfg.requires_customer_ack,
    }
    cfg.approver_roles = sorted({r.value for r in approver_roles})
    cfg.requires_artifact = requires_artifact
    cfg.requires_customer_ack = requires_customer_ack
    cfg.updated_by = principal.user_id
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="update",
        entity_type="gate_config",
        entity_id=stage.value,
        before=before,
        after={
            "approver_roles": cfg.approver_roles,
            "requires_artifact": requires_artifact,
            "requires_customer_ack": requires_customer_ack,
        },
    )
    await session.commit()
    return cfg


async def record_artifact(session: AsyncSession, event: DomainEvent) -> None:
    """Outbox handler: a module locked an output that a stage gate can approve."""
    p = event.payload
    if await session.scalar(
        select(StageArtifact.id).where(StageArtifact.source_event_id == event.event_id)
    ):
        return  # already recorded (handlers are retried)
    project = await session.get(Project, uuid.UUID(p["project_id"]))
    if project is None:
        raise ValueError(f"artifact for unknown project {p['project_id']}")
    session.add(
        StageArtifact(
            project_id=project.id,
            stage=Stage(p["stage"]).value,
            artifact_type=p["artifact_type"],
            artifact_id=str(p["artifact_id"]),
            artifact_version=int(p.get("artifact_version", 1)),
            title=str(p.get("title", p["artifact_type"]))[:250],
            locked_by=uuid.UUID(p["locked_by"]) if p.get("locked_by") else None,
            locked_at=event.occurred_at,
            source_event_id=event.event_id,
        )
    )
    await record(
        session,
        AuditContext.system("outbox"),
        action="artifact_recorded",
        entity_type="project",
        entity_id=project.id,
        after={k: p.get(k) for k in ("stage", "artifact_type", "artifact_id", "artifact_version")},
        only_changes=False,
    )


async def list_artifacts(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[StageArtifact]:
    await get_project(session, principal, project_id)
    return list(
        (
            await session.scalars(
                select(StageArtifact)
                .where(StageArtifact.project_id == project_id)
                .order_by(StageArtifact.locked_at.desc())
            )
        ).all()
    )


async def submit_stage(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    stage: Stage,
    note: str | None,
    artifact_id: uuid.UUID | None,
) -> StageSubmission:
    project = await get_project(session, principal, project_id)
    await session.refresh(project, with_for_update=True)
    if project.status != "active":
        raise Conflict("Only active projects can move through gates.", code="project_not_active")
    if project.current_stage != stage.value:
        raise Conflict(
            f"This project is at the {STAGE_LABELS[Stage(project.current_stage)]} stage.",
            code="wrong_stage",
        )
    if await session.scalar(
        select(StageSubmission.id).where(
            StageSubmission.project_id == project.id,
            StageSubmission.stage == stage.value,
            StageSubmission.status == "pending",
        )
    ):
        raise Conflict("This stage already waits for approval.", code="submission_pending")
    cfg = await gate_config(session, stage)
    artifact: StageArtifact | None = None
    if cfg.requires_artifact:
        if artifact_id is None:
            raise ValidationFailed(
                "Choose the locked output this gate approves.", code="artifact_required"
            )
        artifact = await session.scalar(
            select(StageArtifact).where(
                StageArtifact.id == artifact_id, StageArtifact.project_id == project.id
            )
        )
        if (
            artifact is None
            or artifact.stage != stage.value
            or artifact.artifact_type != cfg.artifact_type
        ):
            raise ValidationFailed(
                f"This gate needs a locked {cfg.artifact_type} for this project and stage.",
                code="artifact_mismatch",
            )
    sub = StageSubmission(
        project_id=project.id,
        stage=stage.value,
        submitted_by=principal.user_id,
        note=note,
        artifact_id=artifact.id if artifact else None,
        requires_customer_ack=cfg.requires_customer_ack,
    )
    session.add(sub)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="gate_submitted",
        entity_type="project",
        entity_id=project.id,
        after={
            "stage": stage.value,
            "submission_id": str(sub.id),
            "artifact_id": str(sub.artifact_id) if sub.artifact_id else None,
        },
        only_changes=False,
    )
    outbox.publish(
        session,
        DomainEvent(
            event_type="customers.gate_submitted",
            aggregate_type="project",
            aggregate_id=str(project.id),
            actor_id=principal.user_id,
            payload={"stage": stage.value, "submission_id": str(sub.id)},
        ),
    )
    await session.commit()
    return sub


async def _pending_submission(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, submission_id: uuid.UUID
) -> tuple[Project, StageSubmission]:
    project = await get_project(session, principal, project_id)
    sub = await session.scalar(
        select(StageSubmission)
        .where(StageSubmission.id == submission_id, StageSubmission.project_id == project.id)
        .with_for_update()
    )
    if sub is None:
        raise NotFound("Submission not found.")
    if sub.status != "pending":
        raise Conflict(f"This submission is already {sub.status}.", code="submission_closed")
    return project, sub


async def _check_approver(
    session: AsyncSession, principal: Principal, sub: StageSubmission
) -> GateConfig:
    cfg = await gate_config(session, Stage(sub.stage))
    if not ({r.value for r in principal.roles} & set(cfg.approver_roles)):
        raise Forbidden("Your role cannot approve this gate.", code="not_gate_approver")
    ensure_different_people(sub.submitted_by, principal.user_id, "submission")
    if sub.artifact_id:
        artifact = await session.get(StageArtifact, sub.artifact_id)
        if artifact:
            ensure_different_people(artifact.locked_by, principal.user_id, "work")
    return cfg


async def approve(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    submission_id: uuid.UUID,
    comment: str | None,
) -> GateDecision:
    project, sub = await _pending_submission(session, principal, project_id, submission_id)
    await _check_approver(session, principal, sub)
    if sub.requires_customer_ack and sub.customer_ack_at is None:
        raise Conflict(
            "The customer has not acknowledged this stage yet.", code="customer_ack_missing"
        )
    await session.refresh(project, with_for_update=True)
    if project.current_stage != sub.stage or project.status != "active":
        raise Conflict("The project moved on since this was submitted.", code="wrong_stage")
    artifact = await session.get(StageArtifact, sub.artifact_id) if sub.artifact_id else None
    decision = GateDecision(
        project_id=project.id,
        submission_id=sub.id,
        stage=sub.stage,
        decision="approved",
        decided_by=principal.user_id,
        decided_by_name=principal.full_name,
        decided_by_roles=sorted(r.value for r in principal.roles),
        decided_at=utcnow(),
        comment=comment,
        artifact_type=artifact.artifact_type if artifact else None,
        artifact_ref=artifact.artifact_id if artifact else None,
        artifact_version=artifact.artifact_version if artifact else None,
    )
    session.add(decision)
    sub.status = "approved"
    before_stage = project.current_stage
    nxt = next_stage(Stage(sub.stage))
    if nxt is None:
        project.status = "completed"
    else:
        project.current_stage = nxt.value
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="gate_approved",
        entity_type="project",
        entity_id=project.id,
        before={"current_stage": before_stage},
        after={
            "current_stage": project.current_stage,
            "status": project.status,
            "submission_id": str(sub.id),
            "stage": sub.stage,
        },
        only_changes=False,
    )
    outbox.publish(
        session,
        DomainEvent(
            event_type=GATE_APPROVED,
            aggregate_type="project",
            aggregate_id=str(project.id),
            actor_id=principal.user_id,
            payload={
                "stage": sub.stage,
                "next_stage": nxt.value if nxt else None,
                "decision_id": str(decision.id),
                "artifact_type": decision.artifact_type,
                "artifact_ref": decision.artifact_ref,
                "artifact_version": decision.artifact_version,
            },
        ),
    )
    await session.commit()
    return decision


async def reject(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    submission_id: uuid.UUID,
    comment: str,
) -> GateDecision:
    project, sub = await _pending_submission(session, principal, project_id, submission_id)
    await _check_approver(session, principal, sub)
    decision = GateDecision(
        project_id=project.id,
        submission_id=sub.id,
        stage=sub.stage,
        decision="rejected",
        decided_by=principal.user_id,
        decided_by_name=principal.full_name,
        decided_by_roles=sorted(r.value for r in principal.roles),
        decided_at=utcnow(),
        comment=comment,
    )
    session.add(decision)
    sub.status = "rejected"
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="gate_rejected",
        entity_type="project",
        entity_id=project.id,
        after={"stage": sub.stage, "submission_id": str(sub.id), "comment": comment},
        only_changes=False,
    )
    outbox.publish(
        session,
        DomainEvent(
            event_type=GATE_REJECTED,
            aggregate_type="project",
            aggregate_id=str(project.id),
            actor_id=principal.user_id,
            payload={"stage": sub.stage, "decision_id": str(decision.id)},
        ),
    )
    await session.commit()
    return decision


async def withdraw(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, submission_id: uuid.UUID
) -> StageSubmission:
    project, sub = await _pending_submission(session, principal, project_id, submission_id)
    if sub.submitted_by != principal.user_id:
        raise Forbidden("Only the person who submitted can withdraw.", code="not_submitter")
    sub.status = "withdrawn"
    await record(
        session,
        audit_context(principal),
        action="gate_withdrawn",
        entity_type="project",
        entity_id=project.id,
        after={"submission_id": str(sub.id)},
        only_changes=False,
    )
    await session.commit()
    return sub


async def tracker(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> tuple[Project, dict[str, GateDecision], dict[str, StageSubmission]]:
    project = await get_project(session, principal, project_id)
    decisions = (
        await session.scalars(
            select(GateDecision).where(
                GateDecision.project_id == project.id, GateDecision.decision == "approved"
            )
        )
    ).all()
    pending = (
        await session.scalars(
            select(StageSubmission).where(
                StageSubmission.project_id == project.id, StageSubmission.status == "pending"
            )
        )
    ).all()
    return project, {d.stage: d for d in decisions}, {s.stage: s for s in pending}


async def history(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> tuple[list[StageSubmission], list[GateDecision]]:
    await get_project(session, principal, project_id)
    subs = (
        await session.scalars(
            select(StageSubmission)
            .where(StageSubmission.project_id == project_id)
            .order_by(StageSubmission.created_at)
        )
    ).all()
    decs = (
        await session.scalars(
            select(GateDecision)
            .where(GateDecision.project_id == project_id)
            .order_by(GateDecision.decided_at)
        )
    ).all()
    return list(subs), list(decs)


# ------------------------------------------------------------------ customer acknowledgement


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_ack(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    submission_id: uuid.UUID,
    contact_id: uuid.UUID,
    valid_hours: int,
) -> tuple[CustomerAck, str]:
    project, sub = await _pending_submission(session, principal, project_id, submission_id)
    if not sub.requires_customer_ack:
        raise Conflict("This gate does not need customer acknowledgement.", code="ack_not_required")
    contact = await session.scalar(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.customer_id == project.customer_id,
            Contact.deleted_at.is_(None),
        )
    )
    if contact is None:
        raise ValidationFailed("Choose a contact of this customer.")
    if not contact.can_sign_off:
        raise ValidationFailed(
            "This contact is not allowed to sign off. Mark them as a sign-off contact first.",
            code="contact_cannot_sign_off",
        )
    token = secrets.token_urlsafe(32)
    now = utcnow()
    ack = CustomerAck(
        submission_id=sub.id,
        contact_id=contact.id,
        token_hash=_hash(token),
        issued_by=principal.user_id,
        issued_at=now,
        expires_at=now + timedelta(hours=valid_hours),
    )
    session.add(ack)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="customer_ack_issued",
        entity_type="project",
        entity_id=project.id,
        after={"submission_id": str(sub.id), "contact_id": str(contact.id), "ack_id": str(ack.id)},
        only_changes=False,
    )
    await session.commit()
    return ack, f"{get_settings().public_base_url}/ack/{token}"


async def _ack_by_token(
    session: AsyncSession, token: str, *, lock: bool = False
) -> tuple[CustomerAck, StageSubmission, Project, Contact]:
    stmt = select(CustomerAck).where(CustomerAck.token_hash == _hash(token))
    if lock:
        stmt = stmt.with_for_update()
    ack = await session.scalar(stmt)
    if ack is None or ack.expires_at <= utcnow():
        raise NotFound(
            "This link is not valid or has expired. Ask ITCraft for a new one.",
            code="ack_link_invalid",
        )
    sub = await session.get(StageSubmission, ack.submission_id)
    contact = await session.get(Contact, ack.contact_id)
    project = await session.get(Project, sub.project_id) if sub else None
    if sub is None or project is None or contact is None:
        raise NotFound(
            "This link is not valid or has expired. Ask ITCraft for a new one.",
            code="ack_link_invalid",
        )
    return ack, sub, project, contact


async def view_ack(session: AsyncSession, token: str) -> dict[str, Any]:
    ack, sub, project, contact = await _ack_by_token(session, token)
    customer = await session.get(Customer, project.customer_id)
    return {
        "customer_name": customer.legal_name if customer else "",
        "project_name": project.name,
        "stage_label": STAGE_LABELS[Stage(sub.stage)],
        "contact_name": contact.full_name,
        "expires_at": ack.expires_at,
        "already_acknowledged": ack.acknowledged_at is not None or sub.customer_ack_at is not None,
    }


async def confirm_ack(
    session: AsyncSession, token: str, typed_name: str, ip: str | None, user_agent: str | None
) -> None:
    ack, sub, project, contact = await _ack_by_token(session, token, lock=True)
    if ack.acknowledged_at is not None:
        return  # single use; repeating is harmless
    if sub.status != "pending":
        raise Conflict(
            "This stage is no longer waiting for your acknowledgement.", code="submission_closed"
        )
    now = utcnow()
    ack.acknowledged_at = now
    ack.acknowledged_name = typed_name
    ack.ip = ip
    ack.user_agent = (user_agent or "")[:400] or None
    sub.customer_ack_at = now
    await record(
        session,
        AuditContext(
            actor_id=None,
            actor_label=f"customer contact {contact.id}",
            ip=ip,
            user_agent=user_agent,
        ),
        action="customer_acknowledged",
        entity_type="project",
        entity_id=project.id,
        after={"submission_id": str(sub.id), "ack_id": str(ack.id), "typed_name": typed_name},
        subject_id=contact.id,
        only_changes=False,
    )
    outbox.publish(
        session,
        DomainEvent(
            event_type="customers.customer_acknowledged",
            aggregate_type="project",
            aggregate_id=str(project.id),
            payload={"stage": sub.stage, "submission_id": str(sub.id)},
        ),
    )
    await session.commit()


# ------------------------------------------------------------------ brief


async def get_brief(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> ProjectBrief | None:
    await get_project(session, principal, project_id)
    return await session.get(ProjectBrief, project_id)


async def upsert_brief(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, body: BriefIn
) -> ProjectBrief:
    principal.require(P.PROJECT_WRITE)
    project = await get_project(session, principal, project_id)
    brief = await session.get(ProjectBrief, project.id)
    data = body.model_dump(exclude={"version"})
    before: dict[str, Any] | None
    if brief is None:
        brief = ProjectBrief(project_id=project.id, updated_by=principal.user_id, **data)
        session.add(brief)
        before = None
    else:
        if body.version != brief.version:
            raise StaleVersion()
        before = {k: getattr(brief, k) for k in data}
        for k, v in data.items():
            setattr(brief, k, v)
        brief.updated_by = principal.user_id
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="brief_saved",
        entity_type="project",
        entity_id=project.id,
        before={k: str(v) for k, v in before.items()} if before else None,
        after={k: str(v) for k, v in data.items()},
    )
    await session.commit()
    await session.refresh(brief)
    return brief


# ------------------------------------------------------------------ return to an earlier stage

STAGE_RETURNED = "customers.stage_returned"


async def return_to_stage(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, target: Stage, reason: str
) -> Project:
    """A disputed gap goes back to gap analysis; a customer change sends the BOQ back. Anyone
    who may approve gates can do it, with a reason. Approved outputs stay as history; the stage
    needs a new locked output and a new approval."""
    principal.require(P.GATE_APPROVE)
    project = await get_project(session, principal, project_id)
    await session.refresh(project, with_for_update=True)
    if project.status != "active":
        raise Conflict("Only active projects can be moved.", code="project_not_active")
    cur = Stage(project.current_stage)
    if STAGE_ORDER.index(target) >= STAGE_ORDER.index(cur):
        raise ValidationFailed("Choose an earlier stage than the current one.", code="not_earlier")
    pending = await session.scalars(
        select(StageSubmission).where(
            StageSubmission.project_id == project.id, StageSubmission.status == "pending"
        )
    )
    for sub in pending:
        sub.status = "withdrawn"
    project.current_stage = target.value
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="stage_returned",
        entity_type="project",
        entity_id=project.id,
        before={"current_stage": cur.value},
        after={"current_stage": target.value, "reason": reason},
        only_changes=False,
    )
    outbox.publish(
        session,
        DomainEvent(
            event_type=STAGE_RETURNED,
            aggregate_type="project",
            aggregate_id=str(project.id),
            actor_id=principal.user_id,
            payload={"from": cur.value, "to": target.value, "reason": reason},
        ),
    )
    await session.commit()
    await session.refresh(project)
    return project
