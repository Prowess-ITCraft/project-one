"""Public surface of the search module. Other modules import only from here.

A module that owns something people search for calls `index` (or `unindex`) in the same
transaction as the change. That writes an outbox event; the search module's subscriber updates
the index. A failing index update never rolls back the change, and the nightly rebuild repairs
anything missed. Documents never carry prices.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.events import DomainEvent

SEARCH_UPSERT = "search.upsert"
SEARCH_UPSERT_MANY = "search.upsert_many"
SEARCH_REMOVE = "search.remove"
KINDS = ("customer", "project", "quote", "task", "item")


@dataclass(frozen=True)
class SearchDoc:
    kind: str  # one of KINDS
    ref_id: str
    title: str
    url: str
    perm: str  # the permission code needed to see it, for example "boq:read"
    subtitle: str | None = None
    body: str | None = None
    project_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None

    def payload(self) -> dict[str, str | None]:
        out = asdict(self)
        for k in ("project_id", "customer_id", "assignee_id"):
            out[k] = str(out[k]) if out[k] else None
        out["title"] = self.title[:300]
        out["subtitle"] = (self.subtitle or "")[:300] or None
        out["body"] = (self.body or "")[:4000] or None
        return out


def index(session: AsyncSession, doc: SearchDoc, actor_id: uuid.UUID | None = None) -> None:
    if doc.kind not in KINDS:
        raise ValueError(f"unknown search kind {doc.kind}")
    outbox.publish(
        session,
        DomainEvent(
            event_type=SEARCH_UPSERT,
            aggregate_type="search",
            aggregate_id=f"{doc.kind}:{doc.ref_id}",
            actor_id=actor_id,
            payload=doc.payload(),
        ),
    )


def index_many(
    session: AsyncSession, docs: list[SearchDoc], actor_id: uuid.UUID | None = None
) -> None:
    """Many documents in one event, for a change that creates many at once (field work start),
    so the outbox carries one message instead of one per document."""
    if not docs:
        return
    for d in docs:
        if d.kind not in KINDS:
            raise ValueError(f"unknown search kind {d.kind}")
    outbox.publish(
        session,
        DomainEvent(
            event_type=SEARCH_UPSERT_MANY,
            aggregate_type="search",
            aggregate_id=f"{docs[0].kind}:many:{len(docs)}",
            actor_id=actor_id,
            payload={"docs": [d.payload() for d in docs]},
        ),
    )


def unindex(
    session: AsyncSession, kind: str, ref_id: str, actor_id: uuid.UUID | None = None
) -> None:
    outbox.publish(
        session,
        DomainEvent(
            event_type=SEARCH_REMOVE,
            aggregate_type="search",
            aggregate_id=f"{kind}:{ref_id}",
            actor_id=actor_id,
            payload={"kind": kind, "ref_id": ref_id},
        ),
    )


__all__ = [
    "KINDS",
    "SEARCH_REMOVE",
    "SEARCH_UPSERT",
    "SEARCH_UPSERT_MANY",
    "SearchDoc",
    "index",
    "index_many",
    "unindex",
]
