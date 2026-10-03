from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, Versioned

IN_REVIEW = "in_review"
APPROVED = "approved"
REJECTED = "rejected"
SUPERSEDED = "superseded"


class AuditImport(UUIDPk, Timestamps, Versioned, Base):
    """One parsed PrismSuite report. `snapshot` is the working copy a reviewer corrects;
    `original_snapshot` is exactly what the parser produced and is never edited."""

    __tablename__ = "audit_imports"
    __table_args__ = (
        Index("uq_audit_imports_project_revision", "project_id", "revision", unique=True),
        # One approved report per project and kind: a baseline (before) and a rescan (after).
        Index(
            "uq_audit_imports_one_approved_per_kind",
            "project_id",
            "kind",
            unique=True,
            postgresql_where="status = 'approved'",
        ),
    )

    kind: Mapped[str] = mapped_column(
        String(12), nullable=False, default="baseline", server_default="baseline"
    )

    project_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_name: Mapped[str] = mapped_column(String(60), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=IN_REVIEW)
    original_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    read_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    imported_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


class AuditCorrection(UUIDPk, Base):
    """Every reviewer change, with the reason. Append-only."""

    __tablename__ = "audit_corrections"

    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audit_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(200), nullable=False)
    old_value: Mapped[Any] = mapped_column(JSONB)
    new_value: Mapped[Any] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    corrected_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    corrected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
