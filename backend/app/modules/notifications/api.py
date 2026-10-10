from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session, get_sessionmaker
from app.core.ratelimit import Limit, check
from app.modules.identity.contracts import CurrentPrincipal, P, Principal, require
from app.modules.notifications import service

account_router = APIRouter(prefix="/account", tags=["notifications"])
ops_router = APIRouter(prefix="/notifications", tags=["notifications"])
Session = Annotated[AsyncSession, Depends(get_session)]
Auditor = Annotated[Principal, Depends(require(P.AUDIT_READ))]
Channel = Literal["email", "in_app", "push"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrefOut(BaseModel):
    template: str
    label: str
    optional: bool
    enabled: bool  # the email channel, kept for older clients
    channels: dict[str, bool]


class PrefIn(_In):
    enabled: bool
    channel: Channel = "email"


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


class InboxItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    template: str
    subject: str
    body: str
    link: str | None
    created_at: datetime
    read_at: datetime | None


class UnreadOut(BaseModel):
    unread: int


class PushStatusOut(BaseModel):
    enabled: bool
    public_key: str | None
    devices: int


class PushKeysIn(_In):
    p256dh: Annotated[str, StringConstraints(min_length=20, max_length=200)]
    auth: Annotated[str, StringConstraints(min_length=8, max_length=100)]


class PushSubscribeIn(_In):
    endpoint: Annotated[str, StringConstraints(min_length=10, max_length=2000)]
    keys: PushKeysIn
    user_agent: Annotated[str, StringConstraints(max_length=200)] | None = None


class PushEndpointIn(_In):
    endpoint: Annotated[str, StringConstraints(min_length=10, max_length=2000)]


class ReadIn(_In):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    all: bool = False


# ------------------------------------------------------------------ preferences


@account_router.get("/notification-preferences", response_model=list[PrefOut])
async def preferences(session: Session, principal: CurrentPrincipal) -> list[PrefOut]:
    """Each kind of message and the channels it comes on: email, the notification centre and
    push to subscribed devices. Security messages cannot be turned off."""
    return [PrefOut(**p) for p in await service.list_preferences(session, principal.user_id)]


@account_router.put("/notification-preferences/{template}", status_code=status.HTTP_204_NO_CONTENT)
async def set_preference(
    session: Session, principal: CurrentPrincipal, template: str, body: PrefIn
) -> Response:
    await service.set_preference(session, principal.user_id, template, body.enabled, body.channel)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ notification centre


@account_router.get("/notifications", response_model=list[InboxItemOut])
async def my_notifications(
    session: Session,
    principal: CurrentPrincipal,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[InboxItemOut]:
    """Your notification centre, newest first."""
    return [
        InboxItemOut.model_validate(n, from_attributes=True)
        for n in await service.inbox(
            session, principal.user_id, unread_only=unread_only, limit=limit
        )
    ]


@account_router.get("/notifications/unread", response_model=UnreadOut)
async def my_unread(session: Session, principal: CurrentPrincipal) -> UnreadOut:
    return UnreadOut(unread=await service.unread_count(session, principal.user_id))


@account_router.post("/notifications/read", response_model=UnreadOut)
async def mark_read(session: Session, principal: CurrentPrincipal, body: ReadIn) -> UnreadOut:
    """Mark the given messages read, or every message with `all`."""
    if body.all:
        await service.mark_read(session, principal.user_id, None)
    for i in body.ids:
        await service.mark_read(session, principal.user_id, i)
    return UnreadOut(unread=await service.unread_count(session, principal.user_id))


# ------------------------------------------------------------------ Web Push


@account_router.get("/push", response_model=PushStatusOut)
async def push_status(session: Session, principal: CurrentPrincipal) -> PushStatusOut:
    """Whether push is set up on this server, the public key a browser needs to subscribe, and
    how many of your devices receive messages."""
    return PushStatusOut(
        **service.push_status(), devices=await service.device_count(session, principal.user_id)
    )


@account_router.post("/push/subscriptions", status_code=status.HTTP_201_CREATED)
async def push_subscribe(
    session: Session, principal: CurrentPrincipal, body: PushSubscribeIn
) -> dict[str, str]:
    """This browser or installed app agrees to receive messages for you."""
    sub = await service.subscribe_push(
        session,
        principal,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=body.user_agent,
    )
    return {"id": str(sub.id)}


@account_router.post("/push/subscriptions/remove", status_code=status.HTTP_204_NO_CONTENT)
async def push_unsubscribe(
    session: Session, principal: CurrentPrincipal, body: PushEndpointIn
) -> Response:
    """Stop messages to this device (also done on sign-out)."""
    await service.unsubscribe_push(session, principal, body.endpoint)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@account_router.post("/push/test", status_code=status.HTTP_202_ACCEPTED)
async def push_test(session: Session, principal: CurrentPrincipal) -> dict[str, str]:
    """Send yourself a test message in the notification centre and on every subscribed device."""
    await check(f"user:{principal.user_id}", Limit("push_test", 5, strict=True))
    ids = await service.send_test(session, principal)
    await service.deliver_ids(get_sessionmaker(), ids)
    return {"status": "sent"}


# ------------------------------------------------------------------ operations


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
