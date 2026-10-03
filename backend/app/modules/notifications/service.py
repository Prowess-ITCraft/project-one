"""Queue, send and retry messages. Sending never blocks the request that caused it."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound, ValidationFailed
from app.core.timeutil import utcnow
from app.modules.identity.contracts import P, Principal
from app.modules.notifications import providers, templates
from app.modules.notifications.models import CHANNELS, Notification, NotificationPref

log = structlog.get_logger(__name__)
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (60, 300, 1800, 7200)
REMOVED = "[removed after sending]"


def queue(
    session: AsyncSession,
    *,
    to_address: str,
    template: str,
    context: dict[str, Any],
    channel: str = "email",
    to_user_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    related: tuple[str, str] | None = None,
    muted: bool = False,
) -> Notification:
    """Add a message in the caller's transaction. The caller commits, then calls `deliver_ids`."""
    if channel not in CHANNELS or template not in templates.TEMPLATES:
        raise ValidationFailed("Unknown message channel or template.")
    subject, body = templates.render(template, context)
    n = Notification(
        channel=channel,
        to_address=to_address,
        to_user_id=to_user_id,
        template=template,
        subject=subject,
        body=body,
        dedupe_key=dedupe_key,
        related_type=related[0] if related else None,
        related_id=related[1] if related else None,
    )
    if muted:
        n.status, n.last_error = "skipped", "Muted by the recipient."
    session.add(n)
    return n


async def queue_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str,
    template: str,
    context: dict[str, Any],
    dedupe_key: str | None = None,
    related: tuple[str, str] | None = None,
) -> Notification:
    """Like `queue`, honouring the person's muted kinds. Security messages cannot be muted."""
    t = templates.TEMPLATES[template]
    muted = False
    if t.optional:
        pref = await session.get(NotificationPref, (user_id, template))
        muted = pref is not None and not pref.enabled
    return queue(
        session,
        to_address=email,
        to_user_id=user_id,
        template=template,
        context=context,
        dedupe_key=dedupe_key,
        related=related,
        muted=muted,
    )


async def deliver(session: AsyncSession, n: Notification) -> None:
    provider = providers.PROVIDERS[n.channel]
    t = templates.TEMPLATES.get(n.template)
    try:
        await provider.send(n.to_address, n.subject, n.body)
    except providers.NotConfigured as exc:
        n.status, n.last_error = "skipped", str(exc)[:300]
    except providers.DeliveryError as exc:
        n.attempts += 1
        n.last_error = str(exc)[:300]
        if n.attempts >= MAX_ATTEMPTS:
            n.status = "failed"
        else:
            wait = BACKOFF_SECONDS[min(n.attempts - 1, len(BACKOFF_SECONDS) - 1)]
            n.next_attempt_at = utcnow() + timedelta(seconds=wait)
        log.warning("notification_failed", id=str(n.id), attempts=n.attempts)
    else:
        n.status, n.sent_at, n.last_error = "sent", utcnow(), None
        n.attempts += 1
        if t is not None and t.sensitive:
            n.body = REMOVED


async def deliver_ids(maker: async_sessionmaker[AsyncSession], ids: list[uuid.UUID]) -> None:
    """Best effort right after commit, so a code arrives in seconds. The scheduled job retries
    anything this misses."""
    if not ids:
        return
    async with maker() as s:
        for n in await s.scalars(
            select(Notification).where(Notification.id.in_(ids), Notification.status == "pending")
        ):
            await deliver(s, n)
        await s.commit()


async def send_pending(maker: async_sessionmaker[AsyncSession], limit: int = 50) -> int:
    done = 0
    async with maker() as s:
        rows = list(
            await s.scalars(
                select(Notification)
                .where(Notification.status == "pending", Notification.next_attempt_at <= utcnow())
                .order_by(Notification.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for n in rows:
            await deliver(s, n)
            done += 1
        await purge_secrets(s)
        await s.commit()
    return done


async def purge_secrets(session: AsyncSession) -> int:
    """One-time codes are wiped from the table an hour after they were made, sent or not."""
    sensitive = [c for c, t in templates.TEMPLATES.items() if t.sensitive]
    res = await session.execute(
        update(Notification)
        .where(
            Notification.template.in_(sensitive),
            Notification.body != REMOVED,
            Notification.created_at < utcnow() - timedelta(hours=1),
        )
        .values(body=REMOVED)
    )
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


# ------------------------------------------------------------------ preferences and ops


async def list_preferences(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    prefs = {
        p.template: p.enabled
        for p in await session.scalars(
            select(NotificationPref).where(NotificationPref.user_id == user_id)
        )
    }
    return [
        {
            "template": t.code,
            "label": t.subject.split("{{")[0].strip() or t.code.replace("_", " "),
            "optional": t.optional,
            "enabled": prefs.get(t.code, True) if t.optional else True,
        }
        for t in templates.TEMPLATES.values()
    ]


async def set_preference(
    session: AsyncSession, user_id: uuid.UUID, template: str, enabled: bool
) -> None:
    t = templates.TEMPLATES.get(template)
    if t is None:
        raise NotFound("Unknown message kind.")
    if not t.optional:
        raise ValidationFailed("Security messages cannot be turned off.", code="not_optional")
    pref = await session.get(NotificationPref, (user_id, template))
    if pref is None:
        session.add(NotificationPref(user_id=user_id, template=template, enabled=enabled))
    else:
        pref.enabled = enabled
    await session.commit()


async def list_notifications(
    session: AsyncSession, principal: Principal, status: str | None, limit: int
) -> list[Notification]:
    principal.require(P.AUDIT_READ)
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(min(limit, 200))
    if status:
        stmt = stmt.where(Notification.status == status)
    return list(await session.scalars(stmt))
