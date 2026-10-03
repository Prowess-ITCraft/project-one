from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, Versioned

SEVERITIES = ("critical", "major", "minor")
DEVIATION_STATUSES = ("open", "resolved", "accepted", "waived")


class Deviation(UUIDPk, Timestamps, Base):
    """A setting found different from its target. Opened by a failed check (or by a verifier),
    closed by a passing re-check, accepted with a reason, or waived with the customer's
    acknowledgement. Never deleted."""

    __tablename__ = "deviations"
    __table_args__ = (
        Index(
            "uq_deviations_open",
            "run_id",
            "field_key",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_deviations_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    task_ref: Mapped[str] = mapped_column(String(12), nullable=False)
    device: Mapped[str | None] = mapped_column(String(200))
    field_key: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    expected: Mapped[str | None] = mapped_column(String(300))
    actual: Mapped[str | None] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # check | verifier
    opened_by: Mapped[uuid.UUID | None] = mapped_column()
    opened_attempt: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column()
    resolution: Mapped[str | None] = mapped_column(Text)


class BrandFieldMap(UUIDPk, Timestamps, Versioned, Base):
    """Which key in a brand's configuration export proves a target setting, and the rule that
    judges it. Data, not code: confirmed against a real export, then marked verified."""

    __tablename__ = "brand_field_maps"
    __table_args__ = (UniqueConstraint("brand", "field_key", name="uq_brand_field_maps"),)

    brand: Mapped[str] = mapped_column(String(30), nullable=False)
    device_type: Mapped[str] = mapped_column(String(20), nullable=False)
    field_key: Mapped[str] = mapped_column(String(60), nullable=False)
    keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(500))


class VerificationSetting(Base):
    """Small editable policies, such as which severities block the certificate."""

    __tablename__ = "verification_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
