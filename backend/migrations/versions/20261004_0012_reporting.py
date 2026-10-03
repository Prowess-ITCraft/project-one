"""reporting: waivers, completion reports, certificates, settings (phase 10)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04 10:00:00+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "waivers",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_label", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(25), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("sent_to", sa.String(254), nullable=True),
        sa.Column("ack_token_hash", sa.String(64), nullable=True),
        sa.Column("ack_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_name", sa.String(200), nullable=True),
        sa.Column("acknowledged_ip", postgresql.INET(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waivers")),
        sa.UniqueConstraint("ack_token_hash", name=op.f("uq_waivers_ack_token_hash")),
    )
    op.create_index("ix_waivers_project_status", "waivers", ["project_id", "status"])
    op.create_table(
        "completion_reports",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("pdf_key", sa.String(300), nullable=False),
        sa.Column("pdf_sha256", sa.String(64), nullable=False),
        sa.Column("locked_by", sa.Uuid(), nullable=False),
        _now("locked_at"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_completion_reports")),
        sa.UniqueConstraint("project_id", "number", name="uq_completion_reports_number"),
    )
    op.create_index(op.f("ix_completion_reports_project_id"), "completion_reports", ["project_id"])
    op.create_table(
        "certificates",
        sa.Column("number", sa.String(30), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("pdf_key", sa.String(300), nullable=False),
        sa.Column("pdf_sha256", sa.String(64), nullable=False),
        sa.Column("issued_by", sa.Uuid(), nullable=False),
        _now("issued_at"),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_certificates")),
        sa.UniqueConstraint("number", name=op.f("uq_certificates_number")),
    )
    op.create_index("ix_certificates_project", "certificates", ["project_id"])
    # One valid certificate per project at a time; revoke before issuing again.
    op.create_index(
        "uq_certificates_valid", "certificates", ["project_id"], unique=True,
        postgresql_where=sa.text("status = 'valid'"),
    )
    # A certificate is evidence: only its status, revocation and nothing else may ever change.
    op.execute(
        """
        CREATE FUNCTION certificates_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'certificates are never deleted' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (NEW.id, NEW.number, NEW.project_id, NEW.report_id, NEW.payload,
                NEW.payload_sha256, NEW.signature, NEW.pdf_key, NEW.pdf_sha256,
                NEW.issued_by, NEW.issued_at)
               IS DISTINCT FROM
               (OLD.id, OLD.number, OLD.project_id, OLD.report_id, OLD.payload,
                OLD.payload_sha256, OLD.signature, OLD.pdf_key, OLD.pdf_sha256,
                OLD.issued_by, OLD.issued_at) THEN
                RAISE EXCEPTION 'a certificate cannot be changed, only revoked' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status = 'revoked' AND (NEW.status IS DISTINCT FROM 'revoked'
               OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
               OR NEW.revoked_by IS DISTINCT FROM OLD.revoked_by
               OR NEW.revoke_reason IS DISTINCT FROM OLD.revoke_reason) THEN
                RAISE EXCEPTION 'a revoked certificate stays revoked' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER certificates_guard_trg BEFORE UPDATE OR DELETE ON certificates "
        "FOR EACH ROW EXECUTE FUNCTION certificates_guard()"
    )
    op.create_table(
        "report_settings",
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_report_settings")),
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS certificates_guard_trg ON certificates")
    op.execute("DROP FUNCTION IF EXISTS certificates_guard()")
    for t in ("report_settings", "certificates", "completion_reports", "waivers"):
        op.drop_table(t)
