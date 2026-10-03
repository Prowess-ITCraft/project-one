from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
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

# The life of one task in the field, in order (ADR 0015). `blocked` can interrupt any working
# state and returns to the state it came from.
FLOW = (
    "assigned",
    "accepted",
    "checked_in",
    "prechecks_done",
    "configured",
    "evidence_uploaded",
    "engine_check",
    "verifier_review",
    "closed",
)
STATES = (*FLOW, "blocked")

# Which evidence belongs to which part of the visit.
EVIDENCE_STAGES = ("check_in", "prechecks", "work")


class TaskRun(UUIDPk, Timestamps, Versioned, Base):
    """One planned task being carried out. Steps, evidence rules and the target configuration are
    copied from the locked plan, so later library changes never alter work already in progress."""

    __tablename__ = "task_runs"
    __table_args__ = (
        UniqueConstraint("plan_id", "task_ref", name="uq_task_runs_task"),
        Index("ix_task_runs_project_state", "project_id", "state"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    task_ref: Mapped[str] = mapped_column(String(12), nullable=False)
    kind: Mapped[str] = mapped_column(String(41), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    asset: Mapped[str | None] = mapped_column(String(200))
    device_type: Mapped[str | None] = mapped_column(String(20))
    requires_downtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    depends_on: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_reqs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    baseline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    actuals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    assignee_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    planned_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planned_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="assigned")
    blocked_from: Mapped[str | None] = mapped_column(String(20))
    block_reason: Mapped[str | None] = mapped_column(String(500))
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handed_over_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column()
    last_check_passed: Mapped[bool | None] = mapped_column(Boolean)
    rework_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RunEvent(Base):
    """Everything that happens to a run, in order. Append only: the database refuses changes.
    `seq` is the cursor for live updates."""

    __tablename__ = "run_events"
    __table_args__ = (
        Index(
            "uq_run_events_client",
            "run_id",
            "client_event_id",
            unique=True,
            postgresql_where=text("client_event_id IS NOT NULL"),
        ),
        Index("ix_run_events_project_seq", "project_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_event_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(20))
    to_state: Mapped[str | None] = mapped_column(String(20))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)


class RunEvidence(UUIDPk, Base):
    """A photo, screenshot, configuration export, serial number or note. Append only."""

    __tablename__ = "run_evidence"
    __table_args__ = (
        UniqueConstraint("run_id", "client_id", name="uq_run_evidence_client"),
        Index("ix_run_evidence_run_req", "run_id", "requirement_index"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    requirement_index: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(14), nullable=False)
    file_id: Mapped[uuid.UUID | None] = mapped_column()
    text_value: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RunCheck(UUIDPk, Base):
    """One engine check of actual against target configuration. Append only."""

    __tablename__ = "run_checks"
    __table_args__ = (Index("ix_run_checks_run", "run_id", "attempt"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    driver: Mapped[str] = mapped_column(String(40), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deviations: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_open: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OtpChallenge(UUIDPk, Base):
    """A one-time code sent to a customer contact. Only a salted hash is kept."""

    __tablename__ = "otp_challenges"
    __table_args__ = (Index("ix_otp_run_purpose", "run_id", "purpose"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(10), nullable=False)  # check_in | handover
    contact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sent_to: Mapped[str] = mapped_column(String(254), nullable=False)  # masked
    salt: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
