"""Public surface of the notifications module. Other modules import only from here."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.notifications import service as _service
from app.modules.notifications.models import Notification

NotificationRow = Notification


def queue_email(
    session: AsyncSession,
    *,
    to_address: str,
    template: str,
    context: dict[str, Any],
    dedupe_key: str | None = None,
    related: tuple[str, str] | None = None,
) -> Notification:
    """Queue an email to someone outside the system, such as a customer contact. The caller
    commits, then calls `deliver_now`."""
    return _service.queue(
        session,
        to_address=to_address,
        template=template,
        context=context,
        dedupe_key=dedupe_key,
        related=related,
    )


async def queue_email_to_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str,
    template: str,
    context: dict[str, Any],
    dedupe_key: str | None = None,
    related: tuple[str, str] | None = None,
    link: str | None = None,
) -> Notification:
    """Queue a message to a user: email, plus the notification centre and push to their
    devices, honouring the channels they turned off. `link` is where the message leads in the
    web app; by default it follows `related`."""
    return await _service.queue_for_user(
        session,
        user_id=user_id,
        email=email,
        template=template,
        context=context,
        dedupe_key=dedupe_key,
        related=related,
        link=link,
    )


async def already_queued(session: AsyncSession, dedupe_key: str) -> bool:
    """True when a message with this dedupe key exists, so a scheduled job can skip it."""
    from sqlalchemy import select

    return (
        await session.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key))
    ) is not None


async def deliver_now(maker: async_sessionmaker[AsyncSession], ids: list[uuid.UUID]) -> None:
    await _service.deliver_ids(maker, ids)


async def send_pending(maker: async_sessionmaker[AsyncSession], limit: int = 50) -> int:
    """Send or retry everything due. Run by the worker every minute."""
    return await _service.send_pending(maker, limit)


__all__ = [
    "NotificationRow",
    "already_queued",
    "deliver_now",
    "queue_email",
    "queue_email_to_user",
    "send_pending",
]
