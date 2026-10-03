from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.identity.contracts import CurrentPrincipal, P, Principal, require
from app.modules.notifications import service

account_router = APIRouter(prefix="/account", tags=["notifications"])
ops_router = APIRouter(prefix="/notifications", tags=["notifications"])
Session = Annotated[AsyncSession, Depends(get_session)]
Auditor = Annotated[Principal, Depends(require(P.AUDIT_READ))]


class PrefOut(BaseModel):
    template: str
    label: str
    optional: bool
    enabled: bool


class PrefIn(BaseModel):
    enabled: bool


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    channel: str
    to_address: str
    template: str
    subject: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


@account_router.get("/notification-preferences", response_model=list[PrefOut])
async def preferences(session: Session, principal: CurrentPrincipal) -> list[PrefOut]:
    return [PrefOut(**p) for p in await service.list_preferences(session, principal.user_id)]


@account_router.put("/notification-preferences/{template}", status_code=status.HTTP_204_NO_CONTENT)
async def set_preference(
    session: Session, principal: CurrentPrincipal, template: str, body: PrefIn
) -> Response:
    await service.set_preference(session, principal.user_id, template, body.enabled)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ops_router.get("", response_model=list[NotificationOut])
async def list_notifications(
    session: Session, principal: Auditor, status: str | None = None, limit: int = 50
) -> list[NotificationOut]:
    """For operations: what was queued, sent, skipped or failed. Message bodies are not shown."""
    return [
        NotificationOut.model_validate(n, from_attributes=True)
        for n in await service.list_notifications(session, principal, status, limit)
    ]


routers = [account_router, ops_router]
