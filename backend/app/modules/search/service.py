"""Global search: Postgres full-text search with trigram matching, filtered by role.

Every result passes the same checks as the module that owns it: the permission on the document,
then the owner's object-level check (project membership, customer access, a field engineer's
own tasks). Nothing here holds or returns a price."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import delete, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound
from app.core.timeutil import utcnow
from app.modules.customers.contracts import get_customer_ref, get_project_ref
from app.modules.identity.contracts import P, Principal
from app.modules.search.contracts import KINDS, SearchDoc
from app.modules.search.models import SearchDocument

MAX_RESULTS = 30
_TOKEN = re.compile(r"[0-9a-z]+")


def _tsquery(q: str) -> str | None:
    """Every word as a prefix, all required: 'shakti fire' finds 'Shakti Equipments, Firewall'."""
    tokens = _TOKEN.findall(q.lower())[:8]
    return " & ".join(f"{t}:*" for t in tokens) if tokens else None


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def upsert(session: AsyncSession, payload: dict[str, Any]) -> None:
    def as_uuid(v: Any) -> uuid.UUID | None:
        return uuid.UUID(str(v)) if v else None

    row = {
        "kind": payload["kind"],
        "ref_id": str(payload["ref_id"]),
        "title": str(payload["title"])[:300],
        "subtitle": payload.get("subtitle"),
        "body": payload.get("body"),
        "url": str(payload["url"])[:300],
        "perm": str(payload["perm"]),
        "project_id": as_uuid(payload.get("project_id")),
        "customer_id": as_uuid(payload.get("customer_id")),
        "assignee_id": as_uuid(payload.get("assignee_id")),
        "updated_at": utcnow(),
    }
    stmt = insert(SearchDocument).values(**row)
    stmt = stmt.on_conflict_do_update(
        index_elements=["kind", "ref_id"],
        set_={k: v for k, v in row.items() if k not in ("kind", "ref_id")},
    )
    await session.execute(stmt)


async def remove(session: AsyncSession, kind: str, ref_id: str) -> None:
    await session.execute(
        delete(SearchDocument).where(SearchDocument.kind == kind, SearchDocument.ref_id == ref_id)
    )


async def _visible(session: AsyncSession, principal: Principal, d: SearchDocument) -> bool:
    """The owner's object-level rule for one document."""
    try:
        if d.project_id is not None:
            await get_project_ref(session, principal, d.project_id)
        elif d.kind == "customer" and d.customer_id is not None:
            await get_customer_ref(session, principal, d.customer_id)
    except (NotFound, Forbidden):
        return False
    if d.kind == "task" and not (principal.has(P.FIELD_MANAGE) or principal.has(P.FIELD_VERIFY)):
        return d.assignee_id == principal.user_id
    return True


async def search(
    session: AsyncSession,
    principal: Principal,
    q: str,
    *,
    kinds: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    q = q.strip()[:100]
    limit = max(1, min(limit, MAX_RESULTS))
    tsq = _tsquery(q)
    if len(q) < 2 or tsq is None:
        return []
    perms = [p.value for p in principal.permissions]
    query = func.to_tsquery("simple", tsq)
    score = (
        func.ts_rank(SearchDocument.tsv, query) + func.similarity(SearchDocument.title, q)
    ).label("score")
    stmt = (
        select(SearchDocument, score)
        .where(
            SearchDocument.perm.in_(perms),
            or_(
                SearchDocument.tsv.op("@@")(query),
                SearchDocument.title.op("%")(q),
                SearchDocument.title.ilike(_like(q), escape="\\"),
            ),
        )
        .order_by(literal_column("score").desc(), SearchDocument.title)
        .limit(limit * 4)
    )
    if kinds:
        stmt = stmt.where(SearchDocument.kind.in_([k for k in kinds if k in KINDS]))
    out: list[dict[str, Any]] = []
    for d, s in (await session.execute(stmt)).all():
        if not await _visible(session, principal, d):
            continue
        out.append(
            {
                "kind": d.kind,
                "title": d.title,
                "subtitle": d.subtitle,
                "url": d.url,
                "score": round(float(s), 4),
            }
        )
        if len(out) >= limit:
            break
    return out


async def reindex(session: AsyncSession) -> dict[str, int]:
    """Rebuild the whole index from the owning modules. Run nightly, after a restore, and by
    `python -m app.cli search-reindex`."""
    from app.modules.boq.contracts import search_documents as quote_docs
    from app.modules.catalogue.contracts import search_documents as item_docs
    from app.modules.customers.contracts import search_documents as customer_docs
    from app.modules.fieldops.contracts import search_documents as task_docs

    docs: list[SearchDoc] = []
    for source in (customer_docs, item_docs, quote_docs, task_docs):
        docs.extend(await source(session))
    await session.execute(delete(SearchDocument))
    for doc in docs:
        await upsert(session, doc.payload())
    await session.commit()
    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc.kind] = counts.get(doc.kind, 0) + 1
    return counts
