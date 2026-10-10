from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk

# in_app: the notification centre in the web app. push: Web Push to a phone or browser that
# subscribed. sms and whatsapp: adapters that stay off until a paid provider is chosen.
CHANNELS = ("email", "in_app", "push", "sms", "whatsapp")
# The channels a person can choose per kind of message on their preferences page.
PERSONAL_CHANNELS = ("email", "in_app", "push")
STATUSES = ("pending", "sent", "failed", "skipped")


class Notification(UUIDPk, Timestamps, Base):
    """One message to one person on one channel. It is written in the same transaction as the
    thing that caused it, so a message is never lost and never sent for a change that rolled
    back."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notifications_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
        Index("ix_notifications_due", "status", "next_attempt_at"),
        Index(
            "ix_notifications_inbox",
            "to_user_id",
            "created_at",
            postgresql_where=text("channel = 'in_app'"),
        ),
    )

    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    to_address: Mapped[str] = mapped_column(String(254), nullable=False)
    to_user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    template: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    related_type: Mapped[str | None] = mapped_column(String(40))
    related_id: Mapped[str | None] = mapped_column(String(64))
    # The in-app and push copies of an email point at it, so sending the email right after the
    # commit sends them too.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    # Where the message leads in the web app ("/field/<task id>"). Never a price or a secret.
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPref(Base):
    """A person's choice to stop one optional kind of message on one channel. Security
    messages cannot be muted."""

    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    template: Mapped[str] = mapped_column(String(40), primary_key=True)
    channel: Mapped[str] = mapped_column(String(10), primary_key=True, default="email")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PushSubscription(UUIDPk, Base):
    """One browser or installed app that agreed to receive Web Push for a person. The keys are
    the browser's public keys for encrypting messages to it; they are not secrets of ours."""

    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
