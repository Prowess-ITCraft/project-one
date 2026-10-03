"""document corpus (ADR 0014)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03 12:00:00+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb(name: str) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=False)


def upgrade() -> None:
    op.create_table(
        "corpus_documents",
        sa.Column("library_file_id", sa.Uuid(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("file_kind", sa.String(10), nullable=False),
        sa.Column("schema", sa.String(20), nullable=False),
        sa.Column("parser", sa.String(60), nullable=True),
        sa.Column("cleaning_version", sa.String(10), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("record_sha256", sa.String(64), nullable=False),
        sa.Column("original_bytes", sa.BigInteger(), nullable=False),
        sa.Column("gzip_bytes", sa.BigInteger(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("text_chars", sa.Integer(), nullable=False),
        sa.Column("lines", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False),
        _jsonb("quality"),
        _jsonb("labels"),
        _jsonb("facts"),
        sa.Column("original_state", sa.String(10), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["library_file_id"],
            ["library_files.id"],
            name=op.f("fk_corpus_documents_library_file_id_library_files"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corpus_documents")),
    )
    op.create_index("uq_corpus_documents_sha", "corpus_documents", ["sha256"], unique=True)
    op.create_index(
        "ix_corpus_documents_kind_score", "corpus_documents", ["kind", "quality_score"]
    )
    op.create_index(
        op.f("ix_corpus_documents_library_file_id"), "corpus_documents", ["library_file_id"]
    )


def downgrade() -> None:
    op.drop_table("corpus_documents")
