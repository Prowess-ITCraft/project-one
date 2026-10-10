"""Messages: queued with the change, sent after it, retried with backoff, mutable only when they
are not about security, and one-time codes wiped from the log."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.core.db import get_sessionmaker
from app.core.timeutil import utcnow
from app.modules.identity.permissions import Role
from app.modules.notifications import providers, service
from app.modules.notifications.models import Notification
from tests.helpers import make_user

API = "/api/v1"


class Flaky:
    channel = "email"

    def __init__(self, fail: int) -> None:
        self.fail, self.sent = fail, 0

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            self.fail -= 1
            raise providers.DeliveryError("mail server said no")
        self.sent += 1


async def test_preferences_mute_optional_messages_only(client: Any) -> None:
    pm = await make_user(client, Role.PROJECT_MANAGER)
    prefs = (await client.get(f"{API}/account/notification-preferences", headers=pm.headers)).json()
    kinds = {p["template"]: p for p in prefs}
    assert kinds["task_update"]["optional"] is True
    assert kinds["verify_requested"]["optional"] is False
    assert "otp_check_in" not in kinds  # customer codes never go to staff
    r = await client.put(
        f"{API}/account/notification-preferences/verify_requested",
        json={"enabled": False},
        headers=pm.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "not_optional"
    r = await client.put(
        f"{API}/account/notification-preferences/task_update",
        json={"enabled": False},
        headers=pm.headers,
    )
    assert r.status_code == 204
    async with get_sessionmaker()() as s:
        n = await service.queue_for_user(
            s,
            user_id=pm.id,
            email="pm@example.com",
            template="task_update",
            context={
                "name": "A",
                "project": "P",
                "task": "T",
                "state": "closed",
                "note": "",
                "actor": "B",
                "at": "x",
            },
        )
        await s.commit()
        assert n.status == "skipped"


async def test_failures_are_retried_with_backoff_then_given_up(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_user(client, Role.ADMIN)
    flaky = Flaky(fail=10)
    monkeypatch.setitem(providers.PROVIDERS, "email", flaky)
    maker = get_sessionmaker()
    async with maker() as s:
        n = service.queue(
            s,
            to_address="a@example.com",
            template="run_returned",
            context={"name": "A", "task": "T", "project": "P", "reason": "R"},
        )
        await s.commit()
        nid = n.id
    for attempt in range(1, service.MAX_ATTEMPTS + 1):
        async with maker() as s:  # make it due again, as the clock would
            await s.execute(
                update(Notification).values(next_attempt_at=utcnow() - timedelta(seconds=1))
            )
            await s.commit()
        await service.send_pending(maker)
        async with maker() as s:
            row = await s.get(Notification, nid)
            assert row is not None and row.attempts == attempt
    assert row is not None
    assert row.status == "failed" and "said no" in (row.last_error or "")


async def test_codes_are_wiped_after_sending(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    await make_user(client, Role.ADMIN)
    monkeypatch.setitem(providers.PROVIDERS, "email", Flaky(fail=0))
    maker = get_sessionmaker()
    async with maker() as s:
        n = service.queue(
            s,
            to_address="c@example.com",
            template="otp_handover",
            context={
                "name": "C",
                "engineer": "E",
                "task": "T",
                "code": "123456",
                "minutes": 15,
                "project": "P",
            },
        )
        await s.commit()
        nid = n.id
    await service.deliver_ids(maker, [nid])
    async with maker() as s:
        row = await s.get(Notification, nid)
        assert row is not None and row.status == "sent" and "123456" not in row.body


async def test_unsent_codes_are_wiped_after_an_hour(client: Any) -> None:
    await make_user(client, Role.ADMIN)
    maker = get_sessionmaker()
    async with maker() as s:
        n = service.queue(
            s,
            to_address="c@example.com",
            template="otp_check_in",
            context={
                "name": "C",
                "engineer": "E",
                "place": "X",
                "task": "T",
                "code": "654321",
                "minutes": 15,
                "project": "P",
            },
        )
        await s.commit()
        await s.execute(
            update(Notification)
            .where(Notification.id == n.id)
            .values(created_at=utcnow() - timedelta(hours=2))
        )
        await s.commit()
        assert await service.purge_secrets(s) == 1
        await s.commit()
        body = await s.scalar(select(Notification.body).where(Notification.id == n.id))
        assert body == service.REMOVED


async def test_only_auditors_see_the_message_log(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    fe = await make_user(client, Role.FIELD_ENGINEER)
    assert (await client.get(f"{API}/notifications", headers=admin.headers)).status_code == 200
    assert (await client.get(f"{API}/notifications", headers=fe.headers)).status_code == 403
