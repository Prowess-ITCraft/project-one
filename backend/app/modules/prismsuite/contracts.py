"""Public surface of the prismsuite module. Other modules import only from here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.contracts import Principal
from app.modules.prismsuite import service as _service
from app.modules.prismsuite.snapshot import (
    AuditSnapshot,
    Device,
    DeviceCategory,
    Endpoint,
    Score,
    Severity,
    Vulnerability,
)

SNAPSHOT_APPROVED = _service.SNAPSHOT_APPROVED


@dataclass(frozen=True)
class ApprovedAudit:
    import_id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    revision: int
    approved_at: datetime | None
    snapshot: AuditSnapshot


async def get_approved_audit(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, kind: str = "baseline"
) -> ApprovedAudit:
    """The reviewed, approved snapshot for a project (`baseline` or the after-work `rescan`).
    Raises NotFound when there is none."""
    row, snap = await _service.approved_snapshot(session, principal, project_id, kind)
    return ApprovedAudit(row.id, row.project_id, row.kind, row.revision, row.decided_at, snap)


async def get_latest_audit(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, kind: str = "baseline"
) -> ApprovedAudit:
    """Approved if possible, else the newest report still in review. `approved_at` is None for
    one in review. For estimates; official steps use `get_approved_audit`."""
    row, snap = await _service.latest_snapshot(session, principal, project_id, kind)
    return ApprovedAudit(row.id, row.project_id, row.kind, row.revision, row.decided_at, snap)


class ReportUnreadable(Exception):
    """The file looks like a PrismSuite report but could not be read."""


@dataclass(frozen=True)
class ParsedReport:
    snapshot: AuditSnapshot
    parser_name: str
    counts: dict[str, int]
    blocking: int  # required fields the parser could not read
    conflicts: int


def parse_report(data: bytes, file_kind: str) -> ParsedReport | None:
    """Read a PrismSuite report without storing anything (used by the library).
    Returns None when no parser recognises the file. Raises ParseFailure when it is unreadable."""
    from app.modules.prismsuite.parsers import base

    parser = base.pick(data, file_kind)
    if parser is None:
        return None
    try:
        result = parser.parse(data)
    except base.ParseFailure as exc:
        raise ReportUnreadable(str(exc)) from exc
    summary = result.report.summary()
    return ParsedReport(
        snapshot=result.snapshot,
        parser_name=parser.name,
        counts=dict(summary["counts"]),
        blocking=int(summary["blocking"]),
        conflicts=int(summary["counts"].get("conflict", 0)),
    )


__all__ = [
    "SNAPSHOT_APPROVED",
    "ApprovedAudit",
    "AuditSnapshot",
    "Device",
    "DeviceCategory",
    "Endpoint",
    "ParsedReport",
    "ReportUnreadable",
    "Score",
    "Severity",
    "Vulnerability",
    "get_approved_audit",
    "parse_report",
]
