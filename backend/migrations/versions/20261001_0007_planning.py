"""planning: plans, tasks, config baselines, leave, downtime windows

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01 10:00:00+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _jsonb(name: str, default: str) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=False)


def upgrade() -> None:
    op.create_table(
        "plan_task_templates",
        sa.Column("key", sa.String(41), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("minutes_fixed", sa.Integer(), nullable=False),
        sa.Column("minutes_per_unit", sa.Integer(), nullable=False),
        sa.Column("split_per_unit", sa.Boolean(), nullable=False),
        sa.Column("requires_downtime", sa.Boolean(), nullable=False),
        sa.Column("device_type", sa.String(20), nullable=True),
        _jsonb("depends_on_kinds", "[]"),
        _jsonb("steps", "[]"),
        _jsonb("evidence", "[]"),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_task_templates")),
    )
    op.create_index("uq_plan_task_templates_key", "plan_task_templates", ["key"], unique=True)

    op.create_table(
        "plan_config_templates",
        sa.Column("device_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        _jsonb("fields", "[]"),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_config_templates")),
    )
    op.create_index("uq_plan_config_templates_type", "plan_config_templates", ["device_type"], unique=True)

    op.create_table(
        "plans",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("boq_version_id", sa.Uuid(), nullable=False),
        sa.Column("boq_quote_ref", sa.String(40), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        _jsonb("settings", "{}"),
        _jsonb("warnings", "[]"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("baselined_by", sa.Uuid(), nullable=True),
        sa.Column("baselined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('draft','baselined','superseded')", name=op.f("ck_plans_status_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("project_id", "number", name="uq_plans_project_number"),
    )
    op.create_index(op.f("ix_plans_project_id"), "plans", ["project_id"])
    op.create_index(
        "uq_plans_one_active", "plans", ["project_id"], unique=True, postgresql_where=sa.text("status <> 'superseded'")
    )

    op.create_table(
        "plan_tasks",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("ref", sa.String(12), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(41), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("boq_line_ref", sa.String(12), nullable=True),
        sa.Column("asset", sa.String(200), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False),
        _jsonb("depends_on", "[]"),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requires_downtime", sa.Boolean(), nullable=False),
        sa.Column("device_type", sa.String(20), nullable=True),
        _jsonb("steps", "[]"),
        _jsonb("evidence", "[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("last_change_reason", sa.String(300), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name=op.f("fk_plan_tasks_plan_id_plans"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_tasks")),
        sa.UniqueConstraint("plan_id", "ref", name="uq_plan_tasks_ref"),
    )
    op.create_index(op.f("ix_plan_tasks_plan_id"), "plan_tasks", ["plan_id"])
    op.create_index(op.f("ix_plan_tasks_assignee_id"), "plan_tasks", ["assignee_id"])

    op.create_table(
        "plan_config_baselines",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("task_ref", sa.String(12), nullable=True),
        sa.Column("device_type", sa.String(20), nullable=False),
        sa.Column("device_label", sa.String(200), nullable=False),
        _jsonb("fields", "[]"),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_plan_config_baselines_plan_id_plans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_config_baselines")),
    )
    op.create_index(op.f("ix_plan_config_baselines_plan_id"), "plan_config_baselines", ["plan_id"])

    op.create_table(
        "engineer_leaves",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.CheckConstraint("date_to >= date_from", name=op.f("ck_engineer_leaves_range_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engineer_leaves")),
    )
    op.create_index(op.f("ix_engineer_leaves_user_id"), "engineer_leaves", ["user_id"])

    op.create_table(
        "downtime_windows",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.CheckConstraint("end_at > start_at", name=op.f("ck_downtime_windows_range_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_downtime_windows")),
    )
    op.create_index(op.f("ix_downtime_windows_project_id"), "downtime_windows", ["project_id"])

    # A baselined plan is a gate output: its tasks and target configurations never change.
    # Phase 8 keeps live progress in its own tables, never here.
    for table in ("plan_tasks", "plan_config_baselines"):
        op.execute(
            f"""
            CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE pid uuid; st text;
            BEGIN
                IF TG_OP = 'DELETE' THEN pid := OLD.plan_id; ELSE pid := NEW.plan_id; END IF;
                SELECT status INTO st FROM plans WHERE id = pid;
                IF st = 'baselined' THEN
                    RAISE EXCEPTION 'plan is baselined: {table} are read-only' USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END $$
            """
        )
        op.execute(
            f"CREATE TRIGGER {table}_guard_trg BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {table}_guard()"
        )
    op.execute(
        """
        CREATE FUNCTION plans_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'baselined' AND NEW.status = 'baselined' THEN
                RAISE EXCEPTION 'plan is baselined and cannot be edited' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status = 'superseded' THEN
                RAISE EXCEPTION 'a superseded plan cannot be edited' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute("CREATE TRIGGER plans_guard_trg BEFORE UPDATE ON plans FOR EACH ROW EXECUTE FUNCTION plans_guard()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS plans_guard_trg ON plans")
    op.execute("DROP FUNCTION IF EXISTS plans_guard()")
    for table in ("plan_config_baselines", "plan_tasks"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_guard_trg ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {table}_guard()")
    for t in (
        "downtime_windows",
        "engineer_leaves",
        "plan_config_baselines",
        "plan_tasks",
        "plans",
        "plan_config_templates",
        "plan_task_templates",
    ):
        op.drop_table(t)
