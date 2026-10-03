"""Rule library, current and ideal state, and the gap register."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.errors import Conflict, NotFound, StaleVersion, ValidationFailed
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import record
from app.modules.customers.contracts import (
    BriefRef,
    Stage,
    artifact_locked_event,
    get_brief_ref,
    get_project_ref,
)
from app.modules.identity.contracts import P, Principal, audit_context, ensure_different_people
from app.modules.infra import dsl
from app.modules.infra.facts import FACT_CATALOGUE, FactSheet, build_facts
from app.modules.infra.models import (
    COMPONENTS,
    LENSES,
    PRIORITIES,
    Gap,
    GapRegister,
    InfraRule,
    InfraState,
    RuleChange,
)
from app.modules.prismsuite.contracts import AuditSnapshot, get_approved_audit

ARTIFACT_CURRENT = "infra_current"
ARTIFACT_IDEAL = "infra_ideal"
ARTIFACT_GAPS = "gap_register"
RULE_FIELDS = (
    "title",
    "component",
    "lens",
    "gap_type",
    "priority",
    "priority_overrides",
    "when",
    "verify_if_unknown",
    "affected_list",
    "qty_fact",
    "recommendation",
    "target",
    "company_sizes",
    "budget_tiers",
)


# ------------------------------------------------------------------ rule library


def validate_rule_payload(data: dict[str, Any]) -> None:
    """Checks a whole rule. Raises ValidationFailed with a message a person can act on."""
    missing = [
        k
        for k in (
            "title",
            "component",
            "lens",
            "gap_type",
            "priority",
            "when",
            "recommendation",
            "target",
        )
        if not data.get(k)
    ]
    if missing:
        raise ValidationFailed(f"A rule needs: {', '.join(missing)}.")
    if data["component"] not in COMPONENTS:
        raise ValidationFailed(f"Component must be one of {', '.join(COMPONENTS)}.")
    if data["lens"] not in LENSES:
        raise ValidationFailed(f"Lens must be one of {', '.join(LENSES)}.")
    if data["priority"] not in PRIORITIES:
        raise ValidationFailed("Priority must be high or consider.")
    try:
        dsl.validate(data["when"])
        for o in data.get("priority_overrides", []):
            dsl.validate(o["when"])
            if o["priority"] not in PRIORITIES:
                raise dsl.RuleError("Override priority must be high or consider.")
    except (dsl.RuleError, KeyError, TypeError) as exc:
        raise ValidationFailed(f"The condition is not valid: {exc}", code="rule_invalid") from exc
    for key in ("affected_list", "qty_fact"):
        v = data.get(key)
        if v and key == "qty_fact" and v not in FACT_CATALOGUE:
            raise ValidationFailed(f"Unknown fact '{v}' in qty_fact.")


async def list_rules(
    session: AsyncSession, *, component: str | None = None, active: bool | None = None
) -> list[InfraRule]:
    stmt = select(InfraRule).order_by(InfraRule.component, InfraRule.code)
    if component:
        stmt = stmt.where(InfraRule.component == component)
    if active is not None:
        stmt = stmt.where(InfraRule.active == active)
    return list(await session.scalars(stmt))


async def get_rule(session: AsyncSession, rule_id: uuid.UUID) -> InfraRule:
    r = await session.get(InfraRule, rule_id)
    if r is None:
        raise NotFound("Rule not found.")
    return r


def _rule_dict(r: InfraRule) -> dict[str, Any]:
    return {k: getattr(r, k) for k in RULE_FIELDS}


async def propose_change(
    session: AsyncSession,
    principal: Principal,
    *,
    rule_id: uuid.UUID | None,
    kind: str,
    proposed: dict[str, Any],
    reason: str,
) -> RuleChange:
    principal.require(P.RULE_EDIT)
    before: dict[str, Any] | None = None
    if kind == "create":
        code = str(proposed.get("code", "")).strip().upper()
        if not code or len(code) > 40:
            raise ValidationFailed("A new rule needs a code of up to 40 characters.")
        if await session.scalar(select(InfraRule.id).where(InfraRule.code == code)):
            raise Conflict("A rule with this code already exists.", code="rule_exists")
        proposed = {**proposed, "code": code}
        validate_rule_payload(proposed)
    else:
        if rule_id is None:
            raise ValidationFailed("Say which rule to change.")
        rule = await get_rule(session, rule_id)
        before = _rule_dict(rule)
        if kind == "update":
            merged = {**before, **{k: v for k, v in proposed.items() if k in RULE_FIELDS}}
            validate_rule_payload(merged)
            proposed = merged
        elif kind == "deactivate":
            proposed = {}
        else:
            raise ValidationFailed("Kind must be create, update or deactivate.")
    if rule_id and await session.scalar(
        select(RuleChange.id).where(RuleChange.rule_id == rule_id, RuleChange.status == "pending")
    ):
        raise Conflict(
            "This rule already has a change waiting for approval.", code="change_pending"
        )
    ch = RuleChange(
        rule_id=rule_id,
        kind=kind,
        proposed=proposed,
        before=before,
        reason=reason,
        submitted_by=principal.user_id,
    )
    session.add(ch)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="rule_change_proposed",
        entity_type="infra_rule",
        entity_id=rule_id or ch.id,
        after={"kind": kind, "reason": reason, "proposed": proposed},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(ch)
    return ch


async def list_changes(session: AsyncSession, status: str = "pending") -> list[RuleChange]:
    return list(
        await session.scalars(
            select(RuleChange).where(RuleChange.status == status).order_by(RuleChange.created_at)
        )
    )


async def decide_change(
    session: AsyncSession,
    principal: Principal,
    change_id: uuid.UUID,
    *,
    approve: bool,
    note: str | None,
) -> RuleChange:
    principal.require(P.RULE_APPROVE)
    ch = await session.get(RuleChange, change_id)
    if ch is None or ch.status != "pending":
        raise NotFound("That change was not found or is already decided.")
    ensure_different_people(ch.submitted_by, principal.user_id, "rule change")
    if not approve and (not note or len(note.strip()) < 3):
        raise ValidationFailed("Say why the change is rejected.")
    if approve:
        if ch.kind == "create":
            session.add(
                InfraRule(
                    **{k: ch.proposed[k] for k in RULE_FIELDS if k in ch.proposed},
                    code=ch.proposed["code"],
                )
            )
        else:
            assert ch.rule_id is not None
            rule = await get_rule(session, ch.rule_id)
            if ch.kind == "deactivate":
                rule.active = False
            else:
                for k in RULE_FIELDS:
                    if k in ch.proposed:
                        setattr(rule, k, ch.proposed[k])
            rule.rule_version += 1
    ch.status = "approved" if approve else "rejected"
    ch.decided_by, ch.decided_at, ch.decision_note = principal.user_id, utcnow(), note
    await record(
        session,
        audit_context(principal),
        action="rule_change_approved" if approve else "rule_change_rejected",
        entity_type="infra_rule",
        entity_id=ch.rule_id or ch.id,
        after={"kind": ch.kind, "note": note},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(ch)
    return ch


# ------------------------------------------------------------------ evaluation


@dataclass
class Outcome:
    rule: InfraRule
    status: str  # gap | verify
    priority: str
    affected: list[str]
    qty: int | None
    evidence: dict[str, Any]


def applies(rule: InfraRule, brief: BriefRef | None) -> bool:
    if not rule.active:
        return False
    if brief is None:
        return True
    return brief.company_size in (
        rule.company_sizes or [brief.company_size]
    ) and brief.budget_tier in (rule.budget_tiers or [brief.budget_tier])


def evaluate_rules(
    rules: list[InfraRule], sheet: FactSheet, brief: BriefRef | None
) -> tuple[list[Outcome], list[tuple[InfraRule, str]]]:
    """Returns (gaps and verify items, the rules that are met). A rule that applies and is
    neither a gap nor a verify item is met."""
    outcomes: list[Outcome] = []
    met: list[tuple[InfraRule, str]] = []
    for r in rules:
        if not applies(r, brief):
            continue
        res = dsl.evaluate(r.when, sheet)
        used = sorted(dsl.facts_used(r.when))
        evidence = {k: sheet.get(k) for k in used}
        if res is True:
            prio = r.priority
            for o in r.priority_overrides or []:
                if dsl.evaluate(o["when"], sheet) is True:
                    prio = o["priority"]
            affected = list(sheet.lists.get(r.affected_list or "", []))
            qty = sheet.get(r.qty_fact) if r.qty_fact else (len(affected) or None)
            outcomes.append(
                Outcome(
                    r,
                    "gap",
                    prio,
                    affected,
                    int(qty) if isinstance(qty, int | float) else None,
                    evidence,
                )
            )
        elif res is None and r.verify_if_unknown:
            outcomes.append(Outcome(r, "verify", r.priority, [], None, evidence))
        else:
            met.append((r, "unknown" if res is None else "met"))
    return outcomes, met


# ------------------------------------------------------------------ states


def _device_row(d: Any) -> dict[str, Any]:
    return {
        "brand_model": d.brand_model,
        "age": d.age,
        "managed": d.managed,
        "firmware": d.firmware,
        "storage_used_percent": str(d.storage_used_percent)
        if d.storage_used_percent is not None
        else None,
        "configuration": d.configuration,
    }


def build_current_data(snap: AuditSnapshot, sheet: FactSheet) -> dict[str, Any]:
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for d in snap.devices:
        by_cat.setdefault(d.category.value, []).append(_device_row(d))
    os_counts: dict[str, int] = {}
    for e in snap.endpoints:
        os_counts[e.os or "unknown"] = os_counts.get(e.os or "unknown", 0) + 1
    sc = snap.scores
    lenses = {
        "productivity": {"score": sheet.get("score.performance"), "from": "PrismSuite performance"},
        "resilience": {
            "score": sheet.get("score.high_availability"),
            "from": "PrismSuite high availability",
        },
        "security": {"score": sheet.get("score.security"), "from": "PrismSuite security"},
        "health": {"score": sheet.get("score.system_health"), "from": "PrismSuite system health"},
    }
    return {
        "customer": snap.header.customer_name,
        "report_reference": snap.header.report_reference,
        "audit_date": str(snap.header.audit_date) if snap.header.audit_date else None,
        "lenses": lenses,
        "components": {
            "endpoints": {
                "count": sheet.get("endpoint.count"),
                "os": os_counts,
                "multi_av": sheet.lists.get("endpoint.multi_av_systems", []),
                "ram_low": sheet.lists.get("endpoint.ram_low_systems", []),
                "office_old": sheet.lists.get("endpoint.office_old_systems", []),
                "eps_coverage": sheet.get("endpoint.eps_coverage"),
            },
            "servers": by_cat.get("server", []),
            "firewalls": by_cat.get("firewall", []),
            "nas": by_cat.get("nas", []),
            "switches": by_cat.get("switch", []),
            "routers": by_cat.get("router", []),
            "access_points": {"count": snap.assets.access_points},
        },
        "facts": sheet.facts,
        "unknown_facts": sorted(k for k, v in sheet.facts.items() if v is None),
        "other_scores": {
            "high_availability": str(sc.high_availability.value),
            "performance": str(sc.performance.value),
        },
    }


async def _next_number(session: AsyncSession, model: Any, *cond: Any) -> int:
    n = await session.scalar(select(func.coalesce(func.max(model.number), 0)).where(*cond))
    return int(n or 0) + 1


async def build_current(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> InfraState:
    principal.require(P.INFRA_WRITE)
    await get_project_ref(session, principal, project_id)
    audit = await get_approved_audit(session, principal, project_id)
    sheet = build_facts(audit.snapshot)
    data = build_current_data(audit.snapshot, sheet)
    for old in await session.scalars(
        select(InfraState).where(
            InfraState.project_id == project_id,
            InfraState.kind == "current",
            InfraState.status == "draft",
        )
    ):
        old.status = "superseded"
    st = InfraState(
        project_id=project_id,
        kind="current",
        number=await _next_number(
            session, InfraState, InfraState.project_id == project_id, InfraState.kind == "current"
        ),
        data=data,
        source_import_id=audit.import_id,
        created_by=principal.user_id,
    )
    session.add(st)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="build_current",
        entity_type="infra_state",
        entity_id=st.id,
        after={
            "project_id": str(project_id),
            "number": st.number,
            "audit_revision": audit.revision,
        },
        only_changes=False,
    )
    await session.commit()
    await session.refresh(st)
    return st


async def _latest(
    session: AsyncSession, project_id: uuid.UUID, kind: str, status: str | None = None
) -> InfraState | None:
    stmt = select(InfraState).where(InfraState.project_id == project_id, InfraState.kind == kind)
    if status:
        stmt = stmt.where(InfraState.status == status)
    else:
        stmt = stmt.where(InfraState.status != "superseded")
    return await session.scalar(stmt.order_by(InfraState.number.desc()).limit(1))


async def build_ideal(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> InfraState:
    principal.require(P.INFRA_WRITE)
    await get_project_ref(session, principal, project_id)
    current = await _latest(session, project_id, "current", "locked")
    if current is None:
        raise Conflict("Lock the current IT infrastructure first.", code="current_not_locked")
    brief = await get_brief_ref(session, principal, project_id)
    if brief is None:
        raise ValidationFailed(
            "Fill in the intake questionnaire first: the company size and budget tier choose the rules.",
            code="brief_required",
        )
    audit = await get_approved_audit(session, principal, project_id)
    sheet = build_facts(audit.snapshot)
    rules = await list_rules(session, active=True)
    outcomes, met = evaluate_rules(rules, sheet, brief)
    status_of = {o.rule.code: o.status for o in outcomes}
    status_of.update({r.code: s for r, s in met})
    items = []
    for r in rules:
        if not applies(r, brief):
            continue
        s = status_of.get(r.code, "met")
        items.append(
            {
                "code": r.code,
                "rule_version": r.rule_version,
                "component": r.component,
                "lens": r.lens,
                "title": r.title,
                "target": r.target,
                "status": {
                    "gap": "not_met",
                    "verify": "unknown",
                    "met": "met",
                    "unknown": "unknown",
                }[s],
                "priority": next(
                    (o.priority for o in outcomes if o.rule.code == r.code), r.priority
                ),
            }
        )
    tier = {"company_size": brief.company_size, "budget_tier": brief.budget_tier}
    data = {
        "tier": tier,
        "targets": items,
        "summary": {
            "rules": len(items),
            "met": sum(1 for i in items if i["status"] == "met"),
            "not_met": sum(1 for i in items if i["status"] == "not_met"),
            "unknown": sum(1 for i in items if i["status"] == "unknown"),
        },
    }
    for old in await session.scalars(
        select(InfraState).where(
            InfraState.project_id == project_id,
            InfraState.kind == "ideal",
            InfraState.status == "draft",
        )
    ):
        old.status = "superseded"
    st = InfraState(
        project_id=project_id,
        kind="ideal",
        number=await _next_number(
            session, InfraState, InfraState.project_id == project_id, InfraState.kind == "ideal"
        ),
        data=data,
        source_import_id=audit.import_id,
        rule_versions={r.code: r.rule_version for r in rules if applies(r, brief)},
        created_by=principal.user_id,
    )
    session.add(st)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="build_ideal",
        entity_type="infra_state",
        entity_id=st.id,
        after={"project_id": str(project_id), "number": st.number, "tier": tier},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(st)
    return st


async def lock_state(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, state_id: uuid.UUID
) -> InfraState:
    principal.require(P.INFRA_WRITE)
    await get_project_ref(session, principal, project_id)
    st = await session.get(InfraState, state_id)
    if st is None or st.project_id != project_id:
        raise NotFound("State not found.")
    if st.status != "draft":
        raise Conflict(f"This state is already {st.status}.")
    st.status, st.locked_by, st.locked_at = "locked", principal.user_id, utcnow()
    stage, art = (
        (Stage.CURRENT_INFRA, ARTIFACT_CURRENT)
        if st.kind == "current"
        else (Stage.IDEAL_INFRA, ARTIFACT_IDEAL)
    )
    outbox.publish(
        session,
        artifact_locked_event(
            project_id=project_id,
            stage=stage,
            artifact_type=art,
            artifact_id=str(st.id),
            artifact_version=st.number,
            title=f"{'Current' if st.kind == 'current' else 'Ideal'} IT infrastructure v{st.number}",
            locked_by=principal.user_id,
        ),
    )
    await record(
        session,
        audit_context(principal),
        action="lock_state",
        entity_type="infra_state",
        entity_id=st.id,
        after={"kind": st.kind, "number": st.number},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(st)
    return st


async def list_states(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[InfraState]:
    principal.require(P.INFRA_READ)
    await get_project_ref(session, principal, project_id)
    return list(
        await session.scalars(
            select(InfraState)
            .where(InfraState.project_id == project_id)
            .order_by(InfraState.kind, InfraState.number.desc())
        )
    )


# ------------------------------------------------------------------ gap register


async def generate_register(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> GapRegister:
    principal.require(P.INFRA_WRITE)
    await get_project_ref(session, principal, project_id)
    current = await _latest(session, project_id, "current", "locked")
    if current is None:
        raise Conflict("Lock the current IT infrastructure first.", code="current_not_locked")
    brief = await get_brief_ref(session, principal, project_id)
    audit = await get_approved_audit(session, principal, project_id)
    sheet = build_facts(audit.snapshot)
    rules = await list_rules(session, active=True)
    outcomes, _ = evaluate_rules(rules, sheet, brief)
    for old in await session.scalars(
        select(GapRegister).where(
            GapRegister.project_id == project_id, GapRegister.status == "draft"
        )
    ):
        old.status = "superseded"
    reg = GapRegister(
        project_id=project_id,
        number=await _next_number(session, GapRegister, GapRegister.project_id == project_id),
        source_state_id=current.id,
        facts=sheet.facts,
        rule_versions={o.rule.code: o.rule.rule_version for o in outcomes},
        created_by=principal.user_id,
    )
    session.add(reg)
    await session.flush()
    order = {"high": 0, "consider": 1}
    for i, o in enumerate(
        sorted(outcomes, key=lambda x: (x.status != "gap", order[x.priority], x.rule.code)), start=1
    ):
        r = o.rule
        session.add(
            Gap(
                register_id=reg.id,
                number=i,
                rule_code=r.code,
                rule_version=r.rule_version,
                gap_type=r.gap_type,
                component=r.component,
                lens=r.lens,
                title=r.title if o.status == "gap" else f"Verify on site: {r.title}",
                description=None,
                priority=o.priority,
                status="open" if o.status == "gap" else "verify",
                source="rule",
                affected=o.affected,
                qty_hint=o.qty,
                evidence=o.evidence,
                recommendation=r.recommendation,
                updated_by=principal.user_id,
            )
        )
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="generate_gaps",
        entity_type="gap_register",
        entity_id=reg.id,
        after={"project_id": str(project_id), "number": reg.number, "gaps": len(outcomes)},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(reg)
    return reg


async def get_register(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    register_id: uuid.UUID | None = None,
) -> tuple[GapRegister, list[Gap]]:
    principal.require(P.INFRA_READ)
    await get_project_ref(session, principal, project_id)
    stmt = select(GapRegister).where(GapRegister.project_id == project_id)
    stmt = (
        stmt.where(GapRegister.id == register_id)
        if register_id
        else stmt.where(GapRegister.status != "superseded")
        .order_by(GapRegister.number.desc())
        .limit(1)
    )
    reg = await session.scalar(stmt)
    if reg is None:
        raise NotFound("No gap register yet.")
    gaps = list(
        await session.scalars(select(Gap).where(Gap.register_id == reg.id).order_by(Gap.number))
    )
    return reg, gaps


async def _draft_register(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, register_id: uuid.UUID
) -> GapRegister:
    principal.require(P.INFRA_WRITE)
    await get_project_ref(session, principal, project_id)
    reg = await session.get(GapRegister, register_id)
    if reg is None or reg.project_id != project_id:
        raise NotFound("Register not found.")
    if reg.status != "draft":
        raise Conflict(
            "A locked register cannot be edited. Generate a new one.", code="register_locked"
        )
    return reg


async def _gap(session: AsyncSession, reg: GapRegister, gap_id: uuid.UUID) -> Gap:
    g = await session.get(Gap, gap_id)
    if g is None or g.register_id != reg.id:
        raise NotFound("Gap not found.")
    return g


async def update_gap(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    register_id: uuid.UUID,
    gap_id: uuid.UUID,
    *,
    version: int,
    reason: str,
    changes: dict[str, Any],
) -> Gap:
    reg = await _draft_register(session, principal, project_id, register_id)
    g = await _gap(session, reg, gap_id)
    if g.version != version:
        raise StaleVersion()
    if "priority" in changes and changes["priority"] not in PRIORITIES:
        raise ValidationFailed("Priority must be high or consider.")
    if changes.get("status") not in (None, "open", "accepted", "disputed", "dismissed"):
        raise ValidationFailed("Status must be open, accepted, disputed or dismissed.")
    before = {k: getattr(g, k) for k in changes}
    for k, v in changes.items():
        setattr(g, k, v)
    g.last_change_reason, g.updated_by = reason, principal.user_id
    await record(
        session,
        audit_context(principal),
        action="gap_edited",
        entity_type="gap",
        entity_id=g.id,
        before={k: str(v) for k, v in before.items()},
        after={**{k: str(v) for k, v in changes.items()}, "reason": reason},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(g)
    return g


async def add_manual_gap(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    register_id: uuid.UUID,
    *,
    data: dict[str, Any],
    reason: str,
) -> Gap:
    reg = await _draft_register(session, principal, project_id, register_id)
    if (
        data["component"] not in COMPONENTS
        or data["lens"] not in LENSES
        or data["priority"] not in PRIORITIES
    ):
        raise ValidationFailed("Component, lens or priority is not valid.")
    n = await session.scalar(
        select(func.coalesce(func.max(Gap.number), 0)).where(Gap.register_id == reg.id)
    )
    g = Gap(
        register_id=reg.id,
        number=int(n or 0) + 1,
        source="manual",
        status="open",
        updated_by=principal.user_id,
        last_change_reason=reason,
        **data,
    )
    session.add(g)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="gap_added",
        entity_type="gap",
        entity_id=g.id,
        after={**{k: str(v) for k, v in data.items()}, "reason": reason},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(g)
    return g


async def lock_register(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, register_id: uuid.UUID
) -> GapRegister:
    reg = await _draft_register(session, principal, project_id, register_id)
    gaps = list(await session.scalars(select(Gap).where(Gap.register_id == reg.id)))
    if any(g.status == "verify" for g in gaps):
        raise Conflict(
            "Resolve every 'verify on site' item first: turn it into a gap or dismiss it with a reason.",
            code="verify_open",
        )
    if any(g.status == "disputed" for g in gaps):
        raise Conflict(
            "A disputed gap must be settled (accepted or dismissed) before the register is locked.",
            code="gap_disputed",
        )
    if not any(g.status in ("open", "accepted") for g in gaps):
        raise Conflict(
            "There is no gap to lock. Add one or generate the register again.", code="no_gaps"
        )
    reg.status, reg.locked_by, reg.locked_at = "locked", principal.user_id, utcnow()
    outbox.publish(
        session,
        artifact_locked_event(
            project_id=project_id,
            stage=Stage.GAP_ANALYSIS,
            artifact_type=ARTIFACT_GAPS,
            artifact_id=str(reg.id),
            artifact_version=reg.number,
            title=f"Gap register v{reg.number}",
            locked_by=principal.user_id,
        ),
    )
    await record(
        session,
        audit_context(principal),
        action="lock_gaps",
        entity_type="gap_register",
        entity_id=reg.id,
        after={"number": reg.number, "gaps": len(gaps)},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(reg)
    return reg


async def locked_register(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> tuple[GapRegister, list[Gap]]:
    """For the BOQ engine: the latest locked register and its live gaps."""
    principal.require(P.INFRA_READ)
    await get_project_ref(session, principal, project_id)
    reg = await session.scalar(
        select(GapRegister)
        .where(GapRegister.project_id == project_id, GapRegister.status == "locked")
        .order_by(GapRegister.number.desc())
        .limit(1)
    )
    if reg is None:
        raise NotFound("No locked gap register for this project yet.")
    gaps = list(
        await session.scalars(
            select(Gap)
            .where(Gap.register_id == reg.id, Gap.status.in_(("open", "accepted")))
            .order_by(Gap.number)
        )
    )
    return reg, gaps
