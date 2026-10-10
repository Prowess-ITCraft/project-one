"""Queue, send and retry messages. Sending never blocks the request that caused it.

A message to a staff member goes out on up to three channels they choose per kind of message:
email, the in-app notification centre and Web Push to the phones and browsers they subscribed.
Messages to people outside the system (customer contacts) are email only."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.errors import NotFound, ValidationFailed
from app.core.timeutil import utcnow
from app.modules.identity.contracts import P, Principal
from app.modules.notifications import providers, templates
from app.modules.notifications.models import (
    CHANNELS,
    PERSONAL_CHANNELS,
    Notification,
    NotificationPref,
    PushSubscription,
)

log = structlog.get_logger(__name__)
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (60, 300, 1800, 7200)
REMOVED = "[removed after sending]"
# Push services browsers use. A subscription pointing anywhere else is refused, so a signed-in
# person cannot make the server call an address of their choosing.
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
    "notify.windows.com",
)
MAX_SUBSCRIPTIONS_PER_USER = 10


def _link_for(related: tuple[str, str] | None) -> str | None:
    if related is None:
        return None
    kind, rid = related
    return {
        "task_run": f"/field/{rid}",
        "project": f"/projects/{rid}",
        "boq_project": f"/projects/{rid}#boq",
    }.get(kind)


def _child_key(key: str | None, suffix: str) -> str | None:
    if key is None:
        return None
    full = f"{key}:{suffix}"
    if len(full) <= 120:
        return full
    return f"h:{hashlib.sha256(full.encode()).hexdigest()}:{suffix}"[:120]


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
    link: str | None = None,
) -> Notification:
    """Add a message in the caller's transaction. The caller commits, then calls `deliver_ids`."""
    if channel not in CHANNELS or template not in templates.TEMPLATES:
        raise ValidationFailed("Unknown message channel or template.")
    subject, body = templates.render(template, context)
    n = Notification(
        id=uuid.uuid4(),
        channel=channel,
        to_address=to_address,
        to_user_id=to_user_id,
        template=template,
        subject=subject,
        body=body,
        dedupe_key=dedupe_key,
        related_type=related[0] if related else None,
        related_id=related[1] if related else None,
        link=link or _link_for(related),
    )
    if muted:
        n.status, n.last_error = "skipped", "Muted by the recipient."
    session.add(n)
    return n


async def _channel_prefs(
    session: AsyncSession, user_id: uuid.UUID, template: str
) -> dict[str, bool]:
    rows = await session.scalars(
        select(NotificationPref).where(
            NotificationPref.user_id == user_id, NotificationPref.template == template
        )
    )
    return {p.channel: p.enabled for p in rows}


async def queue_for_user(
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
    """The email, plus a copy in the notification centre and on each subscribed device, as the
    person chose. Security messages cannot be muted. Returns the email; sending it with
    `deliver_ids` sends the push copies too."""
    t = templates.TEMPLATES[template]
    prefs = await _channel_prefs(session, user_id, template) if t.optional else {}

    def on(channel: str) -> bool:
        return not t.optional or prefs.get(channel, True)

    n = queue(
        session,
        to_address=email,
        to_user_id=user_id,
        template=template,
        context=context,
        dedupe_key=dedupe_key,
        related=related,
        muted=not on("email"),
        link=link,
    )
    if t.sensitive:
        return n  # one-time codes go by email only
    now = utcnow()
    if on("in_app"):
        session.add(
            Notification(
                id=uuid.uuid4(),
                channel="in_app",
                to_address="in-app",
                to_user_id=user_id,
                template=template,
                subject=n.subject,
                body=n.body,
                status="sent",
                sent_at=now,
                dedupe_key=_child_key(dedupe_key, "in_app"),
                related_type=n.related_type,
                related_id=n.related_id,
                parent_id=n.id,
                link=n.link,
            )
        )
    if on("push") and get_settings().push_enabled:
        for sub in await session.scalars(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        ):
            session.add(
                Notification(
                    id=uuid.uuid4(),
                    channel="push",
                    to_address=str(sub.id),
                    to_user_id=user_id,
                    template=template,
                    subject=n.subject,
                    body=n.body,
                    dedupe_key=_child_key(dedupe_key, f"push:{sub.id}"),
                    related_type=n.related_type,
                    related_id=n.related_id,
                    parent_id=n.id,
                    link=n.link,
                )
            )
    return n


def push_payload(n: Notification) -> dict[str, str]:
    """Title, one line and where it leads. The first line after the greeting says what
    happened; nothing more goes to a lock screen."""
    lines = [ln.strip() for ln in n.body.splitlines() if ln.strip()]
    line = next((ln for ln in lines if not ln.lower().startswith("hello")), n.subject)
    return {"title": n.subject, "body": line[:180], "url": n.link or "/", "tag": n.template}


def _retry_later(n: Notification, error: str) -> None:
    n.attempts += 1
    n.last_error = error[:300]
    if n.attempts >= MAX_ATTEMPTS:
        n.status = "failed"
    else:
        wait = BACKOFF_SECONDS[min(n.attempts - 1, len(BACKOFF_SECONDS) - 1)]
        n.next_attempt_at = utcnow() + timedelta(seconds=wait)
    log.warning("notification_failed", id=str(n.id), channel=n.channel, attempts=n.attempts)


async def _deliver_push(session: AsyncSession, n: Notification) -> None:
    try:
        sub = await session.get(PushSubscription, uuid.UUID(n.to_address))
    except ValueError:
        sub = None
    if sub is None:
        n.status, n.last_error = "skipped", "The device unsubscribed."
        return
    info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
    try:
        await providers.PUSH.send_push(info, push_payload(n))
    except providers.Gone:
        n.status, n.last_error = "skipped", "The device no longer accepts messages."
        await session.delete(sub)
    except providers.NotConfigured as exc:
        n.status, n.last_error = "skipped", str(exc)[:300]
    except providers.DeliveryError as exc:
        sub.failures += 1
        _retry_later(n, str(exc))
    else:
        n.status, n.sent_at, n.last_error = "sent", utcnow(), None
        n.attempts += 1
        sub.last_success_at, sub.failures = utcnow(), 0


async def deliver(session: AsyncSession, n: Notification) -> None:
    if n.channel == "in_app":
        n.status, n.sent_at = "sent", n.sent_at or utcnow()
        return
    if n.channel == "push":
        await _deliver_push(session, n)
        return
    provider = providers.PROVIDERS[n.channel]
    t = templates.TEMPLATES.get(n.template)
    try:
        await provider.send(n.to_address, n.subject, n.body)
    except providers.NotConfigured as exc:
        n.status, n.last_error = "skipped", str(exc)[:300]
    except providers.DeliveryError as exc:
        _retry_later(n, str(exc))
    else:
        n.status, n.sent_at, n.last_error = "sent", utcnow(), None
        n.attempts += 1
        if t is not None and t.sensitive:
            n.body = REMOVED


async def deliver_ids(maker: async_sessionmaker[AsyncSession], ids: list[uuid.UUID]) -> None:
    """Best effort right after commit, so a code arrives in seconds and a push reaches the phone
    at once. The scheduled job retries anything this misses."""
    if not ids:
        return
    async with maker() as s:
        for n in await s.scalars(
            select(Notification).where(
                (Notification.id.in_(ids)) | (Notification.parent_id.in_(ids)),
                Notification.status == "pending",
            )
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


# ------------------------------------------------------------------ preferences


async def list_preferences(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    prefs: dict[tuple[str, str], bool] = {
        (p.template, p.channel): p.enabled
        for p in await session.scalars(
            select(NotificationPref).where(NotificationPref.user_id == user_id)
        )
    }
    out = []
    for t in templates.TEMPLATES.values():
        if t.sensitive:
            continue  # codes for customers, never sent to staff
        channels = {
            c: (prefs.get((t.code, c), True) if t.optional else True) for c in PERSONAL_CHANNELS
        }
        out.append(
            {
                "template": t.code,
                "label": t.label,
                "optional": t.optional,
                "enabled": channels["email"],
                "channels": channels,
            }
        )
    return out


async def set_preference(
    session: AsyncSession, user_id: uuid.UUID, template: str, enabled: bool, channel: str = "email"
) -> None:
    t = templates.TEMPLATES.get(template)
    if t is None or t.sensitive:
        raise NotFound("Unknown message kind.")
    if channel not in PERSONAL_CHANNELS:
        raise ValidationFailed("Choose email, in_app or push.", code="unknown_channel")
    if not t.optional:
        raise ValidationFailed("Security messages cannot be turned off.", code="not_optional")
    pref = await session.get(NotificationPref, (user_id, template, channel))
    if pref is None:
        session.add(
            NotificationPref(user_id=user_id, template=template, channel=channel, enabled=enabled)
        )
    else:
        pref.enabled = enabled
    await session.commit()


# ------------------------------------------------------------------ the notification centre


async def inbox(
    session: AsyncSession, user_id: uuid.UUID, *, unread_only: bool, limit: int
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.to_user_id == user_id, Notification.channel == "in_app")
        .order_by(Notification.created_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(await session.scalars(stmt))


async def unread_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.to_user_id == user_id,
                Notification.channel == "in_app",
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


async def mark_read(
    session: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID | None
) -> int:
    """Mark one message read, or all of them when no id is given."""
    stmt = (
        update(Notification)
        .where(
            Notification.to_user_id == user_id,
            Notification.channel == "in_app",
            Notification.read_at.is_(None),
        )
        .values(read_at=utcnow())
    )
    if notification_id is not None:
        stmt = stmt.where(Notification.id == notification_id)
    res = await session.execute(stmt)
    await session.commit()
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


# ------------------------------------------------------------------ Web Push subscriptions


def push_status() -> dict[str, Any]:
    s = get_settings()
    return {"enabled": s.push_enabled, "public_key": s.vapid_public_key or None}


def _check_endpoint(endpoint: str) -> None:
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in PUSH_HOSTS):
        raise ValidationFailed(
            "This is not a browser push address we accept.", code="push_endpoint_refused"
        )


async def subscribe_push(
    session: AsyncSession,
    principal: Principal,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> PushSubscription:
    """Save one device's subscription. The same device subscribing again updates its keys; a
    subscription that moved to another person (a shared phone) moves with the sign-in."""
    if not get_settings().push_enabled:
        raise ValidationFailed("Web Push is not set up on this server.", code="push_off")
    _check_endpoint(endpoint)
    sub = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    if sub is None:
        count = await session.scalar(
            select(func.count())
            .select_from(PushSubscription)
            .where(PushSubscription.user_id == principal.user_id)
        )
        if int(count or 0) >= MAX_SUBSCRIPTIONS_PER_USER:
            raise ValidationFailed(
                "Too many devices get messages for you. Turn them off on a device you no "
                "longer use.",
                code="too_many_devices",
            )
        sub = PushSubscription(user_id=principal.user_id, endpoint=endpoint, p256dh="", auth="")
        session.add(sub)
    sub.user_id, sub.p256dh, sub.auth = principal.user_id, p256dh, auth
    sub.user_agent = (user_agent or "")[:200] or None
    sub.failures = 0
    await session.commit()
    await session.refresh(sub)
    return sub


async def unsubscribe_push(session: AsyncSession, principal: Principal, endpoint: str) -> bool:
    sub = await session.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint == endpoint, PushSubscription.user_id == principal.user_id
        )
    )
    if sub is None:
        return False
    await session.delete(sub)
    await session.commit()
    return True


async def device_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(PushSubscription)
            .where(PushSubscription.user_id == user_id)
        )
        or 0
    )


async def send_test(session: AsyncSession, principal: Principal) -> list[uuid.UUID]:
    """A test message to the signed-in person on every channel they have, so they can see that
    push reaches their phone."""
    n = await queue_for_user(
        session,
        user_id=principal.user_id,
        email=principal.email,
        template="test_message",
        context={"name": principal.full_name},
        link="/account",
    )
    n.status, n.last_error = "skipped", "Test messages are not emailed."
    await session.commit()
    return [n.id]


# ------------------------------------------------------------------ operations


async def list_notifications(
    session: AsyncSession, principal: Principal, status: str | None, limit: int
) -> list[Notification]:
    principal.require(P.AUDIT_READ)
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(min(limit, 200))
    if status:
        stmt = stmt.where(Notification.status == status)
    return list(await session.scalars(stmt))
