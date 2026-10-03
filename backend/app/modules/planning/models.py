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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, Versioned

PLAN_STATUSES = ("draft", "baselined", "superseded")


class TaskTemplate(UUIDPk, Timestamps, Versioned, Base):
    """How one kind of BOQ line turns into field work. Keyed by the BOQ template line key."""

    __tablename__ = "plan_task_templates"
    __table_args__ = (Index("uq_plan_task_templates_key", "key", unique=True),)

    key: Mapped[str] = mapped_column(String(41), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    minutes_fixed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minutes_per_unit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    split_per_unit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_downtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    device_type: Mapped[str | None] = mapped_column(String(20))
    depends_on_kinds: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    steps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()


class ConfigTemplate(UUIDPk, Timestamps, Versioned, Base):
    """The settings that matter for one device type. Copied into each plan as the target."""

    __tablename__ = "plan_config_templates"
    __table_args__ = (Index("uq_plan_config_templates_type", "device_type", unique=True),)

    device_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()


class Plan(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_plans_project_number"),
        Index(
            "uq_plans_one_active",
            "project_id",
            unique=True,
            postgresql_where=text("status <> 'superseded'"),
        ),
        CheckConstraint("status IN ('draft','baselined','superseded')", name="status_valid"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
    boq_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    boq_quote_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    baselined_by: Mapped[uuid.UUID | None] = mapped_column()
    baselined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanTask(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "plan_tasks"
    __table_args__ = (UniqueConstraint("plan_id", "ref", name="uq_plan_tasks_ref"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ref: Mapped[str] = mapped_column(String(12), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(41), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    boq_line_ref: Mapped[str | None] = mapped_column(String(12))
    asset: Mapped[str | None] = mapped_column(String(200))
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    depends_on: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requires_downtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    device_type: Mapped[str | None] = mapped_column(String(20))
    steps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="template")
    last_change_reason: Mapped[str | None] = mapped_column(String(300))


class ConfigBaseline(UUIDPk, Timestamps, Versioned, Base):
    """The target configuration for one device, the yardstick for verification (phase 9)."""

    __tablename__ = "plan_config_baselines"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_ref: Mapped[str | None] = mapped_column(String(12))
    device_type: Mapped[str] = mapped_column(String(20), nullable=False)
    device_label: Mapped[str] = mapped_column(String(200), nullable=False)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class EngineerLeave(UUIDPk, Timestamps, Base):
    __tablename__ = "engineer_leaves"
    __table_args__ = (CheckConstraint("date_to >= date_from", name="range_valid"),)

    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)


class DowntimeWindow(UUIDPk, Timestamps, Base):
    """A period the customer allows systems to be offline."""

    __tablename__ = "downtime_windows"
    __table_args__ = (CheckConstraint("end_at > start_at", name="range_valid"),)

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
