"""Public surface of the reporting module. Other modules import only from here."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reporting.models import Certificate


async def valid_certificate_number(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The number of the project's valid certificate, if one is issued."""
    return await session.scalar(
        select(Certificate.number).where(
            Certificate.project_id == project_id, Certificate.status == "valid"
        )
    )


__all__ = ["valid_certificate_number"]
