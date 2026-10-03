"""notifications and field operations

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01 14:00:00+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _jsonb(name: str) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=False)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("to_address", sa.String(254), nullable=False),
        sa.Column("to_user_id", sa.Uuid(), nullable=True),
        sa.Column("template", sa.String(40), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.String(120), nullable=True),
        sa.Column("related_type", sa.String(40), nullable=True),
        sa.Column("related_id", sa.String(64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(op.f("ix_notifications_to_user_id"), "notifications", ["to_user_id"])
    op.create_index("ix_notifications_due", "notifications", ["status", "next_attempt_at"])
    op.create_index(
        "uq_notifications_dedupe", "notifications", ["dedupe_key"], unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_table(
        "notification_prefs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("template", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "template", name=op.f("pk_notification_prefs")),
    )

    op.create_table(
        "task_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_ref", sa.String(12), nullable=False),
        sa.Column("kind", sa.String(41), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("asset", sa.String(200), nullable=True),
        sa.Column("device_type", sa.String(20), nullable=True),
        sa.Column("requires_downtime", sa.Boolean(), nullable=False),
        _jsonb("depends_on"),
        _jsonb("steps"),
        _jsonb("evidence_reqs"),
        sa.Column("assignee_id", sa.Uuid(), nullable=False),
        sa.Column("planned_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("blocked_from", sa.String(12), nullable=True),
        sa.Column("block_reason", sa.String(500), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handed_over_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rework_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_runs")),
        sa.UniqueConstraint("plan_id", "task_ref", name="uq_task_runs_task"),
    )
    op.create_index(op.f("ix_task_runs_project_id"), "task_runs", ["project_id"])
    op.create_index(op.f("ix_task_runs_assignee_id"), "task_runs", ["assignee_id"])
    op.create_index("ix_task_runs_project_state", "task_runs", ["project_id", "state"])

    op.create_table(
        "run_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_event_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("from_state", sa.String(12), nullable=True),
        sa.Column("to_state", sa.String(12), nullable=True),
        _jsonb("detail"),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["task_runs.id"], name=op.f("fk_run_events_run_id_task_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_run_events")),
    )
    op.create_index(op.f("ix_run_events_run_id"), "run_events", ["run_id"])
    op.create_index("ix_run_events_project_seq", "run_events", ["project_id", "seq"])
    op.create_index(
        "uq_run_events_client", "run_events", ["run_id", "client_event_id"], unique=True,
        postgresql_where=sa.text("client_event_id IS NOT NULL"),
    )

    op.create_table(
        "run_evidence",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_index", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(14), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("text_value", sa.String(500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["task_runs.id"], name=op.f("fk_run_evidence_run_id_task_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_evidence")),
        sa.UniqueConstraint("run_id", "client_id", name="uq_run_evidence_client"),
    )
    op.create_index("ix_run_evidence_run_req", "run_evidence", ["run_id", "requirement_index"])

    op.create_table(
        "otp_challenges",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(10), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("sent_to", sa.String(254), nullable=False),
        sa.Column("salt", sa.String(32), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["task_runs.id"], name=op.f("fk_otp_challenges_run_id_task_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_challenges")),
    )
    op.create_index("ix_otp_run_purpose", "otp_challenges", ["run_id", "purpose"])

    # The history of field work is evidence: events and evidence rows can be added, never changed.
    for table in ("run_events", "run_evidence"):
        op.execute(
            f"""
            CREATE FUNCTION {table}_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION '{table} is append only' USING ERRCODE = 'integrity_constraint_violation';
            END $$
            """
        )
        op.execute(
            f"CREATE TRIGGER {table}_immutable_trg BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
        )


def downgrade() -> None:
    for table in ("run_evidence", "run_events"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_trg ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
    for t in (
        "otp_challenges",
        "run_evidence",
        "run_events",
        "task_runs",
        "notification_prefs",
        "notifications",
    ):
        op.drop_table(t)
