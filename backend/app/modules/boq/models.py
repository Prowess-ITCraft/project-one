from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, Versioned

STAGES = ("drafting", "pricing_review", "pricing_approved")
STATUSES = ("draft", "accepted", "closed")


class BoqTemplate(UUIDPk, Timestamps, Versioned, Base):
    """What a gap turns into: product and service lines with a quantity rule each. One active
    template per gap type. Admin and the sales head edit them; every change is audited."""

    __tablename__ = "boq_templates"
    __table_args__ = (Index("uq_boq_templates_gap_type", "gap_type", unique=True),)

    gap_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()


class RecoWeights(Timestamps, Base):
    """Recommendation weights per customer segment. Admin edits them."""

    __tablename__ = "reco_weights"

    segment: Mapped[str] = mapped_column(
        String(12), primary_key=True
    )  # micro | small | medium | large | default
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()


class CompanySettings(Timestamps, Versioned, Base):
    """Letterhead, default terms and signature for the quotation. One row, key `company`."""

    __tablename__ = "company_settings"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()


class Boq(UUIDPk, Timestamps, Versioned, Base):
    """The working BOQ of a project. `draft` is edited in place (each edit logged with its
    reason); issuing copies it into an immutable version."""

    __tablename__ = "boqs"
    __table_args__ = (
        Index("uq_boqs_project", "project_id", unique=True),
        CheckConstraint(
            "stage IN ('drafting','pricing_review','pricing_approved')", name="stage_valid"
        ),
        CheckConstraint("status IN ('draft','accepted','closed')", name="status_valid"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    stage: Mapped[str] = mapped_column(String(18), nullable=False, default="drafting")
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_register_id: Mapped[uuid.UUID | None] = mapped_column()
    generation_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    quote_ref: Mapped[str | None] = mapped_column(String(40), unique=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column()
    pricing_approved_by: Mapped[uuid.UUID | None] = mapped_column()
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)


class BoqVersion(UUIDPk, Base):
    """An issued BOQ: immutable. The version the customer accepts is locked and drives planning."""

    __tablename__ = "boq_versions"
    __table_args__ = (
        UniqueConstraint("boq_id", "number"),
        CheckConstraint("state IN ('issued','accepted','superseded')", name="state_valid"),
    )

    boq_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boqs.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="issued")
    quote_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_summary: Mapped[str] = mapped_column(String(400), nullable=False)
    delta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    issued_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    pricing_approved_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    selected_options: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    po_number: Mapped[str | None] = mapped_column(String(60))
    po_date: Mapped[date | None] = mapped_column(Date)
    po_file_id: Mapped[uuid.UUID | None] = mapped_column()
    accepted_by: Mapped[uuid.UUID | None] = mapped_column()
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_note: Mapped[str | None] = mapped_column(Text)


class BoqEdit(UUIDPk, Base):
    """Every change to a draft: who, what, why. The audit log holds the same, chained."""

    __tablename__ = "boq_edits"

    boq_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boqs.id"), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    draft_rev: Mapped[int] = mapped_column(Integer, nullable=False)
