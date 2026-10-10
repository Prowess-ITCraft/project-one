"""field app: evidence location and stamps, single-use upload links, phone sync status, the
notification centre, Web Push subscriptions and preferences per channel

Expand only: new tables and nullable or defaulted columns, so the previous release keeps
working against this schema and a rollback of the code needs no downgrade.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-08 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------------------------------------------------------------- evidence
    op.add_column("run_evidence", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("run_evidence", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column("run_evidence", sa.Column("accuracy_m", sa.Float(), nullable=True))
    op.add_column("run_evidence", sa.Column("location_note", sa.String(200), nullable=True))
    op.add_column("run_evidence", sa.Column("stamped_file_id", sa.Uuid(), nullable=True))
    op.add_column(
        "run_evidence",
        sa.Column("parse", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "run_evidence",
        sa.Column("via", sa.String(8), nullable=False, server_default="app"),
    )

    op.create_table(
        "field_upload_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_index", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_ip", sa.String(64), nullable=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_runs.id"],
            ondelete="CASCADE",
            name=op.f("fk_field_upload_links_run_id_task_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_upload_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_field_upload_links_token_hash")),
    )
    op.create_index("ix_field_upload_links_run_id", "field_upload_links", ["run_id"])

    op.create_table(
        "field_device_status",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("pending", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("oldest_pending_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("app_version", sa.String(40), nullable=True),
        sa.Column("platform", sa.String(40), nullable=True),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_field_device_status")),
    )

    # ---------------------------------------------------------------- notifications
    op.add_column("notifications", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.add_column("notifications", sa.Column("link", sa.String(300), nullable=True))
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_notifications_parent_id", "notifications", ["parent_id"])
    op.create_index(
        "ix_notifications_inbox",
        "notifications",
        ["to_user_id", "created_at"],
        postgresql_where=sa.text("channel = 'in_app'"),
    )

    # Preferences become per channel. Existing choices were about email.
    op.add_column(
        "notification_prefs",
        sa.Column("channel", sa.String(10), nullable=False, server_default="email"),
    )
    op.drop_constraint("pk_notification_prefs", "notification_prefs", type_="primary")
    op.create_primary_key(
        "pk_notification_prefs", "notification_prefs", ["user_id", "template", "channel"]
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(200), nullable=False),
        sa.Column("auth", sa.String(100), nullable=False),
        sa.Column("user_agent", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
        sa.UniqueConstraint("endpoint", name=op.f("uq_push_subscriptions_endpoint")),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.execute("DELETE FROM notification_prefs WHERE channel <> 'email'")
    op.drop_constraint("pk_notification_prefs", "notification_prefs", type_="primary")
    op.create_primary_key("pk_notification_prefs", "notification_prefs", ["user_id", "template"])
    op.drop_column("notification_prefs", "channel")
    op.drop_index("ix_notifications_inbox", table_name="notifications")
    op.drop_index("ix_notifications_parent_id", table_name="notifications")
    op.drop_column("notifications", "read_at")
    op.drop_column("notifications", "link")
    op.drop_column("notifications", "parent_id")
    op.drop_table("field_device_status")
    op.drop_index("ix_field_upload_links_run_id", table_name="field_upload_links")
    op.drop_table("field_upload_links")
    for col in ("via", "parse", "stamped_file_id", "location_note", "accuracy_m", "lng", "lat"):
        op.drop_column("run_evidence", col)
