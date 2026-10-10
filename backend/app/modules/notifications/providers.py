"""Delivery channels. Email works today over SMTP (Mailpit in development) and Web Push with our
own VAPID keys (no push service account, no cost). In-app messages need no provider: they are
stored and shown in the notification centre. SMS and WhatsApp are named interfaces: a provider is
plugged in by implementing `Provider` and adding it to `PROVIDERS`. Until then those messages are
recorded as skipped, never dropped silently."""

from __future__ import annotations

import asyncio
import json
import smtplib
from email.message import EmailMessage
from typing import Any, Protocol

from app.core.config import get_settings


class NotConfigured(Exception):
    """The channel has no provider set up."""


class DeliveryError(Exception):
    """The provider was reached but refused or failed. The message is retried."""


class Gone(Exception):
    """The push subscription no longer exists (the person removed the app or revoked it)."""


class Provider(Protocol):
    channel: str

    async def send(self, to: str, subject: str, body: str) -> None: ...


class EmailProvider:
    channel = "email"

    async def send(self, to: str, subject: str, body: str) -> None:
        s = get_settings()
        if not s.smtp_host:
            raise NotConfigured("No email server is set up (P1_SMTP_HOST is empty).")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
        msg.set_content(body)

        def _send() -> None:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                if s.smtp_starttls:
                    smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password.get_secret_value())
                smtp.send_message(msg)

        try:
            await asyncio.to_thread(_send)
        except (OSError, smtplib.SMTPException) as exc:
            raise DeliveryError(f"{type(exc).__name__}: {exc}"[:280]) from exc


class UnconfiguredProvider:
    def __init__(self, channel: str) -> None:
        self.channel = channel

    async def send(self, to: str, subject: str, body: str) -> None:
        raise NotConfigured(f"No {self.channel} provider is set up yet.")


class PushProvider:
    """Web Push (RFC 8030, 8291, 8292) through the browser's own push service, signed with our
    VAPID key. Only a title, one line and a link are sent: never a price or a secret."""

    channel = "push"

    async def send_push(self, subscription: dict[str, Any], payload: dict[str, str]) -> None:
        s = get_settings()
        if not s.push_enabled:
            raise NotConfigured("Web Push is not set up (P1_VAPID_PUBLIC_KEY is empty).")
        from pywebpush import WebPushException, webpush

        def _send() -> None:
            webpush(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=s.vapid_private_key.get_secret_value(),
                vapid_claims={"sub": s.vapid_subject},
                ttl=24 * 3600,
                timeout=10,
            )

        try:
            await asyncio.to_thread(_send)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                raise Gone(str(status)) from exc
            raise DeliveryError(f"push refused ({status}): {exc}"[:280]) from exc
        except (OSError, ValueError) as exc:
            raise DeliveryError(f"{type(exc).__name__}: {exc}"[:280]) from exc


PUSH = PushProvider()

PROVIDERS: dict[str, Provider] = {
    "email": EmailProvider(),
    "sms": UnconfiguredProvider("sms"),
    "whatsapp": UnconfiguredProvider("whatsapp"),
}
