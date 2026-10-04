"""learning from accepted BOQs: examples, frozen training sets, models, shadow runs (phase 13)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04 18:00:00+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "ml_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("boq_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("rec_key", sa.String(120), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("item_name", sa.String(300), nullable=False),
        sa.Column("rule_rank", sa.Integer(), nullable=False),
        sa.Column("rule_score", sa.Float(), nullable=False),
        sa.Column("criteria", JSONB, nullable=False),
        sa.Column("kept", sa.Boolean(), nullable=True),
        sa.Column("labelled_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_examples")),
        sa.UniqueConstraint("boq_id", "rec_key", "item_id", name="uq_ml_examples"),
    )
    op.create_index("ix_ml_examples_boq_id", "ml_examples", ["boq_id"])
    op.create_index("ix_ml_examples_labelled", "ml_examples", ["labelled_at"])

    op.create_table(
        "ml_training_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("rows", JSONB, nullable=False),
        sa.Column("data_card", JSONB, nullable=False),
        sa.Column("frozen_by", sa.Uuid(), nullable=False),
        _now("frozen_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_training_sets")),
        sa.UniqueConstraint("number", name=op.f("uq_ml_training_sets_number")),
    )
    # A training set is the record of what a model learned from: it never changes.
    op.execute(
        """
        CREATE FUNCTION ml_training_sets_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'training sets are frozen' USING ERRCODE = 'integrity_constraint_violation';
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER ml_training_sets_guard_trg BEFORE UPDATE OR DELETE ON ml_training_sets "
        "FOR EACH ROW EXECUTE FUNCTION ml_training_sets_guard()"
    )

    op.create_table(
        "ml_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("training_set_id", sa.Uuid(), nullable=False),
        sa.Column("weights", JSONB, nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("trained_by", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_models")),
        sa.UniqueConstraint("number", name=op.f("uq_ml_models_number")),
    )
    op.create_index(
        "uq_ml_models_shadow", "ml_models", ["status"], unique=True,
        postgresql_where=sa.text("status = 'shadow'"),
    )

    op.create_table(
        "ml_shadow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("boq_id", sa.Uuid(), nullable=False),
        sa.Column("rec_key", sa.String(120), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("rule_top", sa.String(300), nullable=False),
        sa.Column("model_top", sa.String(300), nullable=False),
        sa.Column("agree", sa.Boolean(), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_shadow_runs")),
        sa.UniqueConstraint("model_id", "boq_id", "rec_key", name="uq_ml_shadow_runs"),
    )
    op.create_index("ix_ml_shadow_runs_model_id", "ml_shadow_runs", ["model_id"])


def downgrade() -> None:
    op.drop_table("ml_shadow_runs")
    op.drop_table("ml_models")
    op.execute("DROP TRIGGER IF EXISTS ml_training_sets_guard_trg ON ml_training_sets")
    op.execute("DROP FUNCTION IF EXISTS ml_training_sets_guard()")
    op.drop_table("ml_training_sets")
    op.drop_table("ml_examples")
