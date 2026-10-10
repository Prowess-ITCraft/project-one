"""global search: one table of documents with a full-text vector and a trigram index

pg_trgm is a trusted extension (PostgreSQL 13 and later), so the database owner can enable it.
Expand only.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-08 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TSV = (
    "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(subtitle, '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(body, '')), 'C')"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "search_documents",
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("ref_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("subtitle", sa.String(300), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("url", sa.String(300), nullable=False),
        sa.Column("perm", sa.String(40), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(TSV, persisted=True), nullable=True),
        sa.PrimaryKeyConstraint("kind", "ref_id", name=op.f("pk_search_documents")),
    )
    op.create_index("ix_search_documents_tsv", "search_documents", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_search_documents_title_trgm",
        "search_documents",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index("ix_search_documents_project", "search_documents", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_search_documents_project", table_name="search_documents")
    op.drop_index("ix_search_documents_title_trgm", table_name="search_documents")
    op.drop_index("ix_search_documents_tsv", table_name="search_documents")
    op.drop_table("search_documents")
