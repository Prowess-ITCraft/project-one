"""field task states follow the v2.1 brief, engine checks (ADR 0015)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03 13:00:00+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Field work was never started on a real project with the earlier state names, so there is
    # no data to translate. Refuse to run if there is, rather than guess.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM task_runs) THEN
                RAISE EXCEPTION 'task_runs is not empty; translate its states by hand first';
            END IF;
        END $$
        """
    )
    for col in ("state", "blocked_from"):
        op.alter_column("task_runs", col, type_=sa.String(20))
    for col in ("from_state", "to_state"):
        op.alter_column("run_events", col, type_=sa.String(20))
    op.drop_column("task_runs", "submitted_at")
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("task_runs", sa.Column("baseline", jsonb, server_default="[]", nullable=False))
    op.add_column("task_runs", sa.Column("actuals", jsonb, server_default="{}", nullable=False))
    op.add_column("task_runs", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("task_runs", sa.Column("verified_by", sa.Uuid(), nullable=True))
    op.add_column("task_runs", sa.Column("last_check_passed", sa.Boolean(), nullable=True))

    op.create_table(
        "run_checks",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("driver", sa.String(40), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("deviations", sa.Integer(), nullable=False),
        sa.Column("critical_open", sa.Integer(), nullable=False),
        sa.Column("result", jsonb, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["task_runs.id"], name=op.f("fk_run_checks_run_id_task_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_checks")),
    )
    op.create_index("ix_run_checks_run", "run_checks", ["run_id", "attempt"])
    op.create_index(op.f("ix_run_checks_project_id"), "run_checks", ["project_id"])
    op.execute(
        """
        CREATE FUNCTION run_checks_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'run_checks is append only' USING ERRCODE = 'integrity_constraint_violation';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER run_checks_immutable_trg BEFORE UPDATE OR DELETE ON run_checks "
        "FOR EACH ROW EXECUTE FUNCTION run_checks_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS run_checks_immutable_trg ON run_checks")
    op.execute("DROP FUNCTION IF EXISTS run_checks_immutable()")
    op.drop_table("run_checks")
    for col in ("last_check_passed", "verified_by", "closed_at", "actuals", "baseline"):
        op.drop_column("task_runs", col)
    op.add_column(
        "task_runs", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True)
    )
    for col in ("from_state", "to_state"):
        op.alter_column("run_events", col, type_=sa.String(12))
    for col in ("state", "blocked_from"):
        op.alter_column("task_runs", col, type_=sa.String(12))
