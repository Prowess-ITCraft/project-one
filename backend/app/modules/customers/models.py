from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDelete, Timestamps, UUIDPk, Versioned


class Customer(UUIDPk, Timestamps, SoftDelete, Versioned, Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("uq_customers_code", "code", unique=True),
        Index(
            "uq_customers_gstin_active",
            "gstin",
            unique=True,
            postgresql_where="deleted_at IS NULL AND gstin IS NOT NULL",
        ),
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(250), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15))
    segment: Mapped[str] = mapped_column(String(20), nullable=False, default="small")
    industry: Mapped[str | None] = mapped_column(String(120))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    address_line1: Mapped[str] = mapped_column(String(250), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(250))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    pincode: Mapped[str] = mapped_column(String(6), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    notes: Mapped[str | None] = mapped_column(Text)
    account_owner_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column()


class Site(UUIDPk, Timestamps, SoftDelete, Versioned, Base):
    __tablename__ = "customer_sites"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address_line1: Mapped[str] = mapped_column(String(250), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(250))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    pincode: Mapped[str] = mapped_column(String(6), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Contact(UUIDPk, Timestamps, SoftDelete, Versioned, Base):
    __tablename__ = "customer_contacts"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_sites.id"))
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_sign_off: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Project(UUIDPk, Timestamps, SoftDelete, Versioned, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("uq_projects_code", "code", unique=True),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_sites.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    current_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column()


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, index=True)
    project_role: Mapped[str] = mapped_column(String(40), nullable=False)
    added_by: Mapped[uuid.UUID | None] = mapped_column()
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectBrief(Timestamps, Versioned, Base):
    """The intake questionnaire: what the customer wants and can spend. It picks the tier of the
    ideal-infra rules and steers the recommender and the BOQ."""

    __tablename__ = "project_briefs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    company_size: Mapped[str] = mapped_column(String(10), nullable=False, default="small")
    budget_tier: Mapped[str] = mapped_column(String(12), nullable=False, default="standard")
    users_now: Mapped[int | None] = mapped_column(Integer)
    users_12m: Mapped[int | None] = mapped_column(Integer)
    sites: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    preferred_brands: Mapped[list[str]] = mapped_column(
        ARRAY(String(80)), nullable=False, default=list
    )
    excluded_brands: Mapped[list[str]] = mapped_column(
        ARRAY(String(80)), nullable=False, default=list
    )
    budget_ceiling: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    category_budgets: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    keep_assets: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    compliance: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()


class GateConfig(Timestamps, Versioned, Base):
    __tablename__ = "stage_gate_configs"

    stage: Mapped[str] = mapped_column(String(40), primary_key=True)
    approver_roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    artifact_type: Mapped[str | None] = mapped_column(String(60))
    requires_artifact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_customer_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()


class StageArtifact(UUIDPk, Base):
    """A locked output that a stage's gate can approve. Written when the owning module locks it."""

    __tablename__ = "stage_artifacts"
    __table_args__ = (
        UniqueConstraint("project_id", "artifact_type", "artifact_id", "artifact_version"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(60), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(80), nullable=False)
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    locked_by: Mapped[uuid.UUID | None] = mapped_column()
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)


class StageSubmission(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "stage_submissions"
    __table_args__ = (
        Index(
            "uq_stage_submissions_pending",
            "project_id",
            "stage",
            unique=True,
            postgresql_where="status = 'pending'",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    submitted_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stage_artifacts.id"))
    requires_customer_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    customer_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GateDecision(UUIDPk, Base):
    """Approval record. Rows are never updated; a later change is a new submission."""

    __tablename__ = "gate_decisions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stage_submissions.id"), nullable=False, unique=True
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decided_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by_roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    artifact_type: Mapped[str | None] = mapped_column(String(60))
    artifact_ref: Mapped[str | None] = mapped_column(String(80))
    artifact_version: Mapped[int | None] = mapped_column(Integer)


class CustomerAck(UUIDPk, Base):
    """Signed, single-use link for a customer to acknowledge a stage (walkthrough, sign-off)."""

    __tablename__ = "customer_acks"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stage_submissions.id"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_contacts.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_name: Mapped[str | None] = mapped_column(String(200))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))
