"""Gap-free, collision-safe counters (project codes, quote refs) using an atomic upsert."""

from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NumberSequence(Base):
    __tablename__ = "number_sequences"

    scope: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)


async def next_value(session: AsyncSession, scope: str) -> int:
    """Next number for `scope`, in the caller's transaction.

    The row lock taken by the upsert is held until commit, so concurrent callers queue and
    each gets a distinct value. If the caller rolls back, the number is reused (no gaps).
    """
    stmt = (
        insert(NumberSequence)
        .values(scope=scope, value=1)
        .on_conflict_do_update(
            index_elements=[NumberSequence.scope], set_={"value": NumberSequence.value + 1}
        )
        .returning(NumberSequence.value)
    )
    return int((await session.execute(stmt)).scalar_one())
