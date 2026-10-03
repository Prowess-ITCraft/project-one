from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
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

COMPONENTS = (
    "endpoint",
    "server",
    "firewall",
    "nas",
    "switch",
    "router",
    "access_point",
    "general",
)
LENSES = ("productivity", "resilience", "security", "health")
PRIORITIES = ("high", "consider")


class InfraRule(UUIDPk, Timestamps, Versioned, Base):
    """One rule of the ideal-infra library. Changes go through a Director-approved change
    request; `version` counts applied changes, and every gap records the version it used."""

    __tablename__ = "infra_rules"
    __table_args__ = (
        Index("uq_infra_rules_code", "code", unique=True),
        CheckConstraint("priority IN ('high','consider')", name="priority_valid"),
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    component: Mapped[str] = mapped_column(String(20), nullable=False)
    lens: Mapped[str] = mapped_column(String(12), nullable=False)
    gap_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="consider")
    priority_overrides: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    when: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verify_if_unknown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    affected_list: Mapped[str | None] = mapped_column(String(60))
    qty_fact: Mapped[str | None] = mapped_column(String(60))
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    company_sizes: Mapped[list[str]] = mapped_column(
        ARRAY(String(10)), nullable=False, default=list
    )
    budget_tiers: Mapped[list[str]] = mapped_column(ARRAY(String(12)), nullable=False, default=list)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RuleChange(UUIDPk, Base):
    """A proposed change to the rule library. The Director decides; the proposer never does."""

    __tablename__ = "infra_rule_changes"

    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("infra_rules.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # create | update | deactivate
    proposed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    submitted_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InfraState(UUIDPk, Base):
    """A project's current-state baseline or ideal-state specification. Drafts can be rebuilt;
    a locked state is the output a stage gate approves and never changes."""

    __tablename__ = "infra_states"
    __table_args__ = (UniqueConstraint("project_id", "kind", "number"),)

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # current | ideal
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="draft"
    )  # draft | locked | superseded
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_import_id: Mapped[uuid.UUID | None] = mapped_column()
    rule_versions: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    locked_by: Mapped[uuid.UUID | None] = mapped_column()
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GapRegister(UUIDPk, Timestamps, Versioned, Base):
    __tablename__ = "gap_registers"
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    source_state_id: Mapped[uuid.UUID | None] = mapped_column()
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rule_versions: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    locked_by: Mapped[uuid.UUID | None] = mapped_column()
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Gap(UUIDPk, Timestamps, Versioned, Base):
    """One difference between current and ideal, or one thing to verify on site."""

    __tablename__ = "gaps"
    __table_args__ = (
        UniqueConstraint("register_id", "number"),
        CheckConstraint("priority IN ('high','consider')", name="priority_valid"),
        CheckConstraint(
            "status IN ('open','verify','accepted','disputed','dismissed')", name="status_valid"
        ),
    )

    register_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gap_registers.id"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_code: Mapped[str | None] = mapped_column(String(40))
    rule_version: Mapped[int | None] = mapped_column(Integer)
    gap_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(20), nullable=False)
    lens: Mapped[str] = mapped_column(String(12), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="rule")  # rule | manual
    affected: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    qty_hint: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recommendation: Mapped[str | None] = mapped_column(Text)
    last_change_reason: Mapped[str | None] = mapped_column(String(500))
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
