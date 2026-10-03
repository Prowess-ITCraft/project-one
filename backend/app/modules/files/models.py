from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDelete, UUIDPk


class StoredFile(UUIDPk, SoftDelete, Base):
    """An uploaded file that passed type checks and the virus scan. Bytes live in object storage."""

    __tablename__ = "stored_files"

    purpose: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    object_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    object_version: Mapped[str | None] = mapped_column(String(120))
    scan_engine: Mapped[str] = mapped_column(String(40), nullable=False)
    exif_stripped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    project_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RejectedUpload(UUIDPk, Base):
    """Record of uploads refused for malware. The bytes are never stored."""

    __tablename__ = "rejected_uploads"

    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
