from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Computed, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Names, codes and quote references are not English prose, so the 'simple' configuration:
# no stemming, no stop words, every token kept as written (lower-cased).
TSV = (
    "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(subtitle, '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(body, '')), 'C')"
)


class SearchDocument(Base):
    """One thing people can find: a customer, project, quote, field task or catalogue item.
    Written only by the search module, from events the owning modules publish. Never holds a
    price. `perm` is the permission needed to see it; `project_id`, `customer_id` and
    `assignee_id` drive the same object-level checks as the owning module."""

    __tablename__ = "search_documents"
    __table_args__ = (
        Index("ix_search_documents_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_search_documents_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index("ix_search_documents_project", "project_id"),
    )

    kind: Mapped[str] = mapped_column(String(12), primary_key=True)
    ref_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(300), nullable=False)
    perm: Mapped[str] = mapped_column(String(40), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column()
    customer_id: Mapped[uuid.UUID | None] = mapped_column()
    assignee_id: Mapped[uuid.UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(TSV, persisted=True))
