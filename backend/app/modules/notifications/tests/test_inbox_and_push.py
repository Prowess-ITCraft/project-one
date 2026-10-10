"""The notification centre and Web Push (Phase 12A): every message to a staff member is also
in their notification centre and on their subscribed devices, per channel they choose; push
goes only to real browser push services; a device that is gone is forgotten."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.modules.identity.permissions import Role
from app.modules.notifications import providers, service
from app.modules.notifications.models import Notification, PushSubscription
from tests.helpers import make_user

API = "/api/v1"
CTX = {
    "name": "A",
    "project": "Shakti",
    "task": "T01 Firewall",
    "state": "closed",
    "note": "",
    "actor": "B",
    "at": "x",
}
ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
KEYS = {
    "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
    "auth": "tBHItJI5svbpez7KI4CCXg",
}


class FakePush:
    def __init__(self, gone: bool = False) -> None:
        self.sent: list[tuple[dict[str, Any], dict[str, str]]] = []
        self.gone = gone

    async def send_push(self, subscription: dict[str, Any], payload: dict[str, str]) -> None:
        if self.gone:
            raise providers.Gone("410")
        self.sent.append((subscription, payload))


@pytest.fixture
def push_on(monkeypatch: pytest.MonkeyPatch) -> FakePush:
    s = get_settings()
    monkeypatch.setattr(s, "vapid_public_key", "BPublicKeyForTests")
    monkeypatch.setattr(s, "vapid_private_key", SecretStr("private-key-for-tests"))
    fake = FakePush()
    monkeypatch.setattr(providers, "PUSH", fake)
    return fake


async def _queue(user: Any, template: str = "task_update") -> Notification:
    maker = get_sessionmaker()
    async with maker() as s:
        n = await service.queue_for_user(
            s,
            user_id=user.id,
            email=user.email,
            template=template,
            context=CTX,
            related=("task_run", "11111111-1111-1111-1111-111111111111"),
        )
        await s.commit()
        nid = n.id
    await service.deliver_ids(maker, [nid])
    return n


async def test_every_message_lands_in_the_notification_centre(client: Any) -> None:
    pm = await make_user(client, Role.PROJECT_MANAGER)
    await _queue(pm)
    await _queue(pm)
    inbox = (await client.get(f"{API}/account/notifications", headers=pm.headers)).json()
    assert len(inbox) == 2 and inbox[0]["subject"].startswith("Shakti")
    assert inbox[0]["link"] == "/field/11111111-1111-1111-1111-111111111111"
    assert (await client.get(f"{API}/account/notifications/unread", headers=pm.headers)).json() == {
        "unread": 2
    }
    r = await client.post(
        f"{API}/account/notifications/read", json={"ids": [inbox[0]["id"]]}, headers=pm.headers
    )
    assert r.json() == {"unread": 1}
    r = await client.post(
        f"{API}/account/notifications/read", json={"all": True}, headers=pm.headers
    )
    assert r.json() == {"unread": 0}

    # one person never sees another's messages
    other = await make_user(client, Role.PROJECT_MANAGER)
    assert (await client.get(f"{API}/account/notifications", headers=other.headers)).json() == []
    r = await client.post(
        f"{API}/account/notifications/read", json={"ids": [inbox[1]["id"]]}, headers=other.headers
    )
    assert r.json() == {"unread": 0}


async def test_channels_are_chosen_per_kind_of_message(client: Any) -> None:
    pm = await make_user(client, Role.PROJECT_MANAGER)
    prefs = (await client.get(f"{API}/account/notification-preferences", headers=pm.headers)).json()
    update = next(p for p in prefs if p["template"] == "task_update")
    assert update["channels"] == {"email": True, "in_app": True, "push": True}
    assert update["label"] == "A field task changes state"
    r = await client.put(
        f"{API}/account/notification-preferences/task_update",
        json={"enabled": False, "channel": "in_app"},
        headers=pm.headers,
    )
    assert r.status_code == 204
    r = await client.put(
        f"{API}/account/notification-preferences/task_update",
        json={"enabled": False, "channel": "fax"},
        headers=pm.headers,
    )
    assert r.status_code == 422
    n = await _queue(pm)
    assert n.status in ("pending", "sent", "skipped")  # email still on
    assert (await client.get(f"{API}/account/notifications", headers=pm.headers)).json() == []
    prefs = (await client.get(f"{API}/account/notification-preferences", headers=pm.headers)).json()
    update = next(p for p in prefs if p["template"] == "task_update")
    assert update["channels"]["in_app"] is False and update["enabled"] is True

    # security messages arrive whatever the person chose
    r = await client.put(
        f"{API}/account/notification-preferences/run_returned",
        json={"enabled": False, "channel": "push"},
        headers=pm.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "not_optional"


async def test_push_reaches_subscribed_devices_and_forgets_gone_ones(
    client: Any, push_on: FakePush, monkeypatch: pytest.MonkeyPatch
) -> None:
    eng = await make_user(client, Role.FIELD_ENGINEER)
    status = (await client.get(f"{API}/account/push", headers=eng.headers)).json()
    assert status == {"enabled": True, "public_key": "BPublicKeyForTests", "devices": 0}

    # only real browser push services are accepted
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example/push", "https://10.0.0.5/x"):
        r = await client.post(
            f"{API}/account/push/subscriptions",
            json={"endpoint": bad, "keys": KEYS},
            headers=eng.headers,
        )
        assert r.status_code == 422 and r.json()["code"] == "push_endpoint_refused", bad
    r = await client.post(
        f"{API}/account/push/subscriptions",
        json={"endpoint": ENDPOINT, "keys": KEYS, "user_agent": "Pixel 7"},
        headers=eng.headers,
    )
    assert r.status_code == 201, r.text
    # subscribing again from the same device updates it, never duplicates it
    await client.post(
        f"{API}/account/push/subscriptions",
        json={"endpoint": ENDPOINT, "keys": KEYS},
        headers=eng.headers,
    )
    assert (await client.get(f"{API}/account/push", headers=eng.headers)).json()["devices"] == 1

    await _queue(eng)
    assert len(push_on.sent) == 1
    sub, payload = push_on.sent[0]
    assert sub["endpoint"] == ENDPOINT and sub["keys"]["auth"] == KEYS["auth"]
    assert payload["title"].startswith("Shakti") and payload["url"].startswith("/field/")
    assert not payload["body"].lower().startswith("hello")
    assert "₹" not in str(payload) and "price" not in str(payload).lower()

    # the test message reaches the device too
    r = await client.post(f"{API}/account/push/test", headers=eng.headers)
    assert r.status_code == 202 and len(push_on.sent) == 2
    assert push_on.sent[1][1]["title"] == "Test message from Project One"

    # the browser says the subscription is gone: it is forgotten
    monkeypatch.setattr(providers, "PUSH", FakePush(gone=True))
    await _queue(eng)
    async with get_sessionmaker()() as s:
        assert (await s.scalar(select(PushSubscription))) is None
        last = await s.scalar(
            select(Notification)
            .where(Notification.channel == "push")
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
    assert last is not None and last.status == "skipped"

    # removing a device on sign-out
    await client.post(
        f"{API}/account/push/subscriptions",
        json={"endpoint": ENDPOINT, "keys": KEYS},
        headers=eng.headers,
    )
    r = await client.post(
        f"{API}/account/push/subscriptions/remove", json={"endpoint": ENDPOINT}, headers=eng.headers
    )
    assert r.status_code == 204
    assert (await client.get(f"{API}/account/push", headers=eng.headers)).json()["devices"] == 0


async def test_push_off_without_keys_and_codes_never_pushed(client: Any, push_on: FakePush) -> None:
    eng = await make_user(client, Role.FIELD_ENGINEER)
    await client.post(
        f"{API}/account/push/subscriptions",
        json={"endpoint": ENDPOINT, "keys": KEYS},
        headers=eng.headers,
    )
    # a one-time code is email only: never in the centre, never on a lock screen
    maker = get_sessionmaker()
    async with maker() as s:
        n = await service.queue_for_user(
            s,
            user_id=eng.id,
            email=eng.email,
            template="otp_check_in",
            context={
                "name": "A",
                "engineer": "B",
                "place": "C",
                "task": "D",
                "code": "123456",
                "minutes": 15,
                "project": "P",
            },
        )
        await s.commit()
        copies = list(await s.scalars(select(Notification).where(Notification.parent_id == n.id)))
    assert copies == [] and push_on.sent == []


async def test_subscribing_needs_push_set_up(client: Any) -> None:
    eng = await make_user(client, Role.FIELD_ENGINEER)
    assert (await client.get(f"{API}/account/push", headers=eng.headers)).json()["enabled"] is False
    r = await client.post(
        f"{API}/account/push/subscriptions",
        json={"endpoint": ENDPOINT, "keys": KEYS},
        headers=eng.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "push_off"


def test_the_push_payload_is_one_line_and_a_link() -> None:
    n = Notification(
        subject="Shakti: T01 is now closed",
        body="Hello Aditya,\n\nT01 on Shakti moved to: closed.\n\nBy B at x (IST).\n",
        template="task_update",
        link="/field/abc",
    )
    assert service.push_payload(n) == {
        "title": "Shakti: T01 is now closed",
        "body": "T01 on Shakti moved to: closed.",
        "url": "/field/abc",
        "tag": "task_update",
    }
