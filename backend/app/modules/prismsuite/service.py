"""PrismSuite import, review and approval rules."""

from __future__ import annotations

import asyncio
import copy
import re
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.errors import Conflict, NotFound, StaleVersion, ValidationFailed
from app.core.events import DomainEvent
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import record
from app.modules.customers.contracts import Stage, artifact_locked_event, get_project_ref
from app.modules.files.contracts import read_file
from app.modules.identity.contracts import (
    P,
    Principal,
    audit_context,
    ensure_different_people,
)
from app.modules.prismsuite import parsers
from app.modules.prismsuite.models import (
    APPROVED,
    IN_REVIEW,
    REJECTED,
    SUPERSEDED,
    AuditCorrection,
    AuditImport,
)
from app.modules.prismsuite.parsers import base
from app.modules.prismsuite.snapshot import AuditSnapshot, FieldReport, FieldStatus, ReadReport

SNAPSHOT_APPROVED = "prismsuite.snapshot_approved"
ARTIFACT_TYPE = "prismsuite_audit"
_IDX = re.compile(r"^\d+$")

assert parsers  # importing the package registers the built-in parsers


def _report(row: AuditImport) -> ReadReport:
    return ReadReport.model_validate(row.read_report)


def read_summary(row: AuditImport) -> dict[str, Any]:
    return _report(row).summary()


async def get_import(
    session: AsyncSession, principal: Principal, import_id: uuid.UUID
) -> AuditImport:
    row = await session.get(AuditImport, import_id)
    if row is None:
        raise NotFound("Audit import not found.")
    await get_project_ref(session, principal, row.project_id)  # object-level access
    return row


async def list_imports(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[AuditImport]:
    await get_project_ref(session, principal, project_id)
    rows = await session.scalars(
        select(AuditImport)
        .where(AuditImport.project_id == project_id)
        .order_by(AuditImport.revision.desc())
    )
    return list(rows)


async def list_corrections(session: AsyncSession, import_id: uuid.UUID) -> list[AuditCorrection]:
    rows = await session.scalars(
        select(AuditCorrection)
        .where(AuditCorrection.import_id == import_id)
        .order_by(AuditCorrection.corrected_at, AuditCorrection.id)
    )
    return list(rows)


async def create_import(
    session: AsyncSession,
    principal: Principal,
    *,
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    kind: str = "baseline",
) -> AuditImport:
    principal.require(P.PRISMSUITE_IMPORT)
    if kind not in ("baseline", "rescan"):
        raise ValidationFailed("Kind must be baseline or rescan.")
    await get_project_ref(session, principal, project_id)
    ref, data = await read_file(session, principal, file_id)
    if ref.purpose != "audit_report":
        raise ValidationFailed("Only files uploaded as an audit report can be imported.")
    if ref.project_id != project_id:
        raise ValidationFailed("The file was uploaded for a different project.")

    clash = await session.scalar(
        select(AuditImport.id).where(
            AuditImport.project_id == project_id,
            AuditImport.file_sha256 == ref.sha256,
            AuditImport.status != REJECTED,
        )
    )
    if clash:
        raise Conflict(
            "This exact report was already imported for the project.", code="already_imported"
        )

    if kind == "rescan" and not await session.scalar(
        select(AuditImport.id).where(
            AuditImport.project_id == project_id,
            AuditImport.kind == "baseline",
            AuditImport.status == APPROVED,
        )
    ):
        raise Conflict(
            "Approve the baseline audit before importing the after-work rescan.",
            code="baseline_required",
        )

    parser = base.pick(data, ref.kind)
    if parser is None:
        raise ValidationFailed(
            "This report layout is not recognised. Ask an admin to add a parser for it.",
            code="audit_layout_unknown",
        )
    try:
        result = await asyncio.to_thread(parser.parse, data)
    except base.ParseFailure as exc:
        raise ValidationFailed(
            f"The report could not be read: {exc}", code="audit_unreadable"
        ) from exc

    snap = result.snapshot.model_dump(mode="json")
    current = await session.scalar(
        select(func.coalesce(func.max(AuditImport.revision), 0)).where(
            AuditImport.project_id == project_id
        )
    )
    revision = (current or 0) + 1
    row = AuditImport(
        project_id=project_id,
        file_id=file_id,
        file_sha256=ref.sha256,
        revision=revision,
        kind=kind,
        parser_name=parser.name,
        schema_version=result.snapshot.schema_version,
        status=IN_REVIEW,
        original_snapshot=snap,
        snapshot=copy.deepcopy(snap),
        read_report=result.report.model_dump(mode="json"),
        imported_by=principal.user_id,
    )
    session.add(row)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="import",
        entity_type="audit_import",
        entity_id=row.id,
        after={
            "project_id": str(project_id),
            "revision": revision,
            "kind": kind,
            "parser": parser.name,
            "file_id": str(file_id),
            "read": result.report.summary(),
        },
        only_changes=False,
    )
    await session.commit()
    return row


def _set_pointer(doc: dict[str, Any], path: str, value: Any) -> Any:
    """Set a value by JSON pointer and return the old one. Dict keys may be created only at the
    last step (e.g. a new component score); list items must already exist."""
    parts = path.strip("/").split("/")
    node: Any = doc
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(node, list):
            if not _IDX.match(part) or int(part) >= len(node):
                raise ValidationFailed(f"'{path}' does not point at an existing item.")
            idx = int(part)
            if last:
                old = node[idx]
                node[idx] = value
                return old
            node = node[idx]
        elif isinstance(node, dict):
            if last:
                old = node.get(part)
                node[part] = value
                return old
            if part not in node or node[part] is None:
                raise ValidationFailed(f"'{path}' does not exist in the snapshot.")
            node = node[part]
        else:
            raise ValidationFailed(f"'{path}' does not exist in the snapshot.")
    raise ValidationFailed("Empty path.")  # unreachable: the pointer pattern needs one segment


def _mark_corrected(report: ReadReport, path: str, value: Any, message: str) -> None:
    for f in report.fields:
        if f.path == path:
            f.status = FieldStatus.CORRECTED
            f.message = message
            return
    report.fields.append(
        FieldReport(path=path, status=FieldStatus.CORRECTED, message=message, raw=str(value))
    )


def _report_field(report: ReadReport, path: str) -> FieldReport:
    for f in report.fields:
        if f.path == path:
            return f
    raise ValidationFailed(f"The read report has no field '{path}'.", code="unknown_report_field")


def _ensure_open(row: AuditImport, version: int) -> None:
    if row.status != IN_REVIEW:
        raise Conflict(f"This import is {row.status} and can no longer be changed.")
    if row.version != version:
        raise StaleVersion()


async def correct(
    session: AsyncSession,
    principal: Principal,
    import_id: uuid.UUID,
    *,
    path: str,
    value: Any,
    reason: str,
    version: int,
    resolves: str | None = None,
) -> AuditImport:
    principal.require(P.PRISMSUITE_REVIEW)
    row = await get_import(session, principal, import_id)
    _ensure_open(row, version)
    report = _report(row)
    if resolves is not None:
        _report_field(report, resolves)  # must exist
    doc = copy.deepcopy(row.snapshot)
    old = _set_pointer(doc, path, value)
    try:
        validated = AuditSnapshot.model_validate(doc)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ValidationFailed(
            f"That value is not valid here: {first['msg']}", code="snapshot_invalid"
        ) from exc
    _mark_corrected(report, resolves or path, value, "Set by a reviewer.")
    row.snapshot = validated.model_dump(mode="json")
    row.read_report = report.model_dump(mode="json")
    session.add(
        AuditCorrection(
            import_id=row.id,
            path=path,
            old_value=old,
            new_value=value,
            reason=reason,
            corrected_by=principal.user_id,
        )
    )
    await record(
        session,
        audit_context(principal),
        action="correct",
        entity_type="audit_import",
        entity_id=row.id,
        before={path: old},
        after={path: value, "reason": reason},
        only_changes=False,
    )
    await session.commit()
    return row


async def resolve_field(
    session: AsyncSession,
    principal: Principal,
    import_id: uuid.UUID,
    *,
    path: str,
    reason: str,
    version: int,
) -> AuditImport:
    """Confirm a report field as it stands, without changing the snapshot. Allowed for a
    conflict (the reviewer checked and the stored value is right) and for optional fields the
    report could not read. A required field that is missing needs a real value instead."""
    principal.require(P.PRISMSUITE_REVIEW)
    row = await get_import(session, principal, import_id)
    _ensure_open(row, version)
    report = _report(row)
    f = _report_field(report, path)
    if f.status == FieldStatus.CORRECTED:
        raise Conflict("This field was already confirmed.")
    if f.status == FieldStatus.OK:
        raise ValidationFailed("This field was read without problems.", code="nothing_to_resolve")
    if f.required and f.status in (FieldStatus.MISSING, FieldStatus.UNREADABLE):
        raise ValidationFailed(
            "This required field has no value. Set one with a correction.",
            code="value_required",
        )
    before = f.status.value
    _mark_corrected(report, path, None, f"Confirmed by a reviewer: {reason}")
    row.read_report = report.model_dump(mode="json")
    session.add(
        AuditCorrection(
            import_id=row.id,
            path=path,
            old_value={"status": before},
            new_value={"acknowledged": True},
            reason=reason,
            corrected_by=principal.user_id,
        )
    )
    await record(
        session,
        audit_context(principal),
        action="resolve_field",
        entity_type="audit_import",
        entity_id=row.id,
        before={path: before},
        after={path: "confirmed", "reason": reason},
        only_changes=False,
    )
    await session.commit()
    return row


async def approve(
    session: AsyncSession,
    principal: Principal,
    import_id: uuid.UUID,
    *,
    note: str | None,
    version: int,
) -> AuditImport:
    principal.require(P.PRISMSUITE_APPROVE)
    row = await get_import(session, principal, import_id)
    _ensure_open(row, version)

    # Doer != verifier: neither the importer nor anyone who corrected a value may approve.
    ensure_different_people(row.imported_by, principal.user_id, "audit import")
    for c in await list_corrections(session, row.id):
        ensure_different_people(c.corrected_by, principal.user_id, "audit correction")

    report = _report(row)
    blocking = report.blocking
    if blocking:
        names = ", ".join(f.path for f in blocking[:5])
        raise Conflict(
            f"{len(blocking)} required field(s) still cannot be read: {names}. Correct them first.",
            code="audit_fields_unresolved",
        )
    conflicts = [f for f in report.fields if f.status == FieldStatus.CONFLICT]
    if conflicts:
        names = ", ".join(f.path for f in conflicts[:5])
        raise Conflict(
            f"{len(conflicts)} field(s) have conflicting values in the report: {names}. "
            "Confirm each value with a correction.",
            code="audit_conflicts_unresolved",
        )

    previous = await session.scalars(
        select(AuditImport).where(
            AuditImport.project_id == row.project_id,
            AuditImport.status == APPROVED,
            AuditImport.kind == row.kind,
        )
    )
    for old in previous:
        old.status = SUPERSEDED
    await session.flush()

    row.status = APPROVED
    row.decided_by = principal.user_id
    row.decided_at = utcnow()
    row.decision_note = note
    await session.flush()
    if row.kind == "baseline":  # the rescan is evidence for the certificate, not a gate output
        outbox.publish(
            session,
            artifact_locked_event(
                project_id=row.project_id,
                stage=Stage.AUDIT_INTAKE,
                artifact_type=ARTIFACT_TYPE,
                artifact_id=str(row.id),
                artifact_version=row.revision,
                title=f"PrismSuite audit, revision {row.revision}",
                locked_by=principal.user_id,
            ),
        )
    outbox.publish(
        session,
        DomainEvent(
            event_type=SNAPSHOT_APPROVED,
            aggregate_type=ARTIFACT_TYPE,
            aggregate_id=str(row.id),
            actor_id=principal.user_id,
            payload={
                "project_id": str(row.project_id),
                "import_id": str(row.id),
                "kind": row.kind,
                "revision": row.revision,
            },
        ),
    )
    await record(
        session,
        audit_context(principal),
        action="approve",
        entity_type="audit_import",
        entity_id=row.id,
        after={"status": APPROVED, "revision": row.revision, "note": note},
        only_changes=False,
    )
    await session.commit()
    return row


async def reject(
    session: AsyncSession,
    principal: Principal,
    import_id: uuid.UUID,
    *,
    reason: str,
    version: int,
) -> AuditImport:
    principal.require(P.PRISMSUITE_APPROVE)
    row = await get_import(session, principal, import_id)
    _ensure_open(row, version)
    row.status = REJECTED
    row.decided_by = principal.user_id
    row.decided_at = utcnow()
    row.decision_note = reason
    await record(
        session,
        audit_context(principal),
        action="reject",
        entity_type="audit_import",
        entity_id=row.id,
        after={"status": REJECTED, "reason": reason},
        only_changes=False,
    )
    await session.commit()
    return row


async def latest_snapshot(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, kind: str = "baseline"
) -> tuple[AuditImport, AuditSnapshot]:
    """The approved report if there is one, otherwise the newest one still in review (with the
    reviewer's corrections so far). For estimates only; official steps use the approved one."""
    await get_project_ref(session, principal, project_id)
    row = await session.scalar(
        select(AuditImport)
        .where(
            AuditImport.project_id == project_id,
            AuditImport.kind == kind,
            AuditImport.status.in_((APPROVED, IN_REVIEW)),
        )
        .order_by((AuditImport.status == APPROVED).desc(), AuditImport.revision.desc())
        .limit(1)
    )
    if row is None:
        raise NotFound("Upload the PrismSuite report first.", code="no_audit")
    return row, AuditSnapshot.model_validate(row.snapshot)


async def approved_snapshot(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, kind: str = "baseline"
) -> tuple[AuditImport, AuditSnapshot]:
    await get_project_ref(session, principal, project_id)
    row = await session.scalar(
        select(AuditImport).where(
            AuditImport.project_id == project_id,
            AuditImport.status == APPROVED,
            AuditImport.kind == kind,
        )
    )
    if row is None:
        raise NotFound(f"No approved {kind} audit for this project yet.")
    return row, AuditSnapshot.model_validate(row.snapshot)
