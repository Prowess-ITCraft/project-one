from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, Versioned

WAIVER_KINDS = ("not_applicable", "deferred_by_customer")
WAIVER_STATUSES = ("requested", "approved", "acknowledged", "rejected")


class Waiver(UUIDPk, Timestamps, Versioned, Base):
    """Permission to leave a task undone, or a deviation open, at completion. Approved by the
    Director, then acknowledged by the customer through an emailed link. Printed on the
    certificate as an exclusion."""

    __tablename__ = "waivers"
    __table_args__ = (Index("ix_waivers_project_status", "project_id", "status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)  # task | deviation
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_label: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(25), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="requested")
    requested_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    contact_id: Mapped[uuid.UUID | None] = mapped_column()
    sent_to: Mapped[str | None] = mapped_column(String(254))  # masked
    ack_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    ack_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_name: Mapped[str | None] = mapped_column(String(200))
    acknowledged_ip: Mapped[str | None] = mapped_column(INET)


class CompletionReport(UUIDPk, Base):
    """A locked completion report: the content as it was when locked, and its PDF. A change
    means a new number; old reports stay."""

    __tablename__ = "completion_reports"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_completion_reports_number"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pdf_key: Mapped[str] = mapped_column(String(300), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locked_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Certificate(UUIDPk, Base):
    """A "Certified by IITPL" certificate. The payload is fixed at issue and signed; the public
    verification page shows only non-sensitive fields."""

    __tablename__ = "certificates"
    __table_args__ = (
        Index("ix_certificates_project", "project_id"),
        # One valid certificate per project at a time; revoke before issuing again.
        Index(
            "uq_certificates_valid",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'valid'"),
        ),
    )

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    pdf_key: Mapped[str] = mapped_column(String(300), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="valid")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column()
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class ReportSetting(Base):
    """Director-owned certificate settings: the IITPL stamp image and the certificate wording."""

    __tablename__ = "report_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
