from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDelete, Timestamps, UUIDPk, Versioned

SYSTEM_USER = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Built-in collections the library fills automatically.
COLLECTION_BOQ = "historical_boq_lines"
COLLECTION_AUDIT = "audit_findings"


class Dataset(UUIDPk, Timestamps, SoftDelete, Versioned, Base):
    __tablename__ = "datasets"
    __table_args__ = (
        Index(
            "uq_datasets_collection_key",
            "collection_key",
            unique=True,
            postgresql_where="collection_key IS NOT NULL AND deleted_at IS NULL",
        ),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    collection_key: Mapped[str | None] = mapped_column(String(60))
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )


class DatasetVersion(UUIDPk, Base):
    """An immutable snapshot. Only the training flag and the cached analysis may change."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "number"),
        CheckConstraint("number >= 1", name="number_positive"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id"))
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    lineage: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    frozen_for_training: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data_card: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    analysis_cache: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class DatasetShare(Base):
    __tablename__ = "dataset_shares"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)  # user | role
    principal: Mapped[str] = mapped_column(String(64), primary_key=True)
    access: Mapped[str] = mapped_column(String(8), nullable=False)  # view | edit
    granted_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuarantineRow(UUIDPk, Base):
    """A row that failed type or rule checks. It is kept, with reasons, until a person fixes or
    discards it."""

    __tablename__ = "dataset_quarantine"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id"))
    library_file_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="open"
    )  # open | fixed | discarded
    resolved_by: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Synonym(UUIDPk, Base):
    __tablename__ = "dataset_synonyms"
    __table_args__ = (
        Index("uq_dataset_synonyms_alias", "domain", text("lower(alias)"), unique=True),
    )

    domain: Mapped[str] = mapped_column(String(12), nullable=False)
    canonical: Mapped[str] = mapped_column(String(160), nullable=False)
    alias: Mapped[str] = mapped_column(String(160), nullable=False)


class PromotionItem(UUIDPk, Base):
    """A cleaned row proposed for the master catalogue. Nothing enters the catalogue without a
    second person approving it."""

    __tablename__ = "dataset_promotions"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id"), nullable=False)
    row: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    proposed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    submitted_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(500))
    catalogue_item_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LibraryFile(UUIDPk, Base):
    """One file dropped into the library: a past BOQ or a PrismSuite report. The engine picks it
    up, reads it and appends the rows to a built-in collection. The hash makes it idempotent."""

    __tablename__ = "library_files"
    __table_args__ = (Index("uq_library_files_sha", "sha256", unique=True),)

    file_id: Mapped[uuid.UUID | None] = mapped_column(index=True)  # the stored file
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # upload | folder
    kind: Mapped[str | None] = mapped_column(String(20))  # boq | audit | unknown
    status: Mapped[str] = mapped_column(String(14), nullable=False, default="queued")
    # queued | processed | needs_review | skipped | failed
    parser: Mapped[str | None] = mapped_column(String(60))
    rows_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_held: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(500))
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CorpusDocument(UUIDPk, Base):
    """The canonical JSON form of one library file (ADR 0014). The gzipped record lives in object
    storage; this row indexes it so lists, filters and quality views never open the record."""

    __tablename__ = "corpus_documents"
    __table_args__ = (
        Index("uq_corpus_documents_sha", "sha256", unique=True),
        Index("ix_corpus_documents_kind_score", "kind", "quality_score"),
    )

    library_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("library_files.id"), index=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # boq | audit | other
    file_kind: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf | docx | xlsx | json
    schema: Mapped[str] = mapped_column(String(20), nullable=False)
    parser: Mapped[str | None] = mapped_column(String(60))
    cleaning_version: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gzip_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    labels: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    original_state: Mapped[str] = mapped_column(String(10), nullable=False, default="kept")
    # kept | purged (the original file was removed under the retention setting)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
