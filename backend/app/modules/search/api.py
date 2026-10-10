from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.identity.contracts import CurrentPrincipal
from app.modules.search import service

router = APIRouter(prefix="/search", tags=["search"])
Session = Annotated[AsyncSession, Depends(get_session)]
Kind = Literal["customer", "project", "quote", "task", "item"]


class SearchHitOut(BaseModel):
    kind: str
    title: str
    subtitle: str | None
    url: str
    score: float


@router.get("", response_model=list[SearchHitOut])
async def search(
    session: Session,
    principal: CurrentPrincipal,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    kind: Annotated[list[Kind] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 20,
) -> list[SearchHitOut]:
    """Customers, projects, quotes, field tasks and catalogue items whose name, code or
    reference matches. You see only what you could open anyway; prices are never searched or
    shown."""
    return [
        SearchHitOut(**h)
        for h in await service.search(session, principal, q, kinds=list(kind or []), limit=limit)
    ]


routers = [router]
