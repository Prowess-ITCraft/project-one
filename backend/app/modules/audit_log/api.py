from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pagination import Page, PageParams, page_params, paginate_rows
from app.modules.audit_log import service
from app.modules.audit_log.models import AuditEntry
from app.modules.identity.contracts import P, Principal, require

router = APIRouter(prefix="/audit-log", tags=["audit log"])
Session = Annotated[AsyncSession, Depends(get_session)]


class AuditEntryOut(BaseModel):
    id: int
    occurred_at: datetime
    actor_id: uuid.UUID | None
    actor_label: str
    action: str
    entity_type: str
    entity_id: str
    ip: str | None
    request_id: str | None
    before: Any
    after: Any


class ChainOut(BaseModel):
    ok: bool
    checked: int
    first_bad_id: int | None
    reason: str | None


@router.get("", response_model=Page[AuditEntryOut])
async def list_entries(
    session: Session,
    _: Annotated[Principal, Depends(require(P.AUDIT_READ))],
    params: Annotated[PageParams, Depends(page_params)],
    entity_type: Annotated[str | None, Query(max_length=60)] = None,
    entity_id: Annotated[str | None, Query(max_length=80)] = None,
    actor_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Page[AuditEntryOut]:
    stmt = select(AuditEntry).order_by(AuditEntry.id.desc())
    if entity_type:
        stmt = stmt.where(AuditEntry.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditEntry.entity_id == entity_id)
    if actor_id:
        stmt = stmt.where(AuditEntry.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditEntry.action == action)
    if since:
        stmt = stmt.where(AuditEntry.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditEntry.occurred_at < until)
    rows, total = await paginate_rows(session, stmt, params)
    items: list[AuditEntryOut] = []
    for e in rows:
        before, after = await service.reveal(session, e)
        items.append(
            AuditEntryOut(
                id=e.id,
                occurred_at=e.occurred_at,
                actor_id=e.actor_id,
                actor_label=e.actor_label,
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                ip=str(e.ip) if e.ip else None,
                request_id=e.request_id,
                before=before,
                after=after,
            )
        )
    return Page(items=items, page=params.page, size=params.size, total=total)


@router.get("/verify", response_model=ChainOut, summary="Check the hash chain for tampering")
async def verify(
    session: Session, _: Annotated[Principal, Depends(require(P.AUDIT_VERIFY))]
) -> ChainOut:
    r = await service.verify_chain(session)
    return ChainOut(ok=r.ok, checked=r.checked, first_bad_id=r.first_bad_id, reason=r.reason)
