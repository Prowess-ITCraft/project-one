"""Learning from accepted BOQs (phase 13, ADR 0020).

1. While a BOQ is drafted, every ranked candidate is kept as an example (`boq.recommended`).
2. When the customer accepts a version, each example is labelled kept or not (`boq.accepted`).
3. A person freezes the labelled examples into a numbered training set with a data card.
4. A model is trained from one frozen set only, and can run in shadow mode: it ranks the same
   candidates next to the rules and the agreement is recorded, but nothing it says reaches a BOQ.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.events import DomainEvent
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import record
from app.modules.identity.contracts import P, Principal, audit_context
from app.modules.ml import train as t
from app.modules.ml.models import MlExample, MlModel, MlShadowRun, MlTrainingSet

# ------------------------------------------------------------------ events


async def record_recommendations(session: AsyncSession, event: DomainEvent) -> None:
    """Keep every ranked candidate. A BOQ drafted again replaces its unlabelled examples, since
    the earlier ranking is no longer what anyone saw. Idempotent."""
    boq_id = uuid.UUID(event.aggregate_id)
    project_id = uuid.UUID(event.payload["project_id"])
    await session.execute(
        delete(MlExample).where(MlExample.boq_id == boq_id, MlExample.kept.is_(None))
    )
    shadow = await active_shadow(session)
    for g in event.payload.get("groups", []):
        cands = g.get("candidates") or []
        for rank, c in enumerate(cands, start=1):
            exists = await session.scalar(
                select(MlExample.id).where(
                    MlExample.boq_id == boq_id,
                    MlExample.rec_key == g["key"],
                    MlExample.item_id == uuid.UUID(c["item_id"]),
                )
            )
            if exists:
                continue
            session.add(
                MlExample(
                    boq_id=boq_id,
                    project_id=project_id,
                    rec_key=g["key"][:120],
                    category=g["category"][:60],
                    item_id=uuid.UUID(c["item_id"]),
                    item_name=c["name"][:300],
                    rule_rank=rank,
                    rule_score=float(c["score"]),
                    criteria=c["criteria"],
                )
            )
        if shadow is not None and len(cands) > 1:
            await _shadow(session, shadow, boq_id, g)
    await session.commit()


async def _shadow(
    session: AsyncSession, model: MlModel, boq_id: uuid.UUID, group: dict[str, Any]
) -> None:
    cands = group["candidates"]
    rule_top = cands[0]["name"]
    model_top = max(cands, key=lambda c: t.score(model.weights, c["criteria"]))["name"]
    run = await session.scalar(
        select(MlShadowRun).where(
            MlShadowRun.model_id == model.id,
            MlShadowRun.boq_id == boq_id,
            MlShadowRun.rec_key == group["key"],
        )
    )
    if run is None:
        run = MlShadowRun(model_id=model.id, boq_id=boq_id, rec_key=group["key"][:120])
        session.add(run)
    run.category, run.rule_top, run.model_top = group["category"][:60], rule_top, model_top
    run.agree = rule_top == model_top


async def label_accepted(session: AsyncSession, event: DomainEvent) -> None:
    """The customer accepted a version: a candidate was kept if its item is in that version.
    A later acceptance (after a reopen) relabels, so the newest decision counts."""
    boq_id = uuid.UUID(event.aggregate_id)
    kept = set(event.payload.get("item_ids") or [])
    now = utcnow()
    for ex in await session.scalars(select(MlExample).where(MlExample.boq_id == boq_id)):
        ex.kept, ex.labelled_at = str(ex.item_id) in kept, now
    await session.commit()


# ------------------------------------------------------------------ training sets


def _row(ex: MlExample) -> dict[str, Any]:
    return {
        "group": f"{ex.boq_id}:{ex.rec_key}",
        "category": ex.category,
        "item_id": str(ex.item_id),
        "item": ex.item_name,
        "criteria": ex.criteria,
        "rule_score": ex.rule_score,
        "rule_rank": ex.rule_rank,
        "kept": bool(ex.kept),
        "labelled_at": ex.labelled_at.isoformat() if ex.labelled_at else None,
    }


def _examples(rows: list[dict[str, Any]]) -> list[t.Example]:
    return [
        t.Example(r["group"], r["item_id"], r["criteria"], float(r["rule_score"]), bool(r["kept"]))
        for r in rows
    ]


async def freeze_training_set(session: AsyncSession, principal: Principal) -> MlTrainingSet:
    principal.require(P.ML_MANAGE)
    labelled = list(
        await session.scalars(
            select(MlExample)
            .where(MlExample.kept.is_not(None))
            .order_by(MlExample.boq_id, MlExample.rec_key, MlExample.rule_rank)
        )
    )
    if not labelled:
        raise ValidationFailed(
            "There are no labelled examples yet. They appear when a customer accepts a BOQ "
            "that the recommender helped draft.",
            code="no_examples",
        )
    rows = [_row(x) for x in labelled]
    groups = t.usable_groups(_examples(rows))
    dates = sorted(r["labelled_at"] for r in rows if r["labelled_at"])
    card = {
        "rows": len(rows),
        "kept": sum(1 for r in rows if r["kept"]),
        "boqs": len({r["group"].split(":", 1)[0] for r in rows}),
        "groups": len({r["group"] for r in rows}),
        "usable_groups": len(groups),
        "categories": dict(Counter(r["category"] for r in rows).most_common()),
        "features": list(t.FEATURES),
        "labelled_from": dates[0] if dates else None,
        "labelled_to": dates[-1] if dates else None,
        "source": "ml_examples: candidates ranked while drafting, labelled at acceptance",
        "personal_data": "none (item names, criteria and scores only; no customers or prices)",
    }
    number = (await session.scalar(select(func.max(MlTrainingSet.number))) or 0) + 1
    ts = MlTrainingSet(number=number, rows=rows, data_card=card, frozen_by=principal.user_id)
    session.add(ts)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="freeze_training_set",
        entity_type="ml_training_set",
        entity_id=ts.id,
        after={"number": number, **{k: card[k] for k in ("rows", "usable_groups")}},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(ts)
    return ts


async def list_training_sets(session: AsyncSession, principal: Principal) -> list[MlTrainingSet]:
    principal.require(P.ML_READ)
    return list(await session.scalars(select(MlTrainingSet).order_by(MlTrainingSet.number.desc())))


# ------------------------------------------------------------------ models


async def train_model(
    session: AsyncSession, principal: Principal, training_set_id: uuid.UUID
) -> MlModel:
    principal.require(P.ML_MANAGE)
    ts = await session.get(MlTrainingSet, training_set_id)
    if ts is None:
        raise NotFound("That training set does not exist.")
    try:
        result = t.train(_examples(ts.rows))
    except t.NotEnoughData as exc:
        raise ValidationFailed(str(exc), code="not_enough_data") from exc
    number = (await session.scalar(select(func.max(MlModel.number))) or 0) + 1
    m = MlModel(
        number=number,
        training_set_id=ts.id,
        weights=result.weights,
        metrics={**result.metrics, "training_set": ts.number},
        trained_by=principal.user_id,
    )
    session.add(m)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="train_model",
        entity_type="ml_model",
        entity_id=m.id,
        after={"number": number, "training_set": ts.number, "weights": result.weights},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(m)
    return m


async def list_models(session: AsyncSession, principal: Principal) -> list[MlModel]:
    principal.require(P.ML_READ)
    return list(await session.scalars(select(MlModel).order_by(MlModel.number.desc())))


async def active_shadow(session: AsyncSession) -> MlModel | None:
    return await session.scalar(select(MlModel).where(MlModel.status == "shadow"))


async def set_status(
    session: AsyncSession, principal: Principal, model_id: uuid.UUID, status: str
) -> MlModel:
    """Start shadow mode for one model (the previous one goes back to trained), or retire one."""
    principal.require(P.ML_MANAGE)
    m = await session.get(MlModel, model_id, with_for_update=True)
    if m is None:
        raise NotFound("That model does not exist.")
    if m.status == "retired":
        raise Conflict("A retired model stays retired. Train a new one.", code="retired")
    before = m.status
    if status == "shadow":
        current = await active_shadow(session)
        if current is not None and current.id != m.id:
            current.status = "trained"
            await session.flush()
    m.status = status
    await record(
        session,
        audit_context(principal),
        action=f"model_{status}",
        entity_type="ml_model",
        entity_id=m.id,
        before={"status": before},
        after={"status": status},
    )
    await session.commit()
    await session.refresh(m)
    return m


# ------------------------------------------------------------------ report


async def report(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    """Where the learning stands: how much data there is, and how the shadow model compares
    with the rules on decisions customers have already made."""
    principal.require(P.ML_READ)
    total = await session.scalar(select(func.count()).select_from(MlExample)) or 0
    labelled = list(await session.scalars(select(MlExample).where(MlExample.kept.is_not(None))))
    groups = t.usable_groups(_examples([_row(x) for x in labelled]))
    shadow = await active_shadow(session)
    out: dict[str, Any] = {
        "examples": total,
        "labelled": len(labelled),
        "usable_groups": len(groups),
        "needed_groups": t.MIN_GROUPS,
        "rules_top1": t.top1(groups, key=lambda x: x.rule_score),
        "shadow": None,
    }
    if shadow is not None:
        runs = list(
            await session.scalars(
                select(MlShadowRun)
                .where(MlShadowRun.model_id == shadow.id)
                .order_by(MlShadowRun.updated_at.desc())
            )
        )
        out["shadow"] = {
            "model_id": str(shadow.id),
            "number": shadow.number,
            "weights": shadow.weights,
            "runs": len(runs),
            "agreement": round(sum(r.agree for r in runs) / len(runs), 3) if runs else None,
            "model_top1": t.top1(groups, key=lambda x: t.score(shadow.weights, x.criteria)),
            "disagreements": [
                {
                    "category": r.category,
                    "rules": r.rule_top,
                    "model": r.model_top,
                    "at": r.updated_at.isoformat(),
                }
                for r in runs
                if not r.agree
            ][:20],
        }
    return out
