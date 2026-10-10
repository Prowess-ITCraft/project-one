"""Learning from what customers accepted (Phase 13, ADR 0020 and 0029). Classical machine
learning only, in shadow mode first, and never deciding anything by itself.

Three kinds of model:

- ranker: weights for the recommendation criteria, from the products customers kept.
- boq_lines: which BOQ lines a set of audit findings leads to, from accepted BOQs.
- price_drift: what a price should be, from the price book history.

The flow is the same for each. Examples are recorded from events as work happens. A person
freezes them into a numbered training set with a data card. A model trains from one frozen set
only and gets a model card. It can run in shadow mode, where its answers are recorded next to
the rules'. Only the Director can approve it, after 30 days and 20 comparisons in shadow mode;
an approved model may advise people (suggested lines, price alerts) and never changes a BOQ, a
price, a verdict or a certificate. The flag `ml_enabled` switches all of it off.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import flags
from app.core.db import get_sessionmaker
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.events import DomainEvent
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import record
from app.modules.identity.contracts import (
    P,
    Principal,
    Role,
    audit_context,
    get_user_summary,
    users_with_role,
)
from app.modules.ml import cards, drift, lines, tracking
from app.modules.ml import train as t
from app.modules.ml.models import (
    MlExample,
    MlLineExample,
    MlModel,
    MlPricePoint,
    MlShadowRun,
    MlTrainingSet,
)
from app.modules.notifications.contracts import deliver_now, queue_email_to_user

SHADOW_MIN_DAYS = 30
SHADOW_MIN_COMPARISONS = 20


async def enabled(session: AsyncSession) -> bool:
    return await flags.is_enabled(session, "ml_enabled")


async def _require_on(session: AsyncSession) -> None:
    if not await enabled(session):
        raise Conflict(
            "Learning is switched off (flag ml_enabled). An Admin can switch it on.",
            code="ml_off",
        )


# ------------------------------------------------------------------ events: the ranker


async def record_recommendations(session: AsyncSession, event: DomainEvent) -> None:
    """Keep every ranked candidate. A BOQ drafted again replaces its unlabelled examples, since
    the earlier ranking is no longer what anyone saw. Idempotent."""
    if not await enabled(session):
        return
    boq_id = uuid.UUID(event.aggregate_id)
    project_id = uuid.UUID(event.payload["project_id"])
    await session.execute(
        delete(MlExample).where(MlExample.boq_id == boq_id, MlExample.kept.is_(None))
    )
    shadow = await active_shadow(session, "ranker")
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
    """The customer accepted a version: a candidate was kept if its item is in that version,
    and the BOQ's lines become the labels for line prediction. A later acceptance (after a
    reopen) relabels, so the newest decision counts."""
    if not await enabled(session):
        return
    boq_id = uuid.UUID(event.aggregate_id)
    kept = set(event.payload.get("item_ids") or [])
    now = utcnow()
    for ex in await session.scalars(select(MlExample).where(MlExample.boq_id == boq_id)):
        ex.kept, ex.labelled_at = str(ex.item_id) in kept, now
    bought = event.payload.get("lines")
    if bought is not None:
        ex2 = await session.scalar(select(MlLineExample).where(MlLineExample.boq_id == boq_id))
        if ex2 is not None:
            ex2.labels = sorted({lines.label_of(ln) for ln in bought})
            ex2.titles = {**ex2.titles, **{lines.label_of(ln): ln["title"] for ln in bought}}
            ex2.labelled_at = now
    await session.commit()


# ------------------------------------------------------------------ events: BOQ lines


async def record_line_draft(session: AsyncSession, event: DomainEvent) -> None:
    """What the rules drafted from which findings. A shadow line model predicts from the same
    findings and its answer is kept next to the rules'. Idempotent; drafting again replaces
    an unlabelled example."""
    if not await enabled(session):
        return
    boq_id = uuid.UUID(event.aggregate_id)
    drafted = event.payload.get("lines") or []
    feats = lines.featurise(event.payload.get("gaps") or {})
    ex = await session.scalar(select(MlLineExample).where(MlLineExample.boq_id == boq_id))
    if ex is None:
        ex = MlLineExample(
            boq_id=boq_id,
            project_id=uuid.UUID(event.payload["project_id"]),
            features={},
            rule_labels=[],
        )
        session.add(ex)
    elif ex.labels is not None:
        await session.commit()
        return  # already accepted: keep what the decision was made against
    ex.features = feats
    ex.rule_labels = sorted({lines.label_of(ln) for ln in drafted})
    ex.titles = {lines.label_of(ln): ln["title"] for ln in drafted}
    shadow = await active_shadow(session, "boq_lines")
    if shadow is not None and shadow.artifact:
        ex.model_id = shadow.id
        ex.model_labels = sorted(lines.predict(shadow.artifact, feats))
    await session.commit()


# ------------------------------------------------------------------ events: prices


async def record_price(session: AsyncSession, event: DomainEvent) -> None:
    """A price entered in the price book: check it against the item's history (the rule), and
    against a shadow model if one runs. A price the rule (or an approved model) flags is sent
    to the sales heads as advice. Idempotent per price."""
    if not await enabled(session):
        return
    pl = event.payload
    if "price_id" not in pl or "category" not in pl:
        return  # an event from before the price check existed
    price_id = uuid.UUID(pl["price_id"])
    if await session.scalar(select(MlPricePoint.id).where(MlPricePoint.price_id == price_id)):
        return
    item_id = uuid.UUID(pl["item_id"])
    history = [
        p.selling
        for p in await session.scalars(
            select(MlPricePoint)
            .where(MlPricePoint.item_id == item_id)
            .order_by(MlPricePoint.quoted_on, MlPricePoint.created_at)
        )
    ]
    selling = float(pl["selling"])
    verdict = drift.rule_check(history, selling)
    point = MlPricePoint(
        price_id=price_id,
        item_id=item_id,
        item_name=str(pl.get("item_name") or "")[:300],
        category=str(pl["category"])[:60],
        item_kind=str(pl.get("item_kind") or "product")[:10],
        vendor=(str(pl["vendor_id"]) if pl.get("vendor_id") else None),
        selling=selling,
        cost=float(pl["cost"]) if pl.get("cost") else None,
        quoted_on=date.fromisoformat(str(pl.get("quoted_on") or utcnow().date().isoformat())),
        rule_flag=verdict.flag,
        rule_reason=verdict.reason,
        change_pct=verdict.change_pct,
    )
    approved_flag = False
    for status in ("shadow", "approved"):
        m = await _model_with_status(session, "price_drift", status)
        if m is None or not m.artifact:
            continue
        expected, flag = drift.model_check(m.artifact, drift.point_row(point))
        if status == "shadow":
            point.model_id, point.model_expected, point.model_flag = m.id, expected, flag
        else:
            approved_flag = flag
    session.add(point)
    ids: list[uuid.UUID] = []
    if verdict.flag or approved_flag:
        change = verdict.change_pct
        for head in await users_with_role(session, Role.SALES_HEAD):
            n = await queue_email_to_user(
                session,
                user_id=head.id,
                email=head.email,
                template="price_drift",
                context={
                    "name": head.full_name,
                    "item": point.item_name or "a catalogue item",
                    "change": f"{abs(change):.0f}" if change is not None else "far",
                    "direction": "above" if (change or 0) > 0 else "below",
                },
                dedupe_key=f"price_drift:{price_id}:{head.id}"[:120],
                link=f"/catalogue/{item_id}",
            )
            ids.append(n.id)
        point.alerted = bool(ids)
    await session.commit()
    if ids:
        await deliver_now(get_sessionmaker(), ids)


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


def _line_row(ex: MlLineExample) -> dict[str, Any]:
    return {
        "boq": str(ex.boq_id),
        "features": ex.features,
        "labels": ex.labels or [],
        "rule_labels": ex.rule_labels,
        "labelled_at": ex.labelled_at.isoformat() if ex.labelled_at else None,
    }


def _line_examples(rows: list[dict[str, Any]]) -> list[lines.LineExample]:
    return [
        lines.LineExample(
            r["boq"], r["features"], frozenset(r["labels"]), frozenset(r["rule_labels"])
        )
        for r in rows
    ]


async def _ranker_rows(session: AsyncSession) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
    return rows, card


async def _line_rows(session: AsyncSession) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labelled = list(
        await session.scalars(
            select(MlLineExample)
            .where(MlLineExample.labels.is_not(None))
            .order_by(MlLineExample.created_at)
        )
    )
    if not labelled:
        raise ValidationFailed(
            "No accepted BOQ drafted from an audit yet. Examples appear when a customer "
            "accepts one.",
            code="no_examples",
        )
    rows = [_line_row(x) for x in labelled]
    label_counts = Counter(lab for r in rows for lab in r["labels"])
    dates = sorted(r["labelled_at"] for r in rows if r["labelled_at"])
    card = {
        "rows": len(rows),
        "distinct_lines": len(label_counts),
        "lines_seen_twice_or_more": sum(1 for n in label_counts.values() if n >= 2),
        "gap_types": len({f for r in rows for f in r["features"]}),
        "labelled_from": dates[0] if dates else None,
        "labelled_to": dates[-1] if dates else None,
        "source": "ml_line_examples: gap types at drafting, lines bought at acceptance",
        "personal_data": "none (gap types and BOQ line names only; no customers or prices)",
    }
    return rows, card


async def _price_rows(session: AsyncSession) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    points = list(await session.scalars(select(MlPricePoint).order_by(MlPricePoint.quoted_on)))
    if not points:
        raise ValidationFailed(
            "No prices recorded yet. Points appear as prices are entered in the price book.",
            code="no_examples",
        )
    rows = [drift.point_row(p) for p in points]
    card = {
        "rows": len(rows),
        "items": len({r["item_id"] for r in rows}),
        "categories": dict(Counter(r["category"] for r in rows).most_common()),
        "quoted_from": rows[0]["quoted_on"],
        "quoted_to": rows[-1]["quoted_on"],
        "source": "ml_price_points: every price entered in the price book",
        "personal_data": "none (no supplier names, no people)",
    }
    return rows, card


async def freeze_training_set(
    session: AsyncSession, principal: Principal, kind: str = "ranker"
) -> MlTrainingSet:
    principal.require(P.ML_MANAGE)
    await _require_on(session)
    if kind == "ranker":
        rows, card = await _ranker_rows(session)
    elif kind == "boq_lines":
        rows, card = await _line_rows(session)
    elif kind == "price_drift":
        rows, card = await _price_rows(session)
    else:
        raise ValidationFailed("Unknown kind of training set.")
    number = (await session.scalar(select(func.max(MlTrainingSet.number))) or 0) + 1
    ts = MlTrainingSet(
        number=number, kind=kind, rows=rows, data_card=card, frozen_by=principal.user_id
    )
    session.add(ts)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="freeze_training_set",
        entity_type="ml_training_set",
        entity_id=ts.id,
        after={"number": number, "kind": kind, "rows": card["rows"]},
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
    await _require_on(session)
    ts = await session.get(MlTrainingSet, training_set_id)
    if ts is None:
        raise NotFound("That training set does not exist.")
    weights: dict[str, float] = {}
    artifact: dict[str, Any] | None = None
    try:
        if ts.kind == "ranker":
            result = t.train(_examples(ts.rows))
            weights, metrics = result.weights, dict(result.metrics)
        elif ts.kind == "boq_lines":
            lm = lines.train(_line_examples(ts.rows))
            artifact, metrics = lm.artifact, lm.metrics
        else:
            dm = drift.train(ts.rows)
            artifact, metrics = dm.artifact, dm.metrics
    except (t.NotEnoughData, lines.NotEnoughData, drift.NotEnoughData) as exc:
        raise ValidationFailed(str(exc), code="not_enough_data") from exc
    number = (await session.scalar(select(func.max(MlModel.number))) or 0) + 1
    metrics = {**metrics, "training_set": ts.number}
    card = cards.build(
        kind=ts.kind,
        number=number,
        training_set={
            "number": ts.number,
            "frozen_at": ts.frozen_at.isoformat(),
            "data_card": ts.data_card,
        },
        metrics=metrics,
        trained_by=principal.full_name,
    )
    m = MlModel(
        number=number,
        kind=ts.kind,
        training_set_id=ts.id,
        weights=weights,
        artifact=artifact,
        metrics=metrics,
        card=card,
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
        after={"number": number, "kind": ts.kind, "training_set": ts.number},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(m)
    run_id = await tracking.log_training(
        kind=ts.kind, number=number, training_set=ts.number, metrics=metrics
    )
    if run_id:
        m.metrics = {**m.metrics, "mlflow_run": run_id}
        await session.commit()
        await session.refresh(m)
    return m


async def list_models(session: AsyncSession, principal: Principal) -> list[MlModel]:
    principal.require(P.ML_READ)
    return list(await session.scalars(select(MlModel).order_by(MlModel.number.desc())))


async def _model_with_status(session: AsyncSession, kind: str, status: str) -> MlModel | None:
    return await session.scalar(
        select(MlModel).where(MlModel.kind == kind, MlModel.status == status)
    )


async def active_shadow(session: AsyncSession, kind: str = "ranker") -> MlModel | None:
    return await _model_with_status(session, kind, "shadow")


async def set_status(
    session: AsyncSession, principal: Principal, model_id: uuid.UUID, status: str
) -> MlModel:
    """Start shadow mode for one model (the previous one of its kind goes back to trained), or
    retire one."""
    principal.require(P.ML_MANAGE)
    m = await session.get(MlModel, model_id, with_for_update=True)
    if m is None:
        raise NotFound("That model does not exist.")
    if m.status == "retired":
        raise Conflict("A retired model stays retired. Train a new one.", code="retired")
    if status == "shadow" and m.status == "approved":
        raise Conflict("This model is already approved.", code="already_approved")
    before = m.status
    if status == "shadow":
        await _require_on(session)
        current = await active_shadow(session, m.kind)
        if current is not None and current.id != m.id:
            current.status = "trained"
            await session.flush()
        if m.status != "shadow":
            m.shadow_started_at = utcnow()
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


async def comparisons(session: AsyncSession, m: MlModel) -> int:
    """How many real decisions a model has been compared on in shadow mode."""
    if m.kind == "ranker":
        q = select(func.count()).select_from(MlShadowRun).where(MlShadowRun.model_id == m.id)
    elif m.kind == "boq_lines":
        q = (
            select(func.count())
            .select_from(MlLineExample)
            .where(MlLineExample.model_id == m.id, MlLineExample.labels.is_not(None))
        )
    else:
        q = select(func.count()).select_from(MlPricePoint).where(MlPricePoint.model_id == m.id)
    return int(await session.scalar(q) or 0)


async def approve_model(
    session: AsyncSession, principal: Principal, model_id: uuid.UUID, note: str
) -> MlModel:
    """The Director approves a model after its shadow run (ADR 0029). An approved model only
    advises people; the one it replaces is retired."""
    principal.require(P.ML_APPROVE)
    await _require_on(session)
    m = await session.get(MlModel, model_id, with_for_update=True)
    if m is None:
        raise NotFound("That model does not exist.")
    if m.status != "shadow" or m.shadow_started_at is None:
        raise Conflict("Run the model in shadow mode first.", code="not_in_shadow")
    days = (utcnow() - m.shadow_started_at).days
    seen = await comparisons(session, m)
    if days < SHADOW_MIN_DAYS or seen < SHADOW_MIN_COMPARISONS:
        raise Conflict(
            f"A model needs {SHADOW_MIN_DAYS} days and {SHADOW_MIN_COMPARISONS} comparisons in "
            f"shadow mode; this one has {days} days and {seen}.",
            code="shadow_too_short",
            extra={"days": days, "comparisons": seen},
        )
    if len(note.strip()) < 10:
        raise ValidationFailed("Say why the model is good enough to advise people.")
    previous = await _model_with_status(session, m.kind, "approved")
    if previous is not None:
        previous.status = "retired"
        await session.flush()
    m.status, m.approved_by, m.approved_at = "approved", principal.user_id, utcnow()
    m.approval_note = note.strip()[:1000]
    m.card = {
        **(m.card or {}),
        "approval": {
            "by": principal.full_name,
            "at": m.approved_at.isoformat(),
            "note": m.approval_note,
            "shadow_days": days,
            "comparisons": seen,
        },
    }
    await record(
        session,
        audit_context(principal),
        action="model_approved",
        entity_type="ml_model",
        entity_id=m.id,
        before={"status": "shadow"},
        after={"status": "approved", "note": m.approval_note, "comparisons": seen},
    )
    await session.commit()
    await session.refresh(m)
    return m


async def model_card(
    session: AsyncSession, principal: Principal, model_id: uuid.UUID
) -> dict[str, Any]:
    principal.require(P.ML_READ)
    m = await session.get(MlModel, model_id)
    if m is None:
        raise NotFound("That model does not exist.")
    card = m.card
    if card is None:  # a ranker trained before model cards existed
        ts = await session.get(MlTrainingSet, m.training_set_id)
        trained = await get_user_summary(session, m.trained_by)
        card = cards.build(
            kind=m.kind,
            number=m.number,
            training_set={
                "number": ts.number if ts else None,
                "frozen_at": ts.frozen_at.isoformat() if ts else None,
                "data_card": ts.data_card if ts else {},
            },
            metrics=m.metrics,
            trained_by=trained.full_name if trained else "unknown",
        )
    return {
        "card": card,
        "markdown": cards.markdown(card),
        "status": m.status,
        "comparisons": await comparisons(session, m),
    }


# ------------------------------------------------------------------ advice from approved models


async def suggest_lines(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> dict[str, Any]:
    """BOQ lines an approved line model expects from this project's audit findings, with how
    sure it is. Advice for the person editing the BOQ: nothing is added by itself."""
    principal.require(P.BOQ_EDIT)
    if not await enabled(session):
        return {"available": False, "reason": "Learning is switched off.", "lines": []}
    m = await _model_with_status(session, "boq_lines", "approved")
    if m is None or not m.artifact:
        return {
            "available": False,
            "reason": "No line model is approved yet. Suggestions appear once the Director "
            "approves one after its shadow run.",
            "lines": [],
        }
    from app.modules.infra.contracts import get_locked_gaps

    gapset = await get_locked_gaps(session, principal, project_id)
    counts: dict[str, int] = {}
    for g in gapset.gaps:
        counts[g.gap_type] = counts.get(g.gap_type, 0) + max(g.qty_hint or 1, 1)
    probs = lines.probabilities(m.artifact, lines.featurise(counts))
    titles: dict[str, str] = {}
    for ex in await session.scalars(select(MlLineExample).where(MlLineExample.labels.is_not(None))):
        titles.update(ex.titles)
    out = [
        {
            "label": lab,
            "title": titles.get(lab, lab.removeprefix("title:")),
            "probability": p,
        }
        for lab, p in sorted(probs.items(), key=lambda kv: -kv[1])
        if p >= float(m.artifact.get("threshold", 0.5))
    ]
    return {"available": True, "model": m.number, "lines": out[:30], "reason": None}


# ------------------------------------------------------------------ report


async def report(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    """Where the learning stands for each kind of model: how much data there is, and how a
    shadow model compares with the rules on decisions already made."""
    principal.require(P.ML_READ)
    total = await session.scalar(select(func.count()).select_from(MlExample)) or 0
    labelled = list(await session.scalars(select(MlExample).where(MlExample.kept.is_not(None))))
    groups = t.usable_groups(_examples([_row(x) for x in labelled]))
    shadow = await active_shadow(session, "ranker")
    out: dict[str, Any] = {
        "enabled": await enabled(session),
        "examples": total,
        "labelled": len(labelled),
        "usable_groups": len(groups),
        "needed_groups": t.MIN_GROUPS,
        "rules_top1": t.top1(groups, key=lambda x: x.rule_score),
        "shadow": None,
        "shadow_rule": {"days": SHADOW_MIN_DAYS, "comparisons": SHADOW_MIN_COMPARISONS},
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
    out["lines"] = await _lines_report(session)
    out["prices"] = await _prices_report(session)
    return out


async def _lines_report(session: AsyncSession) -> dict[str, Any]:
    examples = list(await session.scalars(select(MlLineExample)))
    done = [e for e in examples if e.labels is not None]
    shadow = await active_shadow(session, "boq_lines")
    approved = await _model_with_status(session, "boq_lines", "approved")
    res: dict[str, Any] = {
        "drafted": len(examples),
        "accepted": len(done),
        "needed": lines.MIN_EXAMPLES,
        "rules": lines._f1(
            [frozenset(e.rule_labels) for e in done], [frozenset(e.labels or []) for e in done]
        )
        if done
        else None,
        "shadow": None,
        "approved_model": approved.number if approved else None,
    }
    if shadow is not None:
        mine = [e for e in done if e.model_id == shadow.id and e.model_labels is not None]
        res["shadow"] = {
            "model_id": str(shadow.id),
            "number": shadow.number,
            "since": shadow.shadow_started_at.isoformat() if shadow.shadow_started_at else None,
            "compared": len(mine),
            "model": lines._f1(
                [frozenset(e.model_labels or []) for e in mine],
                [frozenset(e.labels or []) for e in mine],
            )
            if mine
            else None,
            "rules_same_boqs": lines._f1(
                [frozenset(e.rule_labels) for e in mine], [frozenset(e.labels or []) for e in mine]
            )
            if mine
            else None,
        }
    return res


async def _prices_report(session: AsyncSession) -> dict[str, Any]:
    since = utcnow().date() - timedelta(days=90)
    points = list(await session.scalars(select(MlPricePoint)))
    recent = [p for p in points if p.quoted_on >= since]
    shadow = await active_shadow(session, "price_drift")
    res: dict[str, Any] = {
        "points": len(points),
        "needed": drift.MIN_POINTS,
        "flagged_90_days": sum(1 for p in recent if p.rule_flag),
        "alerted_90_days": sum(1 for p in recent if p.alerted),
        "latest_flags": [
            {
                "item": p.item_name,
                "reason": p.rule_reason,
                "quoted_on": p.quoted_on.isoformat(),
                "item_id": str(p.item_id),
            }
            for p in sorted(points, key=lambda p: p.created_at, reverse=True)
            if p.rule_flag
        ][:10],
        "shadow": None,
    }
    if shadow is not None:
        mine = [p for p in points if p.model_id == shadow.id and p.model_flag is not None]
        res["shadow"] = {
            "model_id": str(shadow.id),
            "number": shadow.number,
            "compared": len(mine),
            "both_flag": sum(1 for p in mine if p.model_flag and p.rule_flag),
            "only_model": sum(1 for p in mine if p.model_flag and not p.rule_flag),
            "only_rule": sum(1 for p in mine if p.rule_flag and not p.model_flag),
        }
    return res
