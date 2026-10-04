"""Public surface of the boq module. Other modules import only from here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq import draft as _d
from app.modules.boq.models import Boq, BoqVersion
from app.modules.boq.service import ARTIFACT, BOQ_ACCEPTED, BOQ_RECOMMENDED, VERSION_ISSUED
from app.modules.customers.contracts import get_project_ref
from app.modules.identity.contracts import P, Principal


@dataclass(frozen=True)
class AcceptedLine:
    ref: str
    title: str
    qty: int
    uom: str
    item_code: str | None
    option_group: str | None
    source_gaps: tuple[str, ...]
    role_hint: str | None  # template line key, used by planning to pick a task template


@dataclass(frozen=True)
class AcceptedBoq:
    boq_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    quote_ref: str
    po_number: str
    lines: tuple[AcceptedLine, ...]
    total_with_gst: Decimal | None


async def get_accepted_boq(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> AcceptedBoq:
    """The locked, customer-accepted BOQ version that planning works from. Lines carry no
    prices: planning and field work never see them (ADR 0003). Needs `boq:read` or `plan:read`."""
    if not principal.has(P.PLAN_READ):
        principal.require(P.BOQ_READ)
    await get_project_ref(session, principal, project_id)
    v = await session.scalar(
        select(BoqVersion).where(
            BoqVersion.project_id == project_id, BoqVersion.state == "accepted"
        )
    )
    if v is None:
        from app.core.errors import NotFound

        raise NotFound("No accepted BOQ for this project yet.")
    draft = _d.Draft.model_validate(v.content)
    chosen = draft.selected_options
    lines: list[AcceptedLine] = []
    for n in _d.numbered(draft):
        ln = n.line
        if ln.option_group and chosen.get(ln.option_group) != n.letter:
            continue  # the customer did not choose this alternative
        lines.append(
            AcceptedLine(
                n.ref,
                ln.title,
                ln.qty,
                ln.uom,
                ln.item_code,
                ln.option_group,
                tuple(ln.source.gap_codes),
                ln.source.template_key,
            )
        )
    total: Any = v.totals.get("total_max")
    return AcceptedBoq(
        v.boq_id,
        v.id,
        v.number,
        v.quote_ref,
        v.po_number or "",
        tuple(lines),
        Decimal(total) if total else None,
    )


async def boq_exists(session: AsyncSession, project_id: uuid.UUID) -> bool:
    return await session.scalar(select(Boq.id).where(Boq.project_id == project_id)) is not None


async def get_company_profile(session: AsyncSession) -> dict[str, Any]:
    """Letterhead facts for any document: name, logo, wordmark colours, address, GSTIN, tagline.
    No prices."""
    from app.modules.boq import service as _svc

    return await _svc.company(session)


__all__ = [
    "ARTIFACT",
    "BOQ_ACCEPTED",
    "BOQ_RECOMMENDED",
    "VERSION_ISSUED",
    "AcceptedBoq",
    "AcceptedLine",
    "boq_exists",
    "get_accepted_boq",
    "get_company_profile",
]
