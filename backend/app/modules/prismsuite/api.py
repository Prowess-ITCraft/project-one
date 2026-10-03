from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.core.ratelimit import Limit, check
from app.modules.identity.contracts import P, Principal, require
from app.modules.prismsuite import service
from app.modules.prismsuite.models import AuditImport
from app.modules.prismsuite.schemas import (
    CorrectionIn,
    CorrectionOut,
    DecisionIn,
    ImportCreateIn,
    ImportDetailOut,
    ImportOut,
    RejectIn,
    ResolveIn,
)

router = APIRouter(prefix="/prismsuite/imports", tags=["prismsuite"])
Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]


def _out(row: AuditImport) -> ImportOut:
    out = ImportOut.model_validate(row, from_attributes=True)
    out.read_summary = service.read_summary(row)
    return out


async def _detail(session: AsyncSession, row: AuditImport) -> ImportDetailOut:
    corrections = await service.list_corrections(session, row.id)
    base = _out(row).model_dump()
    return ImportDetailOut(
        **base,
        snapshot=row.snapshot,
        read_report=row.read_report,
        corrections=[CorrectionOut.model_validate(c, from_attributes=True) for c in corrections],
    )


@router.post("", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
async def create_import(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PRISMSUITE_IMPORT))],
    body: ImportCreateIn,
    guard: Idem,
) -> Any:
    await check(f"user:{principal.user_id}", Limit("audit_import", 10, strict=True))

    async def work() -> ImportOut:
        row = await service.create_import(
            session, principal, project_id=body.project_id, file_id=body.file_id, kind=body.kind
        )
        return _out(row)

    return await run_idempotent(guard, str(principal.user_id), 201, work)


@router.get("/by-project/{project_id}", response_model=list[ImportOut])
async def list_for_project(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PRISMSUITE_REVIEW))],
    project_id: uuid.UUID,
) -> list[ImportOut]:
    return [_out(r) for r in await service.list_imports(session, principal, project_id)]


@router.get("/{import_id}", response_model=ImportDetailOut)
async def get_import(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PRISMSUITE_REVIEW))],
    import_id: uuid.UUID,
) -> ImportDetailOut:
    return await _detail(session, await service.get_import(session, principal, import_id))


@router.post("/{import_id}/corrections", response_model=ImportDetailOut)
async def add_correction(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PRISMSUITE_REVIEW))],
    import_id: uuid.UUID,
    body: CorrectionIn,
) -> ImportDetailOut:
    row = await service.correct(
        session,
        principal,
        import_id,
        path=body.path,
        value=body.value,
        reason=body.reason,
        version=body.version,
        resolves=body.resolves,
    )
    return await _detail(session, row)


@router.post("/{import_id}/resolutions", response_model=ImportDetailOut)
async def resolve_field(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PRISMSUITE_REVIEW))],
    import_id: uuid.UUID,
    body: ResolveIn,
) -> ImportDetailOut:
    row = await service.resolve_field(
        session, principal, import_id, path=body.path, reason=body.reason, version=body.version
    )
    return await _detail(session, row)


@router.post("/{import_id}/approve", response_model=ImportOut)
async def approve(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PRISMSUITE_APPROVE))],
    import_id: uuid.UUID,
    body: DecisionIn,
    guard: Idem,
) -> Any:
    async def work() -> ImportOut:
        row = await service.approve(
            session, principal, import_id, note=body.note, version=body.version
        )
        return _out(row)

    return await run_idempotent(guard, str(principal.user_id), 200, work)


@router.post("/{import_id}/reject", response_model=ImportOut)
async def reject(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.PRISMSUITE_APPROVE))],
    import_id: uuid.UUID,
    body: RejectIn,
) -> ImportOut:
    row = await service.reject(
        session, principal, import_id, reason=body.reason, version=body.version
    )
    return _out(row)


routers = [router]
