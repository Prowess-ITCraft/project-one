from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.modules.identity.contracts import P, Principal, require
from app.modules.infra import service
from app.modules.infra.facts import FACT_CATALOGUE
from app.modules.infra.schemas import (
    DecisionIn,
    GapOut,
    GapUpdateIn,
    ManualGapIn,
    RegisterDetailOut,
    RegisterOut,
    RuleChangeIn,
    RuleChangeOut,
    RuleOut,
    StateOut,
)

rules_router = APIRouter(prefix="/infra/rules", tags=["infra"])
project_router = APIRouter(prefix="/projects/{project_id}", tags=["infra"])
Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]
Reader = Annotated[Principal, Depends(require(P.INFRA_READ))]
Writer = Annotated[Principal, Depends(require(P.INFRA_WRITE))]
Editor = Annotated[Principal, Depends(require(P.RULE_EDIT))]
Approver = Annotated[Principal, Depends(require(P.RULE_APPROVE))]


def _gap(g: Any) -> GapOut:
    out = GapOut.model_validate(g, from_attributes=True)
    out.code = f"GAP-{g.number:03d}"
    return out


async def _detail(reg: Any, gaps: list[Any]) -> RegisterDetailOut:
    counts: dict[str, int] = {}
    for g in gaps:
        counts[g.status] = counts.get(g.status, 0) + 1
    return RegisterDetailOut(
        **RegisterOut.model_validate(reg, from_attributes=True).model_dump(),
        gaps=[_gap(g) for g in gaps],
        counts=counts,
    )


# ------------------------------------------------------------------ rule library


@rules_router.get("", response_model=list[RuleOut])
async def list_rules(
    session: Session, _: Reader, component: str | None = None, active: bool | None = None
) -> list[RuleOut]:
    return [
        RuleOut.model_validate(r, from_attributes=True)
        for r in await service.list_rules(session, component=component, active=active)
    ]


@rules_router.get("/facts", response_model=dict[str, str])
async def facts(_: Reader) -> dict[str, str]:
    """The facts a rule condition may test, with plain descriptions."""
    return FACT_CATALOGUE


@rules_router.post("/changes", response_model=RuleChangeOut, status_code=status.HTTP_201_CREATED)
async def propose_change(session: Session, principal: Editor, body: RuleChangeIn) -> RuleChangeOut:
    """Admin proposes a rule change. The Director approves it before it takes effect."""
    ch = await service.propose_change(
        session,
        principal,
        rule_id=body.rule_id,
        kind=body.kind,
        proposed=body.proposed.model_dump(exclude_none=True),
        reason=body.reason,
    )
    return RuleChangeOut.model_validate(ch, from_attributes=True)


@rules_router.get("/changes", response_model=list[RuleChangeOut])
async def list_changes(
    session: Session,
    _: Reader,
    status_: Annotated[
        str, Query(alias="status", pattern="^(pending|approved|rejected)$")
    ] = "pending",
) -> list[RuleChangeOut]:
    return [
        RuleChangeOut.model_validate(c, from_attributes=True)
        for c in await service.list_changes(session, status_)
    ]


@rules_router.post("/changes/{change_id}/decision", response_model=RuleChangeOut)
async def decide_change(
    session: Session, principal: Approver, change_id: uuid.UUID, body: DecisionIn
) -> RuleChangeOut:
    ch = await service.decide_change(
        session, principal, change_id, approve=body.approve, note=body.note
    )
    return RuleChangeOut.model_validate(ch, from_attributes=True)


@rules_router.get("/{rule_id}", response_model=RuleOut)
async def get_rule(session: Session, _: Reader, rule_id: uuid.UUID) -> RuleOut:
    return RuleOut.model_validate(await service.get_rule(session, rule_id), from_attributes=True)


# ------------------------------------------------------------------ project states and gaps


@project_router.get("/infra", response_model=list[StateOut])
async def list_states(session: Session, principal: Reader, project_id: uuid.UUID) -> list[StateOut]:
    return [
        StateOut.model_validate(s, from_attributes=True)
        for s in await service.list_states(session, principal, project_id)
    ]


@project_router.post("/infra/current", response_model=StateOut, status_code=status.HTTP_201_CREATED)
async def build_current(session: Session, principal: Writer, project_id: uuid.UUID) -> StateOut:
    """Build the current IT infrastructure baseline from the approved audit."""
    return StateOut.model_validate(
        await service.build_current(session, principal, project_id), from_attributes=True
    )


@project_router.post("/infra/ideal", response_model=StateOut, status_code=status.HTTP_201_CREATED)
async def build_ideal(session: Session, principal: Writer, project_id: uuid.UUID) -> StateOut:
    """Build the target state from the rule library, for the tier in the intake questionnaire."""
    return StateOut.model_validate(
        await service.build_ideal(session, principal, project_id), from_attributes=True
    )


@project_router.post("/infra/{state_id}/lock", response_model=StateOut)
async def lock_state(
    session: Session, principal: Writer, project_id: uuid.UUID, state_id: uuid.UUID, guard: Idem
) -> Any:
    async def work() -> StateOut:
        return StateOut.model_validate(
            await service.lock_state(session, principal, project_id, state_id), from_attributes=True
        )

    return await run_idempotent(guard, str(principal.user_id), 200, work)


@project_router.post("/gaps", response_model=RegisterDetailOut, status_code=status.HTTP_201_CREATED)
async def generate_gaps(
    session: Session, principal: Writer, project_id: uuid.UUID
) -> RegisterDetailOut:
    """Evaluate the rules against the audit and draft the gap register."""
    reg = await service.generate_register(session, principal, project_id)
    r, gaps = await service.get_register(session, principal, project_id, reg.id)
    return await _detail(r, gaps)


@project_router.get("/gaps", response_model=RegisterDetailOut)
async def get_gaps(
    session: Session, principal: Reader, project_id: uuid.UUID, register_id: uuid.UUID | None = None
) -> RegisterDetailOut:
    reg, gaps = await service.get_register(session, principal, project_id, register_id)
    return await _detail(reg, gaps)


@project_router.post(
    "/gaps/{register_id}/items", response_model=GapOut, status_code=status.HTTP_201_CREATED
)
async def add_gap(
    session: Session,
    principal: Writer,
    project_id: uuid.UUID,
    register_id: uuid.UUID,
    body: ManualGapIn,
) -> GapOut:
    """Add a gap by hand. The reason is recorded."""
    data = body.model_dump(exclude={"reason"})
    g = await service.add_manual_gap(
        session,
        principal,
        project_id,
        register_id,
        data={**data, "evidence": {}},
        reason=body.reason,
    )
    return _gap(g)


@project_router.patch("/gaps/{register_id}/items/{gap_id}", response_model=GapOut)
async def update_gap(
    session: Session,
    principal: Writer,
    project_id: uuid.UUID,
    register_id: uuid.UUID,
    gap_id: uuid.UUID,
    body: GapUpdateIn,
) -> GapOut:
    """Change priority, text, affected assets or status. Every change needs a reason."""
    changes = body.model_dump(exclude_unset=True, exclude={"version", "reason"})
    g = await service.update_gap(
        session,
        principal,
        project_id,
        register_id,
        gap_id,
        version=body.version,
        reason=body.reason,
        changes=changes,
    )
    return _gap(g)


@project_router.post("/gaps/{register_id}/lock", response_model=RegisterOut)
async def lock_gaps(
    session: Session, principal: Writer, project_id: uuid.UUID, register_id: uuid.UUID, guard: Idem
) -> Any:
    async def work() -> RegisterOut:
        return RegisterOut.model_validate(
            await service.lock_register(session, principal, project_id, register_id),
            from_attributes=True,
        )

    return await run_idempotent(guard, str(principal.user_id), 200, work)


routers = [rules_router, project_router]
