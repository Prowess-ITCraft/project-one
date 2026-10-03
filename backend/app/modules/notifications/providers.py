"""Delivery channels. Email works today over SMTP (Mailpit in development). SMS and WhatsApp are
named interfaces: a provider is plugged in by implementing `Provider` and adding it to `PROVIDERS`.
Until then those messages are recorded as skipped, never dropped silently."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import get_settings


class NotConfigured(Exception):
    """The channel has no provider set up."""


class DeliveryError(Exception):
    """The provider was reached but refused or failed. The message is retried."""


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


PROVIDERS: dict[str, Provider] = {
    "email": EmailProvider(),
    "sms": UnconfiguredProvider("sms"),
    "whatsapp": UnconfiguredProvider("whatsapp"),
}
