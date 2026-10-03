"""Offset pagination with a hard page-size cap of 200."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_PAGE_SIZE = 200


class PageParams(BaseModel):
    model_config = ConfigDict(frozen=True)
    page: int = 1
    size: int = 50

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def page_params(
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> PageParams:
    return PageParams(page=page, size=size)


class Page[T](BaseModel):
    items: list[T]
    page: int
    size: int
    total: int


async def paginate_rows[R](
    session: AsyncSession, stmt: Select[R], params: PageParams
) -> tuple[list[R], int]:
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await session.scalars(stmt.limit(params.size).offset(params.offset))).all()
    return list(rows), int(total or 0)
