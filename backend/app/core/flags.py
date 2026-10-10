"""DB-backed feature flags, cached in-process for 30 seconds."""

from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Known flags and their default when no row exists. Add new flags here.
DEFAULTS: dict[str, bool] = {
    "customer_portal_login": False,  # customer reps sign in with a password (v1: links + OTP only)
    "prismsuite_json_import": True,  # accept AuditSnapshot JSON uploads
    # The customer's one-time code at check-in and hand over. Built and tested, switched off
    # for now: the arrival photo, evidence and checks still apply (ADR 0025).
    "field_customer_codes": False,
    # The learning module: examples, shadow models, suggestions and price alerts. Off stops all
    # of it at once and changes nothing in any other module (ADR 0029).
    "ml_enabled": True,
}

_CACHE_TTL = 30.0
_cache: dict[str, tuple[float, bool]] = {}


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


async def is_enabled(session: AsyncSession, key: str) -> bool:
    if key not in DEFAULTS:
        raise KeyError(f"unknown feature flag {key}")
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    row = await session.scalar(select(FeatureFlag.enabled).where(FeatureFlag.key == key))
    value = DEFAULTS[key] if row is None else bool(row)
    _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    _cache.clear()
