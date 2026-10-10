"""learning: three kinds of model (ranker, BOQ lines, price drift), model cards, approval by
the Director, BOQ line examples and price points

Expand only. The shadow index moves from one model overall to one per kind; existing rows are
all rankers.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-08 13:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "ml_training_sets",
        sa.Column("kind", sa.String(12), nullable=False, server_default="ranker"),
    )
    op.add_column(
        "ml_models", sa.Column("kind", sa.String(12), nullable=False, server_default="ranker")
    )
    op.add_column("ml_models", sa.Column("artifact", JSONB, nullable=True))
    op.add_column("ml_models", sa.Column("card", JSONB, nullable=True))
    op.add_column(
        "ml_models", sa.Column("shadow_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("ml_models", sa.Column("approved_by", sa.Uuid(), nullable=True))
    op.add_column("ml_models", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ml_models", sa.Column("approval_note", sa.String(1000), nullable=True))
    op.execute("UPDATE ml_models SET shadow_started_at = updated_at WHERE status = 'shadow'")
    op.drop_index("uq_ml_models_shadow", table_name="ml_models")
    op.create_index(
        "uq_ml_models_shadow",
        "ml_models",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("status = 'shadow'"),
    )
    op.create_index(
        "uq_ml_models_approved",
        "ml_models",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )

    op.create_table(
        "ml_line_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("boq_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("features", JSONB, nullable=False),
        sa.Column("rule_labels", JSONB, nullable=False),
        sa.Column("titles", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("model_labels", JSONB, nullable=True),
        sa.Column("labels", JSONB, nullable=True),
        sa.Column("labelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_line_examples")),
        sa.UniqueConstraint("boq_id", name=op.f("uq_ml_line_examples_boq_id")),
    )
    op.create_table(
        "ml_price_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("price_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("item_name", sa.String(300), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("item_kind", sa.String(10), nullable=False),
        sa.Column("vendor", sa.String(64), nullable=True),
        sa.Column("selling", sa.Float(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("quoted_on", sa.Date(), nullable=False),
        sa.Column("rule_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rule_reason", sa.String(300), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("model_expected", sa.Float(), nullable=True),
        sa.Column("model_flag", sa.Boolean(), nullable=True),
        sa.Column("alerted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_price_points")),
        sa.UniqueConstraint("price_id", name=op.f("uq_ml_price_points_price_id")),
    )
    op.create_index("ix_ml_price_points_item", "ml_price_points", ["item_id", "quoted_on"])


def downgrade() -> None:
    op.drop_index("ix_ml_price_points_item", table_name="ml_price_points")
    op.drop_table("ml_price_points")
    op.drop_table("ml_line_examples")
    op.drop_index("uq_ml_models_approved", table_name="ml_models")
    op.drop_index("uq_ml_models_shadow", table_name="ml_models")
    op.execute("UPDATE ml_models SET status = 'trained' WHERE status = 'approved'")
    op.create_index(
        "uq_ml_models_shadow",
        "ml_models",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'shadow'"),
    )
    for col in (
        "approval_note",
        "approved_at",
        "approved_by",
        "shadow_started_at",
        "card",
        "artifact",
        "kind",
    ):
        op.drop_column("ml_models", col)
    op.drop_column("ml_training_sets", "kind")
