"""Verification (phase 9): the deviation register, the severity policy, brand key mappings, the
export inspector and the Director's dashboard.

Deviations follow the configuration checks that field work publishes: a failed setting opens one
(or updates the open one), a later passing check resolves it. A verifier can also open one by hand
for a setting the check could not judge, or accept a deviation with a reason, except severities
the policy marks not acceptable (critical by default): those are fixed or waived. The person who
did the work never accepts a deviation on it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.events import DomainEvent
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import AuditContext, record
from app.modules.customers.contracts import STAGE_LABELS, get_project_ref, list_visible_projects
from app.modules.fieldops.contracts import field_snapshots, get_run_ref
from app.modules.identity.contracts import P, Principal, audit_context, ensure_different_people
from app.modules.verification.exports import parse_export, read_key_values
from app.modules.verification.models import (
    SEVERITIES,
    BrandFieldMap,
    Deviation,
    VerificationSetting,
)
from app.modules.verification.seed import DEFAULT_POLICY

# ------------------------------------------------------------------ policy


async def get_policy(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(VerificationSetting, "severity_policy")
    return dict(row.value) if row else dict(DEFAULT_POLICY)


async def set_policy(
    session: AsyncSession, principal: Principal, value: dict[str, Any]
) -> dict[str, Any]:
    principal.require(P.POLICY_EDIT)
    for k in ("certificate_blocking", "not_acceptable"):
        bad = [x for x in value.get(k, []) if x not in SEVERITIES]
        if bad:
            raise ValidationFailed(f"Unknown severity: {', '.join(bad)}.", code="unknown_severity")
    if "critical" not in value.get("certificate_blocking", []):
        raise ValidationFailed(
            "An open critical deviation always stops the certificate.", code="critical_required"
        )
    row = await session.get(VerificationSetting, "severity_policy")
    before = dict(row.value) if row else dict(DEFAULT_POLICY)
    merged = {**before, **value}
    if row is None:
        session.add(
            VerificationSetting(key="severity_policy", value=merged, updated_by=principal.user_id)
        )
    else:
        row.value, row.updated_by, row.updated_at = merged, principal.user_id, utcnow()
    await record(
        session,
        audit_context(principal),
        action="set_severity_policy",
        entity_type="verification_setting",
        entity_id="severity_policy",
        before=before,
        after=merged,
    )
    await session.commit()
    return merged


# ------------------------------------------------------------------ deviations from checks


async def record_check(session: AsyncSession, event: DomainEvent) -> None:
    """Outbox handler: keep the register in step with one configuration check. Idempotent."""
    p = event.payload
    run_id = uuid.UUID(p["run_id"])
    attempt = int(p["attempt"])
    for f in p["fields"]:
        open_dev = await session.scalar(
            select(Deviation).where(
                Deviation.run_id == run_id,
                Deviation.field_key == f["key"],
                Deviation.status == "open",
            )
        )
        if f["outcome"] == "fail":
            if open_dev is None:
                session.add(
                    Deviation(
                        project_id=uuid.UUID(p["project_id"]),
                        run_id=run_id,
                        task_ref=p["task_ref"],
                        device=p.get("device"),
                        field_key=f["key"],
                        label=f["label"],
                        severity=f.get("severity", "minor"),
                        expected=(f.get("expected") or "")[:300],
                        actual=(f.get("actual") or "")[:300] or None,
                        reason=(f.get("reason") or "")[:500],
                        source="check",
                        opened_attempt=attempt,
                    )
                )
            else:
                open_dev.actual = (f.get("actual") or "")[:300] or None
                open_dev.reason = (f.get("reason") or "")[:500]
        elif f["outcome"] == "pass" and open_dev is not None and open_dev.source == "check":
            open_dev.status = "resolved"
            open_dev.resolved_at = utcnow()
            open_dev.resolution = f"Passed on configuration check {attempt}."
    await session.flush()


# ------------------------------------------------------------------ reading and acting


async def list_deviations(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, status: str | None = None
) -> list[Deviation]:
    principal.require(P.FIELD_READ)
    await get_project_ref(session, principal, project_id)
    stmt = (
        select(Deviation)
        .where(Deviation.project_id == project_id)
        .order_by(Deviation.status, Deviation.created_at)
    )
    if status:
        stmt = stmt.where(Deviation.status == status)
    return list(await session.scalars(stmt))


async def add_deviation(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    label: str,
    severity: str,
    note: str,
    field_key: str | None,
) -> Deviation:
    """A verifier records something the check could not judge."""
    principal.require(P.FIELD_VERIFY)
    run = await get_run_ref(session, principal, run_id)
    ensure_different_people(run.assignee_id, principal.user_id, "task")
    if severity not in SEVERITIES:
        raise ValidationFailed("Severity must be critical, major or minor.")
    key = field_key or f"manual-{uuid.uuid4().hex[:8]}"
    if await session.scalar(
        select(Deviation.id).where(
            Deviation.run_id == run_id, Deviation.field_key == key, Deviation.status == "open"
        )
    ):
        raise Conflict("There is already an open deviation for this setting.", code="already_open")
    d = Deviation(
        project_id=run.project_id,
        run_id=run.id,
        task_ref=run.task_ref,
        device=run.asset,
        field_key=key,
        label=label,
        severity=severity,
        reason=note,
        source="verifier",
        opened_by=principal.user_id,
    )
    session.add(d)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="open_deviation",
        entity_type="deviation",
        entity_id=d.id,
        after={"task": run.task_ref, "label": label, "severity": severity},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(d)
    return d


async def _load(session: AsyncSession, principal: Principal, deviation_id: uuid.UUID) -> Deviation:
    d = await session.get(Deviation, deviation_id)
    if d is None:
        raise NotFound("Deviation not found.")
    await get_project_ref(session, principal, d.project_id)
    return d


async def accept_deviation(
    session: AsyncSession, principal: Principal, deviation_id: uuid.UUID, *, note: str
) -> Deviation:
    principal.require(P.FIELD_VERIFY)
    d = await _load(session, principal, deviation_id)
    if d.status != "open":
        raise Conflict("Only an open deviation can be accepted.", code="bad_state")
    policy = await get_policy(session)
    if d.severity in policy.get("not_acceptable", ["critical"]):
        raise Conflict(
            f"A {d.severity} deviation cannot be accepted. Fix it and check again, or ask the "
            "Director for a waiver.",
            code="not_acceptable",
        )
    run = await get_run_ref(session, principal, d.run_id)
    ensure_different_people(run.assignee_id, principal.user_id, "task")
    d.status, d.resolved_at, d.resolved_by, d.resolution = (
        "accepted",
        utcnow(),
        principal.user_id,
        note,
    )
    await record(
        session,
        audit_context(principal),
        action="accept_deviation",
        entity_type="deviation",
        entity_id=d.id,
        after={"note": note, "severity": d.severity},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(d)
    return d


async def mark_waived(
    session: AsyncSession, deviation_id: uuid.UUID, *, waiver: str, by: uuid.UUID
) -> None:
    """Called by reporting when a waiver for this deviation is approved and acknowledged. The
    caller commits."""
    d = await session.get(Deviation, deviation_id)
    if d is None or d.status != "open":
        return
    d.status, d.resolved_at, d.resolved_by = "waived", utcnow(), by
    d.resolution = f"Waived ({waiver})."
    await record(
        session,
        AuditContext.system("reporting"),
        action="waive_deviation",
        entity_type="deviation",
        entity_id=d.id,
        after={"waiver": waiver},
        only_changes=False,
    )


# ------------------------------------------------------------------ brand key mappings


async def list_maps(
    session: AsyncSession, principal: Principal, brand: str | None
) -> list[BrandFieldMap]:
    principal.require(P.TEMPLATE_EDIT)
    stmt = select(BrandFieldMap).order_by(BrandFieldMap.brand, BrandFieldMap.field_key)
    if brand:
        stmt = stmt.where(BrandFieldMap.brand == brand)
    return list(await session.scalars(stmt))


async def update_map(
    session: AsyncSession,
    principal: Principal,
    map_id: uuid.UUID,
    *,
    version: int,
    changes: dict[str, Any],
) -> BrandFieldMap:
    principal.require(P.TEMPLATE_EDIT)
    m = await session.get(BrandFieldMap, map_id)
    if m is None:
        raise NotFound("Mapping not found.")
    if m.version != version:
        raise Conflict(
            "Someone else changed this mapping. Reload and try again.", code="stale_version"
        )
    before = {"keys": m.keys, "rule": m.rule, "verified": m.verified, "note": m.note}
    for k in ("keys", "rule", "verified", "note"):
        if k in changes and changes[k] is not None:
            setattr(m, k, changes[k])
    m.version += 1
    await record(
        session,
        audit_context(principal),
        action="update_brand_map",
        entity_type="brand_field_map",
        entity_id=m.id,
        before=before,
        after={"keys": m.keys, "rule": m.rule, "verified": m.verified, "note": m.note},
    )
    await session.commit()
    await session.refresh(m)
    return m


async def inspect_export(
    session: AsyncSession, principal: Principal, *, name: str, data: bytes
) -> dict[str, Any]:
    """Show what a configuration export contains and which target settings the current mappings
    would read from it. Nothing is stored. Used to confirm mappings on the first real export."""
    principal.require(P.TEMPLATE_EDIT)
    parsed = parse_export(name, data)
    raw = read_key_values(data)
    facts = parsed.facts if parsed else (raw[1] if raw else {})
    brand = parsed.brand if parsed else None
    matches = []
    if brand:
        for m in await session.scalars(select(BrandFieldMap).where(BrandFieldMap.brand == brand)):
            key = next((k for k in m.keys if k in facts), None)
            matches.append(
                {
                    "field_key": m.field_key,
                    "matched_key": key,
                    "value": facts.get(key) if key else None,
                    "verified": m.verified,
                }
            )
    return {
        "brand": brand,
        "shape": parsed.shape if parsed else (raw[0] if raw else None),
        "key_count": len(facts),
        "keys": dict(sorted(facts.items())[:500]),
        "matches": matches,
    }


# ------------------------------------------------------------------ the Director's dashboard


async def open_counts(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    """Open deviations by severity for each project, in one query."""
    out = {pid: dict.fromkeys(SEVERITIES, 0) for pid in project_ids}
    if not project_ids:
        return out
    rows = await session.execute(
        select(Deviation.project_id, Deviation.severity, func.count())
        .where(Deviation.project_id.in_(project_ids), Deviation.status == "open")
        .group_by(Deviation.project_id, Deviation.severity)
    )
    for pid, severity, n in rows.tuples():
        out[pid][str(severity)] = int(n)
    return out


async def dashboard(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    """Every active project the caller can see: stage, field progress, blocked work with
    reasons, open deviations, check-ins today and time against plan."""
    principal.require(P.DASHBOARD_READ)
    now = utcnow()
    projects = []
    totals = {
        "projects": 0,
        "tasks": 0,
        "closed": 0,
        "blocked": 0,
        "checkins_today": 0,
        "open_critical": 0,
        "open_major": 0,
        "open_minor": 0,
        "behind_plan": 0,
    }
    visible = await list_visible_projects(session, principal)
    ids = [pr.id for pr in visible]
    snaps = await field_snapshots(session, principal, ids) if principal.has(P.FIELD_READ) else {}
    devs = await open_counts(session, ids)
    for pr in visible:
        snap = snaps.get(pr.id)
        dev = devs[pr.id]
        behind = bool(snap and snap["overdue"]) or bool(
            snap
            and snap["planned_end"]
            and snap["closed_share"] < 1
            and snap["planned_end"] < now.isoformat()
        )
        projects.append(
            {
                "id": str(pr.id),
                "code": pr.code,
                "name": pr.name,
                "stage": pr.current_stage.value,
                "stage_label": STAGE_LABELS[pr.current_stage],
                "field": snap,
                "open_deviations": dev,
                "behind_plan": behind,
            }
        )
        totals["projects"] += 1
        if snap:
            totals["tasks"] += snap["total"]
            totals["closed"] += snap["counts"].get("closed", 0)
            totals["blocked"] += len(snap["blocked"])
            totals["checkins_today"] += snap["checkins_today"]
        totals["open_critical"] += dev["critical"]
        totals["open_major"] += dev["major"]
        totals["open_minor"] += dev["minor"]
        totals["behind_plan"] += int(behind)
    return {"generated_at": now.isoformat(), "totals": totals, "projects": projects}
