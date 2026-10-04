"""issued BOQ versions keep their quotation PDF in object storage

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUARD = """
CREATE OR REPLACE FUNCTION boq_versions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'issued BOQ versions cannot be deleted' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.state IN ('accepted', 'superseded') THEN
        RAISE EXCEPTION 'a % BOQ version cannot change', OLD.state USING ERRCODE = 'restrict_violation';
    END IF;
    -- issued: may become superseded (state only) or accepted (with the purchase order)
    IF NEW.state = OLD.state THEN
        RAISE EXCEPTION 'an issued BOQ version cannot change' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.state = 'superseded' AND (NEW.content IS DISTINCT FROM OLD.content OR NEW.totals IS DISTINCT FROM OLD.totals) THEN
        RAISE EXCEPTION 'superseding a BOQ version cannot change its content' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.quote_ref IS DISTINCT FROM OLD.quote_ref OR NEW.number IS DISTINCT FROM OLD.number
       OR NEW.boq_id IS DISTINCT FROM OLD.boq_id OR NEW.issued_by IS DISTINCT FROM OLD.issued_by{pdf} THEN
        RAISE EXCEPTION 'BOQ version identity cannot change' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
"""

_PDF_CHECK = (
    "\n       OR NEW.pdf_key IS DISTINCT FROM OLD.pdf_key"
    " OR NEW.pdf_sha256 IS DISTINCT FROM OLD.pdf_sha256"
)


def upgrade() -> None:
    # Null for versions issued before this revision; those are still rendered on request.
    op.add_column("boq_versions", sa.Column("pdf_key", sa.String(300), nullable=True))
    op.add_column("boq_versions", sa.Column("pdf_sha256", sa.String(64), nullable=True))
    op.execute(_GUARD.replace("{pdf}", _PDF_CHECK))


def downgrade() -> None:
    op.execute(_GUARD.replace("{pdf}", ""))
    op.drop_column("boq_versions", "pdf_sha256")
    op.drop_column("boq_versions", "pdf_key")
