"""Turn the accepted BOQ into a plan: tasks, dependencies, engineers, a schedule and the target
configuration for each device. Locking the plan is what the implementation-plan gate approves."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.errors import Conflict, NotFound, StaleVersion, ValidationFailed
from app.core.timeutil import IST, today_ist, utcnow
from app.modules.audit_log.contracts import record
from app.modules.boq.contracts import AcceptedBoq, get_accepted_boq
from app.modules.customers.contracts import (
    STAGE_ORDER,
    Stage,
    artifact_locked_event,
    get_project_members,
    get_project_ref,
)
from app.modules.identity.contracts import P, Principal, Role, audit_context, get_user_summary
from app.modules.infra.contracts import get_locked_gaps
from app.modules.planning import scheduler as sch
from app.modules.planning.models import (
    ConfigBaseline,
    ConfigTemplate,
    DowntimeWindow,
    EngineerLeave,
    Plan,
    PlanTask,
    TaskTemplate,
)

ARTIFACT = "implementation_plan"
MAX_SPLIT = 40
DEFAULT_SETTINGS: dict[str, Any] = {
    "work_start": "10:00",
    "work_end": "18:00",
    "work_days": [0, 1, 2, 3, 4, 5],
    "buffer_minutes": 30,
}
EDITABLE = {
    "title",
    "minutes",
    "depends_on",
    "assignee_id",
    "requires_downtime",
    "notes",
    "steps",
    "evidence",
}
SCHEDULE_FIELDS = {"minutes", "depends_on", "assignee_id", "requires_downtime"}
EVIDENCE_TYPES = {"photo", "screenshot", "config_export", "serial", "note"}
SEVERITIES = {"critical", "major", "minor"}


# ------------------------------------------------------------------ helpers


def rules_of(settings: dict[str, Any]) -> sch.Rules:
    s = {**DEFAULT_SETTINGS, **settings}
    h1, m1 = (int(x) for x in str(s["work_start"]).split(":"))
    h2, m2 = (int(x) for x in str(s["work_end"]).split(":"))
    return sch.Rules(
        time(h1, m1), time(h2, m2), frozenset(s["work_days"]), int(s["buffer_minutes"])
    )


def _validate_settings(raw: dict[str, Any]) -> dict[str, Any]:
    s = {**DEFAULT_SETTINGS, **raw}
    try:
        r = rules_of(s)
    except (ValueError, TypeError) as exc:
        raise ValidationFailed("Working hours must look like 10:00 and 18:00.") from exc
    if r.work_end <= r.work_start:
        raise ValidationFailed("The working day must end after it starts.")
    if not r.work_days or any(d not in range(7) for d in r.work_days):
        raise ValidationFailed("Choose working days between 0 (Monday) and 6 (Sunday).")
    if not 0 <= r.buffer_minutes <= 240:
        raise ValidationFailed("The buffer between tasks must be 0 to 240 minutes.")
    return {
        "work_start": r.work_start.strftime("%H:%M"),
        "work_end": r.work_end.strftime("%H:%M"),
        "work_days": sorted(r.work_days),
        "buffer_minutes": r.buffer_minutes,
    }


async def _active_plan(session: AsyncSession, project_id: uuid.UUID) -> Plan | None:
    return await session.scalar(
        select(Plan).where(Plan.project_id == project_id, Plan.status != "superseded")
    )


async def _tasks(session: AsyncSession, plan_id: uuid.UUID) -> list[PlanTask]:
    return list(
        await session.scalars(
            select(PlanTask).where(PlanTask.plan_id == plan_id).order_by(PlanTask.sequence)
        )
    )


async def _draft_plan(session: AsyncSession, principal: Principal, project_id: uuid.UUID) -> Plan:
    principal.require(P.PLAN_WRITE)
    await get_project_ref(session, principal, project_id)
    plan = await _active_plan(session, project_id)
    if plan is None:
        raise NotFound("There is no plan for this project yet. Generate it from the accepted BOQ.")
    if plan.status != "draft":
        raise Conflict(
            "This plan is locked. Send the project back to the planning stage to change it.",
            code="plan_locked",
        )
    return plan


def _sched_tasks(tasks: list[PlanTask]) -> list[sch.SchedTask]:
    return [
        sch.SchedTask(
            t.ref,
            t.minutes,
            list(t.depends_on),
            str(t.assignee_id) if t.assignee_id else None,
            t.requires_downtime,
        )
        for t in tasks
    ]


def _check_graph(tasks: list[PlanTask]) -> None:
    try:
        sch.order_tasks(_sched_tasks(tasks))
    except sch.ScheduleError as exc:
        raise ValidationFailed(str(exc), code=exc.code) from exc


def _clear_schedule(tasks: list[PlanTask]) -> None:
    for t in tasks:
        t.start_at = t.end_at = None


async def _check_engineer(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    u = await get_user_summary(session, user_id)
    if u is None or not u.is_active:
        raise ValidationFailed("That person is not an active user.")
    if Role.FIELD_ENGINEER not in u.roles:
        raise ValidationFailed("Tasks can only be assigned to field engineers.")
    members = await get_project_members(session, principal, project_id)
    if user_id not in {m.user_id for m in members}:
        raise ValidationFailed("Add this engineer to the project team first.")


# ------------------------------------------------------------------ generating


def _split_assets(
    boq: AcceptedBoq, line_gaps: tuple[str, ...], affected: dict[str, tuple[str, ...]]
) -> list[str]:
    out: list[str] = []
    for g in line_gaps:
        for a in affected.get(g, ()):
            if a not in out:
                out.append(a)
    return out


async def generate_plan(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    replace: bool = False,
    settings: dict[str, Any] | None = None,
) -> Plan:
    principal.require(P.PLAN_WRITE)
    project = await get_project_ref(session, principal, project_id)
    boq = await get_accepted_boq(session, principal, project_id)  # NotFound until accepted
    existing = await _active_plan(session, project_id)
    if existing is not None:
        if existing.status == "baselined":
            if STAGE_ORDER.index(project.current_stage) > STAGE_ORDER.index(
                Stage.IMPLEMENTATION_PLAN
            ):
                raise Conflict(
                    "The plan is approved and field work has started. Send the project back to the "
                    "planning stage before planning again.",
                    code="plan_locked",
                )
        elif not replace:
            raise Conflict(
                "A draft plan exists. Generate again with replace to start over.",
                code="plan_exists",
            )
        existing.status = "superseded"
        await session.flush()

    number = (
        await session.scalar(select(func.max(Plan.number)).where(Plan.project_id == project_id))
        or 0
    ) + 1
    templates = {
        t.key: t for t in await session.scalars(select(TaskTemplate).where(TaskTemplate.active))
    }
    configs = {c.device_type: c for c in await session.scalars(select(ConfigTemplate))}
    generic = templates.get("generic")
    if generic is None:
        raise Conflict("The task library is empty. Run the seed first.", code="not_seeded")
    try:
        gaps = await get_locked_gaps(session, principal, project_id)
        affected = {g.code: g.affected for g in gaps.gaps}
    except NotFound:
        affected = {}

    plan = Plan(
        project_id=project_id,
        number=number,
        status="draft",
        boq_version_id=boq.version_id,
        boq_quote_ref=boq.quote_ref,
        settings=_validate_settings(settings or {}),
        created_by=principal.user_id,
        warnings=[],
    )
    session.add(plan)
    await session.flush()

    warnings: list[str] = []
    built: list[PlanTask] = []

    def add(tpl: TaskTemplate, title: str, minutes: int, line_ref: str, asset: str | None) -> None:
        built.append(
            PlanTask(
                plan_id=plan.id,
                ref=f"T{len(built) + 1:02d}",
                sequence=len(built) + 1,
                kind=tpl.key,
                title=title[:300],
                boq_line_ref=line_ref,
                asset=asset,
                minutes=max(minutes, 15),
                depends_on=[],
                requires_downtime=tpl.requires_downtime,
                device_type=tpl.device_type,
                steps=list(tpl.steps),
                evidence=list(tpl.evidence),
                source="template",
            )
        )

    for ln in boq.lines:
        key = ln.role_hint or ""
        tpl = templates.get(key)
        if tpl is None:
            tpl = generic
            warnings.append(
                f"BOQ line {ln.ref} ({ln.title}) has no task template, so a generic task was "
                "made. Edit its steps."
            )
        if tpl.split_per_unit and 1 < ln.qty <= MAX_SPLIT:
            assets = _split_assets(boq, ln.source_gaps, affected)
            for i in range(ln.qty):
                asset = assets[i] if i < len(assets) else None
                label = asset or f"unit {i + 1} of {ln.qty}"
                add(
                    tpl,
                    f"{tpl.title}: {label}",
                    tpl.minutes_per_unit + tpl.minutes_fixed // ln.qty,
                    ln.ref,
                    asset,
                )
        else:
            title = f"{tpl.title}: {ln.title}" if tpl is generic else tpl.title
            add(tpl, title, tpl.minutes_fixed + tpl.minutes_per_unit * ln.qty, ln.ref, None)

    by_kind: dict[str, list[PlanTask]] = {}
    for t in built:
        by_kind.setdefault(t.kind, []).append(t)
    for t in built:
        tpl = templates.get(t.kind) or generic
        deps: list[str] = []
        for kind in tpl.depends_on_kinds:
            cands = by_kind.get(kind, [])
            same = [c for c in cands if t.asset and c.asset == t.asset]
            deps.extend(c.ref for c in (same or cands) if c.ref != t.ref)
        t.depends_on = list(dict.fromkeys(deps))
    session.add_all(built)

    seen: set[tuple[str, str | None]] = set()
    for t in built:
        if not t.device_type or (t.device_type, t.asset) in seen:
            continue
        seen.add((t.device_type, t.asset))
        cfg = configs.get(t.device_type)
        if cfg is None:
            continue
        label = t.asset or f"{cfg.title} (all units in scope)"
        session.add(
            ConfigBaseline(
                plan_id=plan.id,
                task_ref=t.ref,
                device_type=t.device_type,
                device_label=label[:200],
                fields=[dict(f) for f in cfg.fields],
            )
        )
    plan.warnings = warnings
    _check_graph(built)
    await record(
        session,
        audit_context(principal),
        action="generate_plan",
        entity_type="plan",
        entity_id=plan.id,
        after={"number": number, "tasks": len(built), "boq": boq.quote_ref},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(plan)
    return plan


# ------------------------------------------------------------------ reading


async def get_plan(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> tuple[Plan, list[PlanTask], list[ConfigBaseline], list[DowntimeWindow]] | None:
    principal.require(P.PLAN_READ)
    await get_project_ref(session, principal, project_id)
    plan = await _active_plan(session, project_id)
    if plan is None:
        return None
    tasks = await _tasks(session, plan.id)
    base = list(
        await session.scalars(
            select(ConfigBaseline)
            .where(ConfigBaseline.plan_id == plan.id)
            .order_by(ConfigBaseline.device_type, ConfigBaseline.device_label)
        )
    )
    wins = list(
        await session.scalars(
            select(DowntimeWindow)
            .where(DowntimeWindow.project_id == project_id)
            .order_by(DowntimeWindow.start_at)
        )
    )
    return plan, tasks, base, wins


# ------------------------------------------------------------------ editing tasks


async def update_task(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    version: int,
    reason: str,
    changes: dict[str, Any],
) -> PlanTask:
    plan = await _draft_plan(session, principal, project_id)
    tasks = await _tasks(session, plan.id)
    t = next((x for x in tasks if x.id == task_id), None)
    if t is None:
        raise NotFound("Task not found.")
    if t.version != version:
        raise StaleVersion()
    bad = set(changes) - EDITABLE
    if bad:
        raise ValidationFailed(f"These fields cannot be changed here: {', '.join(sorted(bad))}.")
    if "minutes" in changes and not 15 <= int(changes["minutes"]) <= 60 * 24 * 10:
        raise ValidationFailed("A task takes between 15 minutes and 10 days.")
    if "title" in changes and not str(changes["title"]).strip():
        raise ValidationFailed("A task needs a title.")
    if "assignee_id" in changes and changes["assignee_id"] is not None:
        await _check_engineer(session, principal, project_id, changes["assignee_id"])
    if "evidence" in changes:
        for e in changes["evidence"]:
            if e.get("type") not in EVIDENCE_TYPES or not str(e.get("label", "")).strip():
                raise ValidationFailed("Each evidence item needs a type and a label.")
    before = {k: getattr(t, k) for k in changes}
    for k, v in changes.items():
        setattr(t, k, v)
    t.last_change_reason = reason[:300]
    _check_graph(tasks)
    if SCHEDULE_FIELDS & set(changes):
        _clear_schedule(tasks)
    await record(
        session,
        audit_context(principal),
        action="update_plan_task",
        entity_type="plan_task",
        entity_id=t.id,
        before={**before, "reason": None},
        after={**changes, "reason": reason},
    )
    await session.commit()
    await session.refresh(t)
    return t


async def add_task(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    reason: str,
    title: str,
    minutes: int,
    depends_on: list[str],
    steps: list[str],
    evidence: list[dict[str, Any]],
    requires_downtime: bool,
    device_type: str | None,
) -> PlanTask:
    plan = await _draft_plan(session, principal, project_id)
    tasks = await _tasks(session, plan.id)
    if not 15 <= minutes <= 60 * 24 * 10:
        raise ValidationFailed("A task takes between 15 minutes and 10 days.")
    n = max((t.sequence for t in tasks), default=0) + 1
    t = PlanTask(
        plan_id=plan.id,
        ref=f"T{n:02d}",
        sequence=n,
        kind="manual",
        title=title.strip()[:300],
        minutes=minutes,
        depends_on=depends_on,
        requires_downtime=requires_downtime,
        device_type=device_type,
        steps=steps,
        evidence=evidence,
        source="manual",
        last_change_reason=reason[:300],
    )
    session.add(t)
    await session.flush()
    _check_graph([*tasks, t])
    _clear_schedule(tasks)
    await record(
        session,
        audit_context(principal),
        action="add_plan_task",
        entity_type="plan_task",
        entity_id=t.id,
        after={"ref": t.ref, "title": t.title, "reason": reason},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(t)
    return t


async def delete_task(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    reason: str,
) -> None:
    plan = await _draft_plan(session, principal, project_id)
    tasks = await _tasks(session, plan.id)
    t = next((x for x in tasks if x.id == task_id), None)
    if t is None:
        raise NotFound("Task not found.")
    for o in tasks:
        if t.ref in o.depends_on:
            o.depends_on = [d for d in o.depends_on if d != t.ref]
    await record(
        session,
        audit_context(principal),
        action="delete_plan_task",
        entity_type="plan_task",
        entity_id=t.id,
        before={"ref": t.ref, "title": t.title},
        after={"reason": reason},
        only_changes=False,
    )
    await session.delete(t)
    _clear_schedule(tasks)
    await session.commit()


# ------------------------------------------------------------------ baselines (target config)


async def update_baseline(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    baseline_id: uuid.UUID,
    *,
    version: int,
    reason: str,
    fields: list[dict[str, Any]],
) -> ConfigBaseline:
    plan = await _draft_plan(session, principal, project_id)
    b = await session.scalar(
        select(ConfigBaseline).where(
            ConfigBaseline.id == baseline_id, ConfigBaseline.plan_id == plan.id
        )
    )
    if b is None:
        raise NotFound("Configuration baseline not found.")
    if b.version != version:
        raise StaleVersion()
    keys: set[str] = set()
    for f in fields:
        if (
            not f.get("key")
            or not str(f.get("expected", "")).strip()
            or not str(f.get("label", "")).strip()
        ):
            raise ValidationFailed("Every setting needs a key, a label and the expected value.")
        if f.get("severity") not in SEVERITIES:
            raise ValidationFailed("Severity must be critical, major or minor.")
        if f["key"] in keys:
            raise ValidationFailed(f"The setting {f['key']} appears twice.")
        keys.add(f["key"])
    if not fields:
        raise ValidationFailed("A baseline needs at least one setting.")
    before = {"fields": b.fields}
    b.fields = fields
    await record(
        session,
        audit_context(principal),
        action="update_config_baseline",
        entity_type="config_baseline",
        entity_id=b.id,
        before=before,
        after={"fields": fields, "reason": reason},
    )
    await session.commit()
    await session.refresh(b)
    return b


# ------------------------------------------------------------------ leave and downtime


async def add_leave(
    session: AsyncSession,
    principal: Principal,
    *,
    user_id: uuid.UUID,
    date_from: date,
    date_to: date,
    reason: str | None,
) -> EngineerLeave:
    principal.require(P.PLAN_WRITE)
    if date_to < date_from:
        raise ValidationFailed("The leave must end on or after the day it starts.")
    u = await get_user_summary(session, user_id)
    if u is None:
        raise NotFound("User not found.")
    row = EngineerLeave(
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        reason=reason,
        created_by=principal.user_id,
    )
    session.add(row)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="add_leave",
        entity_type="engineer_leave",
        entity_id=row.id,
        after={"user_id": str(user_id), "from": str(date_from), "to": str(date_to)},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(row)
    return row


async def list_leaves(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID | None
) -> list[EngineerLeave]:
    principal.require(P.PLAN_READ)
    stmt = select(EngineerLeave).order_by(EngineerLeave.date_from)
    if user_id:
        stmt = stmt.where(EngineerLeave.user_id == user_id)
    return list(await session.scalars(stmt))


async def delete_leave(session: AsyncSession, principal: Principal, leave_id: uuid.UUID) -> None:
    principal.require(P.PLAN_WRITE)
    row = await session.get(EngineerLeave, leave_id)
    if row is None:
        raise NotFound("Leave not found.")
    await record(
        session,
        audit_context(principal),
        action="delete_leave",
        entity_type="engineer_leave",
        entity_id=row.id,
        before={"user_id": str(row.user_id), "from": str(row.date_from), "to": str(row.date_to)},
        only_changes=False,
    )
    await session.delete(row)
    await session.commit()


async def add_window(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    start_at: datetime,
    end_at: datetime,
    note: str | None,
) -> DowntimeWindow:
    plan = await _draft_plan(session, principal, project_id)
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise ValidationFailed("Give the window times with a time zone.")
    if end_at <= start_at:
        raise ValidationFailed("The window must end after it starts.")
    if end_at <= utcnow():
        raise ValidationFailed("That window is already in the past.")
    row = DowntimeWindow(
        project_id=project_id,
        start_at=start_at,
        end_at=end_at,
        note=note,
        created_by=principal.user_id,
    )
    session.add(row)
    _clear_schedule(await _tasks(session, plan.id))
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="add_downtime_window",
        entity_type="downtime_window",
        entity_id=row.id,
        after={"start": start_at.isoformat(), "end": end_at.isoformat()},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(row)
    return row


async def delete_window(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, window_id: uuid.UUID
) -> None:
    plan = await _draft_plan(session, principal, project_id)
    row = await session.scalar(
        select(DowntimeWindow).where(
            DowntimeWindow.id == window_id, DowntimeWindow.project_id == project_id
        )
    )
    if row is None:
        raise NotFound("Downtime window not found.")
    _clear_schedule(await _tasks(session, plan.id))
    await record(
        session,
        audit_context(principal),
        action="delete_downtime_window",
        entity_type="downtime_window",
        entity_id=row.id,
        before={"start": row.start_at.isoformat(), "end": row.end_at.isoformat()},
        only_changes=False,
    )
    await session.delete(row)
    await session.commit()


# ------------------------------------------------------------------ scheduling


async def schedule_plan(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    start_date: date,
    auto_assign: bool,
    settings: dict[str, Any] | None = None,
) -> tuple[Plan, list[PlanTask]]:
    plan = await _draft_plan(session, principal, project_id)
    if start_date < today_ist():
        raise ValidationFailed("The plan cannot start in the past.")
    if settings:
        plan.settings = _validate_settings({**plan.settings, **settings})
    rules = rules_of(plan.settings)
    tasks = await _tasks(session, plan.id)
    if not tasks:
        raise Conflict("The plan has no tasks.", code="no_tasks")
    warnings: list[str] = [w for w in plan.warnings if "no task template" in w]

    members = await get_project_members(session, principal, project_id)
    engineers: list[uuid.UUID] = []
    for m in members:
        u = await get_user_summary(session, m.user_id)
        if u and u.is_active and Role.FIELD_ENGINEER in u.roles:
            engineers.append(m.user_id)
    if auto_assign:
        if not engineers:
            raise Conflict(
                "Add at least one field engineer to the project team to assign tasks.",
                code="no_engineers",
            )
        load: dict[uuid.UUID, int] = dict.fromkeys(engineers, 0)
        for t in tasks:
            if t.assignee_id in load:
                load[t.assignee_id] += t.minutes
        for t in tasks:
            if t.assignee_id is None:
                e = min(load, key=lambda k: load[k])
                t.assignee_id = e
                load[e] += t.minutes
    unassigned = [t.ref for t in tasks if t.assignee_id is None]
    if unassigned:
        warnings.append(
            f"{len(unassigned)} task(s) have no engineer yet: {', '.join(unassigned[:6])}."
        )

    leaves: dict[str, set[date]] = {}
    for lv in await session.scalars(
        select(EngineerLeave).where(
            EngineerLeave.user_id.in_({t.assignee_id for t in tasks if t.assignee_id})
        )
    ):
        d = lv.date_from
        while d <= lv.date_to:
            leaves.setdefault(str(lv.user_id), set()).add(d)
            d += timedelta(days=1)
    wins = [
        sch.Slot(w.start_at, w.end_at)
        for w in await session.scalars(
            select(DowntimeWindow).where(DowntimeWindow.project_id == project_id)
        )
    ]
    if any(t.requires_downtime for t in tasks) and not wins:
        raise Conflict(
            "Some tasks need downtime. Add the customer's downtime windows first.",
            code="downtime_windows_missing",
        )

    start = datetime.combine(start_date, rules.work_start, tzinfo=IST)
    try:
        placed = sch.schedule(_sched_tasks(tasks), rules, start, leaves=leaves, windows=wins)
    except sch.ScheduleError as exc:
        raise Conflict(str(exc), code=exc.code) from exc
    for t in tasks:
        slot = placed[t.ref]
        t.start_at, t.end_at = slot.start, slot.end
    plan.start_date = start_date
    plan.warnings = warnings
    await record(
        session,
        audit_context(principal),
        action="schedule_plan",
        entity_type="plan",
        entity_id=plan.id,
        after={
            "start_date": str(start_date),
            "auto_assign": auto_assign,
            "ends": max(s.end for s in placed.values()).isoformat(),
        },
        only_changes=False,
    )
    await session.commit()
    await session.refresh(plan)
    return plan, await _tasks(session, plan.id)


# ------------------------------------------------------------------ locking the baseline


async def baseline_plan(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, plan_id: uuid.UUID
) -> Plan:
    principal.require(P.PLAN_BASELINE)
    plan = await _draft_plan_for_baseline(session, principal, project_id, plan_id)
    tasks = await _tasks(session, plan.id)
    if not tasks:
        raise Conflict("The plan has no tasks.", code="no_tasks")
    problems: list[str] = []
    if any(t.start_at is None for t in tasks):
        problems.append("Schedule the plan first, so every task has a date.")
    if any(t.assignee_id is None for t in tasks):
        problems.append("Every task needs an engineer.")
    base = list(
        await session.scalars(select(ConfigBaseline).where(ConfigBaseline.plan_id == plan.id))
    )
    if any(not b.fields for b in base):
        problems.append("Every device baseline needs at least one setting.")
    _check_graph(tasks)
    if problems:
        raise Conflict(" ".join(problems), code="plan_incomplete")
    plan.status = "baselined"
    plan.baselined_by, plan.baselined_at = principal.user_id, utcnow()
    outbox.publish(
        session,
        artifact_locked_event(
            project_id=project_id,
            stage=Stage.IMPLEMENTATION_PLAN,
            artifact_type=ARTIFACT,
            artifact_id=str(plan.id),
            artifact_version=plan.number,
            title=f"Implementation plan v{plan.number}",
            locked_by=principal.user_id,
        ),
    )
    await record(
        session,
        audit_context(principal),
        action="baseline_plan",
        entity_type="plan",
        entity_id=plan.id,
        after={"number": plan.number, "tasks": len(tasks), "baselines": len(base)},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(plan)
    return plan


async def _draft_plan_for_baseline(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, plan_id: uuid.UUID
) -> Plan:
    await get_project_ref(session, principal, project_id)
    plan = await session.get(Plan, plan_id)
    if plan is None or plan.project_id != project_id:
        raise NotFound("Plan not found.")
    if plan.status != "draft":
        raise Conflict("This plan is already locked or replaced.", code="plan_locked")
    return plan


# ------------------------------------------------------------------ libraries


async def list_task_templates(session: AsyncSession, principal: Principal) -> list[TaskTemplate]:
    principal.require(P.PLAN_READ)
    return list(await session.scalars(select(TaskTemplate).order_by(TaskTemplate.key)))


async def update_task_template(
    session: AsyncSession,
    principal: Principal,
    key: str,
    *,
    version: int,
    changes: dict[str, Any],
) -> TaskTemplate:
    principal.require(P.TEMPLATE_EDIT)
    t = await session.scalar(select(TaskTemplate).where(TaskTemplate.key == key))
    if t is None:
        raise NotFound("Task template not found.")
    if t.version != version:
        raise StaleVersion()
    for k, v in changes.items():
        setattr(t, k, v)
    t.updated_by = principal.user_id
    await record(
        session,
        audit_context(principal),
        action="update_task_template",
        entity_type="plan_task_template",
        entity_id=t.id,
        after={"key": key, **changes},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(t)
    return t


async def list_config_templates(
    session: AsyncSession, principal: Principal
) -> list[ConfigTemplate]:
    principal.require(P.PLAN_READ)
    return list(await session.scalars(select(ConfigTemplate).order_by(ConfigTemplate.device_type)))
