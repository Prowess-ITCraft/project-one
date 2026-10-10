"""quotes won and lost, with the reason; the outcome history is append only

Expand only: three defaulted or nullable columns on boqs and a new table.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-08 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("boqs", sa.Column("outcome", sa.String(8), nullable=False, server_default="open"))
    op.add_column("boqs", sa.Column("outcome_reason", sa.String(20), nullable=True))
    op.add_column("boqs", sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True))
    # Quotes accepted before this revision were won.
    op.execute("UPDATE boqs SET outcome = 'won' WHERE status = 'accepted'")

    op.create_table(
        "boq_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("boq_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(20), nullable=True),
        sa.Column("competitor", sa.String(120), nullable=True),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("by", sa.Uuid(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["boq_id"], ["boqs.id"], name=op.f("fk_boq_outcomes_boq_id_boqs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_outcomes")),
    )
    op.create_index("ix_boq_outcomes_boq_id", "boq_outcomes", ["boq_id"])
    op.execute(
        """
        CREATE FUNCTION boq_outcomes_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'boq_outcomes is append only' USING ERRCODE = 'integrity_constraint_violation';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER boq_outcomes_immutable_trg BEFORE UPDATE OR DELETE ON boq_outcomes "
        "FOR EACH ROW EXECUTE FUNCTION boq_outcomes_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS boq_outcomes_immutable_trg ON boq_outcomes")
    op.execute("DROP FUNCTION IF EXISTS boq_outcomes_immutable()")
    op.drop_index("ix_boq_outcomes_boq_id", table_name="boq_outcomes")
    op.drop_table("boq_outcomes")
    op.drop_column("boqs", "outcome_at")
    op.drop_column("boqs", "outcome_reason")
    op.drop_column("boqs", "outcome")
