"""Domain events and the subscriber registry.

Modules publish events with `outbox.publish(session, event)` inside their own transaction.
Other modules subscribe with `@subscribe("module.event_name", name="module.handler")`.
Handlers run later in the worker, one outbox row per subscriber, and must be idempotent.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    aggregate_type: str
    aggregate_id: str
    occurred_at: datetime = Field(default_factory=utcnow)
    actor_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


Handler = Callable[[AsyncSession, DomainEvent], Awaitable[None]]


@dataclass(frozen=True)
class Subscription:
    name: str
    event_type: str
    handler: Handler


_subscriptions: dict[str, list[Subscription]] = {}
_by_name: dict[str, Subscription] = {}
_handlers_loaded = False


def mark_handlers_loaded() -> None:
    """Called by the module registry once every subscriber is imported in this process."""
    global _handlers_loaded
    _handlers_loaded = True


def handlers_loaded() -> bool:
    return _handlers_loaded


def subscribe(event_type: str, *, name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if name in _by_name and _by_name[name].handler is not fn:
            raise RuntimeError(f"duplicate subscriber name {name}")
        sub = Subscription(name=name, event_type=event_type, handler=fn)
        _by_name[name] = sub
        subs = _subscriptions.setdefault(event_type, [])
        if all(s.name != name for s in subs):
            subs.append(sub)
        return fn

    return register


def subscribers_for(event_type: str) -> list[Subscription]:
    return list(_subscriptions.get(event_type, ())) + list(_subscriptions.get("*", ()))


def subscriber(name: str) -> Subscription | None:
    return _by_name.get(name)
