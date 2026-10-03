"""verification: deviations, brand key mappings, settings (phase 9)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04 09:00:00+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "deviations",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_ref", sa.String(12), nullable=False),
        sa.Column("device", sa.String(200), nullable=True),
        sa.Column("field_key", sa.String(60), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("expected", sa.String(300), nullable=True),
        sa.Column("actual", sa.String(300), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("opened_by", sa.Uuid(), nullable=True),
        sa.Column("opened_attempt", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deviations")),
    )
    op.create_index(op.f("ix_deviations_run_id"), "deviations", ["run_id"])
    op.create_index("ix_deviations_project_status", "deviations", ["project_id", "status"])
    op.create_index(
        "uq_deviations_open", "deviations", ["run_id", "field_key"], unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "brand_field_maps",
        sa.Column("brand", sa.String(30), nullable=False),
        sa.Column("device_type", sa.String(20), nullable=False),
        sa.Column("field_key", sa.String(60), nullable=False),
        sa.Column("keys", JSONB, nullable=False),
        sa.Column("rule", JSONB, nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_field_maps")),
        sa.UniqueConstraint("brand", "field_key", name="uq_brand_field_maps"),
    )
    op.create_table(
        "verification_settings",
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_verification_settings")),
    )


def downgrade() -> None:
    for t in ("verification_settings", "brand_field_maps", "deviations"):
        op.drop_table(t)
