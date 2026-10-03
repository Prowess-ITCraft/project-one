from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk

CHANNELS = ("email", "sms", "whatsapp")
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


class NotificationPref(Base):
    """A person's choice to stop one optional kind of message. Security messages cannot be muted."""

    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    template: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
