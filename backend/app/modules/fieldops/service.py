"""Field work: the gated state machine for a task in the field (ADR 0015).

    assigned -> accepted -> checked_in -> prechecks_done -> configured -> evidence_uploaded
             -> engine_check -> verifier_review -> closed

- Check-in needs a site photo taken with the phone's location, the location itself, every
  dependency handed over, and the customer's one-time code while customer codes are on (off for
  now, ADR 0025). Location is required at check-in only (ADR 0027).
- Prechecks need backup and access confirmed with evidence. For a firewall, switch or NAS the
  backup is a configuration export: the rollback point, compared with the export after the work.
- Configured needs every step ticked in order and a value recorded for every target setting.
- Evidence uploaded needs every required item; the engine check then runs at once. A failed
  critical or major setting sends the task back to configured.
- Hand over needs a passed check, and the customer's second code while codes are on; the task
  goes to a verifier.
- The verifier (never the engineer who did the work) closes it or sends it back to configured.

Nothing can be skipped. Every action is recorded with who, when and where, and every state
change notifies the customer's sign-off contact, the Directors and the project manager.
Offline work arrives later with `client_event_id` and `captured_at`, so repeats are harmless.
Field work never carries prices.
"""

from __future__ import annotations

import difflib
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import flags, outbox
from app.core.db import get_sessionmaker
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.events import DomainEvent
from app.core.timeutil import to_ist, utcnow
from app.modules.audit_log.contracts import record
from app.modules.customers.contracts import (
    STAGE_ORDER,
    ProjectRef,
    Stage,
    get_customer_ref,
    get_project_members,
    get_project_ref,
    get_sign_off_contacts,
)
from app.modules.fieldops import engine
from app.modules.fieldops.models import (
    FLOW,
    FieldDeviceStatus,
    FieldUploadLink,
    OtpChallenge,
    RunCheck,
    RunEvent,
    RunEvidence,
    TaskRun,
)
from app.modules.files.contracts import read_file, read_file_system, store_upload
from app.modules.identity.contracts import (
    P,
    Principal,
    Role,
    audit_context,
    ensure_different_people,
    get_user_summary,
    principal_for_link,
    users_with_role,
)
from app.modules.notifications.contracts import deliver_now, queue_email, queue_email_to_user
from app.modules.planning.contracts import get_baselined_plan
from app.modules.search.contracts import SearchDoc
from app.modules.search.contracts import index as search_index
from app.modules.search.contracts import index_many as search_index_many

# Published after every configuration check; verification keeps the deviation register from it.
CHECK_COMPLETED = "fieldops.check_completed"
OTP_TTL_MINUTES = 15
OTP_MAX_ATTEMPTS = 5
OTP_MAX_PER_HOUR = 5
OFFLINE_WINDOW_HOURS = 72
CLOCK_SKEW_MINUTES = 5
# A dependent task may start once its prerequisite is handed over (the customer confirmed it and
# the configuration check passed); waiting for the verifier would stall a site visit.
DONE_FOR_DEPENDENTS = ("verifier_review", "closed")
BLOCKABLE = ("accepted", "checked_in", "prechecks_done", "configured", "engine_check")
NETWORK_DEVICES = ("firewall", "switch", "nas", "server")
# Devices whose whole configuration can be exported as a file before the work starts.
SNAPSHOT_DEVICES = ("firewall", "switch", "nas")
UPLOAD_LINK_MINUTES = 15
STAMPABLE = ("photo", "screenshot")
# How long a phone may stay silent before the Director sees it as quiet rather than synced.
QUIET_AFTER_MINUTES = 30
FILE_PURPOSE = {
    "photo": "evidence_photo",
    "screenshot": "evidence_photo",
    "config_export": "config_export",
}
STATE_LABEL = {
    "assigned": "assigned",
    "accepted": "accepted by the engineer",
    "checked_in": "checked in on site",
    "prechecks_done": "prechecks done (backup and access confirmed)",
    "configured": "configured",
    "evidence_uploaded": "evidence uploaded",
    "engine_check": "configuration check passed, waiting for hand over",
    "verifier_review": "handed over, waiting for verification",
    "closed": "closed and verified",
    "blocked": "blocked",
}
# Which evidence may be added in which state.
EVIDENCE_WINDOW = {
    "check_in": ("accepted",),
    "prechecks": ("checked_in",),
    "work": ("prechecks_done", "configured"),
}


# ------------------------------------------------------------------ small helpers


def evidence_plan(
    task_evidence: list[dict[str, Any]], device_type: str | None
) -> list[dict[str, Any]]:
    """The evidence a run needs, in visit order: arrival, prechecks, then the task's own."""
    if device_type in SNAPSHOT_DEVICES:
        backup: dict[str, Any] = {
            "type": "config_export",
            "label": "Configuration export before any change (the rollback point)",
            "required": True,
            "snapshot": True,
        }
    elif device_type in NETWORK_DEVICES:
        backup = {
            "type": "screenshot",
            "label": "Backup of the current configuration",
            "required": True,
        }
    else:
        backup = {
            "type": "note",
            "label": "Backup confirmed: who took it and where it is",
            "required": True,
        }
    return [
        {
            "type": "photo",
            "label": "Photo of the site on arrival",
            "required": True,
            "stage": "check_in",
        },
        {**backup, "stage": "prechecks"},
        {
            "type": "note",
            "label": "Access confirmed: admin login works and a customer contact is present",
            "required": True,
            "stage": "prechecks",
        },
        *({**e, "stage": "work"} for e in task_evidence),
    ]


def task_doc(run: TaskRun, project: str | None = None) -> SearchDoc:
    """What search shows for a field task. A field engineer finds only their own."""
    return SearchDoc(
        kind="task",
        ref_id=str(run.id),
        title=f"{run.task_ref} {run.title}",
        subtitle=", ".join(x for x in (run.asset or "No device", project) if x),
        body=run.kind.replace("_", " "),
        url=f"/field/{run.id}",
        perm="field:read",
        project_id=run.project_id,
        assignee_id=run.assignee_id,
    )


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}{'*' * max(len(name) - 1, 2)}@{domain}"


def _hash(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def _captured(at: datetime | None) -> datetime:
    now = utcnow()
    if at is None:
        return now
    if at.tzinfo is None:
        raise ValidationFailed("Give the time with a time zone.", code="time_zone_missing")
    if at > now + timedelta(minutes=CLOCK_SKEW_MINUTES):
        raise ValidationFailed("That time is in the future.", code="time_in_future")
    if at < now - timedelta(hours=OFFLINE_WINDOW_HOURS):
        raise ValidationFailed(
            f"Work captured more than {OFFLINE_WINDOW_HOURS} hours ago cannot be sent. "
            "Tell the project manager.",
            code="too_old",
        )
    return at


def _check_location(lat: float | None, lng: float | None) -> None:
    if (lat is None) != (lng is None):
        raise ValidationFailed("Send both latitude and longitude, or neither.")
    if lat is not None and not (-90 <= lat <= 90 and -180 <= (lng or 0) <= 180):
        raise ValidationFailed("That location is not on Earth.")


def _need(run: TaskRun, *states: str, msg: str) -> None:
    if run.state not in states:
        raise Conflict(msg, code="bad_state", extra={"state": run.state})


async def _load(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> TaskRun:
    principal.require(P.FIELD_READ)
    run = await session.get(TaskRun, run_id)
    if run is None:
        raise NotFound("Task not found.")
    await get_project_ref(session, principal, run.project_id)
    if not (principal.has(P.FIELD_MANAGE) or principal.has(P.FIELD_VERIFY)) and (
        run.assignee_id != principal.user_id
    ):
        raise NotFound("Task not found.")
    return run


def _mine(principal: Principal, run: TaskRun) -> None:
    principal.require(P.FIELD_WORK)
    if run.assignee_id != principal.user_id:
        raise Forbidden("This task is assigned to someone else.")


async def _seen(
    session: AsyncSession, run_id: uuid.UUID, client_event_id: uuid.UUID | None
) -> bool:
    if client_event_id is None:
        return False
    return (
        await session.scalar(
            select(RunEvent.seq).where(
                RunEvent.run_id == run_id, RunEvent.client_event_id == client_event_id
            )
        )
    ) is not None


def _log(
    session: AsyncSession,
    run: TaskRun,
    principal: Principal | None,
    action: str,
    *,
    to_state: str | None = None,
    detail: dict[str, Any] | None = None,
    client_event_id: uuid.UUID | None = None,
    captured_at: datetime | None = None,
    lat: float | None = None,
    lng: float | None = None,
    accuracy_m: float | None = None,
) -> None:
    before = run.state
    if to_state and to_state != run.state:
        run.state = to_state
        run.state_changed_at = utcnow()
    session.add(
        RunEvent(
            run_id=run.id,
            project_id=run.project_id,
            captured_at=captured_at,
            client_event_id=client_event_id,
            actor_id=principal.user_id if principal else None,
            action=action,
            from_state=before,
            to_state=run.state,
            detail=detail or {},
            lat=lat,
            lng=lng,
            accuracy_m=accuracy_m,
        )
    )


async def _open_dependencies(session: AsyncSession, run: TaskRun) -> list[str]:
    if not run.depends_on:
        return []
    rows = await session.execute(
        select(TaskRun.task_ref, TaskRun.state).where(
            TaskRun.plan_id == run.plan_id, TaskRun.task_ref.in_(run.depends_on)
        )
    )
    return sorted(ref for ref, state in rows if state not in DONE_FOR_DEPENDENTS)


async def _evidence_indexes(session: AsyncSession, run: TaskRun) -> set[int]:
    return set(
        await session.scalars(
            select(RunEvidence.requirement_index).where(RunEvidence.run_id == run.id)
        )
    )


async def _missing(session: AsyncSession, run: TaskRun, stage: str) -> list[str]:
    have = await _evidence_indexes(session, run)
    return [
        r["label"]
        for i, r in enumerate(run.evidence_reqs)
        if r.get("stage", "work") == stage and r.get("required", True) and i not in have
    ]


async def _name(session: AsyncSession, user_id: uuid.UUID | None) -> str:
    u = await get_user_summary(session, user_id) if user_id else None
    return u.full_name if u else "Project One"


async def _announce(
    session: AsyncSession,
    principal: Principal,
    run: TaskRun,
    project: ProjectRef,
    note: str | None = None,
) -> list[uuid.UUID]:
    """Tell the customer's sign-off contact, every Director and the project managers that the
    task changed state. Messages are queued in this transaction and sent after the commit, so a
    mail failure never undoes the change. No prices, ever."""
    ctx = {
        "project": project.name,
        "task": f"{run.task_ref} {run.title}",
        "state": STATE_LABEL[run.state],
        "note": note or "",
        "actor": await _name(session, principal.user_id),
        "at": to_ist(utcnow()).strftime("%d %b %Y %H:%M"),
    }
    key = f"upd:{run.id}:{run.state}:{run.rework_count}:{run.version}"
    ids: list[uuid.UUID] = []
    contacts = await get_sign_off_contacts(session, principal, run.project_id)
    if contacts:
        c = contacts[0]
        ids.append(
            queue_email(
                session,
                to_address=c.email,
                template="task_update",
                context={**ctx, "name": c.full_name},
                dedupe_key=f"{key}:c:{c.id}",
                related=("task_run", str(run.id)),
            ).id
        )
    people: dict[uuid.UUID, str] = {
        u.id: u.email for u in await users_with_role(session, Role.DIRECTOR)
    }
    for m in await get_project_members(session, principal, run.project_id):
        if m.project_role == "project_manager":
            u = await get_user_summary(session, m.user_id)
            if u and u.is_active:
                people[u.id] = u.email
    for uid, email in people.items():
        n = await queue_email_to_user(
            session,
            user_id=uid,
            email=email,
            template="task_update",
            context={**ctx, "name": await _name(session, uid)},
            dedupe_key=f"{key}:u:{uid}",
            related=("task_run", str(run.id)),
        )
        ids.append(n.id)
    return ids


async def _commit_and_send(session: AsyncSession, run: TaskRun, ids: list[uuid.UUID]) -> TaskRun:
    await session.commit()
    await deliver_now(get_sessionmaker(), ids)
    await session.refresh(run)
    return run


async def _transition(
    session: AsyncSession,
    principal: Principal,
    run: TaskRun,
    action: str,
    to_state: str,
    *,
    note: str | None = None,
    detail: dict[str, Any] | None = None,
    **where: Any,
) -> list[uuid.UUID]:
    _log(session, run, principal, action, to_state=to_state, detail=detail, **where)
    project = await get_project_ref(session, principal, run.project_id)
    return await _announce(session, principal, run, project, note)


# ------------------------------------------------------------------ starting field work


async def start_field_work(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[TaskRun]:
    principal.require(P.FIELD_MANAGE)
    project = await get_project_ref(session, principal, project_id)
    if STAGE_ORDER.index(project.current_stage) < STAGE_ORDER.index(Stage.FIELD_WORK):
        raise Conflict(
            "Field work starts after the implementation plan is approved.", code="plan_not_approved"
        )
    if await session.scalar(select(TaskRun.id).where(TaskRun.project_id == project_id).limit(1)):
        raise Conflict(
            "Field work has already been started for this project.", code="already_started"
        )
    plan = await get_baselined_plan(session, principal, project_id)
    baselines = {b.task_ref: b for b in plan.baselines if b.task_ref}
    runs: list[TaskRun] = []
    for t in plan.tasks:
        if t.assignee_id is None:
            raise Conflict(f"Task {t.ref} has no engineer.", code="plan_incomplete")
        b = baselines.get(t.ref)
        runs.append(
            TaskRun(
                project_id=project_id,
                plan_id=plan.id,
                task_id=t.id,
                task_ref=t.ref,
                kind=t.kind,
                title=t.title,
                asset=t.asset,
                device_type=t.device_type,
                requires_downtime=t.requires_downtime,
                depends_on=list(t.depends_on),
                steps=[{"text": s, "done": False, "done_at": None} for s in t.steps],
                evidence_reqs=evidence_plan([dict(e) for e in t.evidence], t.device_type),
                baseline=[dict(f) for f in b.fields] if b else [],
                actuals={},
                assignee_id=t.assignee_id,
                planned_start=t.start_at,
                planned_end=t.end_at,
            )
        )
    session.add_all(runs)
    await session.flush()
    for r in runs:
        _log(session, r, principal, "created", detail={"plan": plan.number})
    where = f"{project.code} {project.name}"
    search_index_many(session, [task_doc(r, where) for r in runs], principal.user_id)
    ids: list[uuid.UUID] = []
    by_eng: dict[uuid.UUID, list[TaskRun]] = {}
    for r in runs:
        by_eng.setdefault(r.assignee_id, []).append(r)
    for eng, rs in by_eng.items():
        u = await get_user_summary(session, eng)
        if u is None:
            continue
        first = min(r.planned_start for r in rs)
        n = await queue_email_to_user(
            session,
            user_id=eng,
            email=u.email,
            template="task_assigned",
            context={
                "name": u.full_name,
                "count": len(rs),
                "project": project.name,
                "first_start": to_ist(first).strftime("%d %b %Y, %H:%M"),
            },
            dedupe_key=f"assigned:{project_id}:{eng}:{plan.number}",
            related=("project", str(project_id)),
        )
        ids.append(n.id)
    await record(
        session,
        audit_context(principal),
        action="start_field_work",
        entity_type="project",
        entity_id=project_id,
        after={"tasks": len(runs)},
        only_changes=False,
    )
    await session.commit()
    await deliver_now(get_sessionmaker(), ids)
    return runs


# ------------------------------------------------------------------ reading


async def list_runs(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, state: str | None = None
) -> list[TaskRun]:
    principal.require(P.FIELD_READ)
    await get_project_ref(session, principal, project_id)
    stmt = select(TaskRun).where(TaskRun.project_id == project_id).order_by(TaskRun.planned_start)
    if not (principal.has(P.FIELD_MANAGE) or principal.has(P.FIELD_VERIFY)):
        stmt = stmt.where(TaskRun.assignee_id == principal.user_id)
    if state:
        stmt = stmt.where(TaskRun.state == state)
    return list(await session.scalars(stmt))


async def my_runs(session: AsyncSession, principal: Principal) -> list[TaskRun]:
    principal.require(P.FIELD_WORK)
    return list(
        await session.scalars(
            select(TaskRun)
            .where(TaskRun.assignee_id == principal.user_id, TaskRun.state != "closed")
            .order_by(TaskRun.planned_start)
        )
    )


async def project_briefs(
    session: AsyncSession, principal: Principal, project_ids: set[uuid.UUID]
) -> dict[uuid.UUID, dict[str, str | None]]:
    """Code, name and customer for each project, for labelling tasks. A project the caller
    cannot see is left out rather than failing the whole list."""
    out: dict[uuid.UUID, dict[str, str | None]] = {}
    for pid in project_ids:
        try:
            p = await get_project_ref(session, principal, pid)
        except NotFound:
            continue
        try:
            customer: str | None = (
                await get_customer_ref(session, principal, p.customer_id)
            ).display_name
        except NotFound:
            customer = None
        out[pid] = {"code": p.code, "name": p.name, "customer": customer}
    return out


async def review_queue(session: AsyncSession, principal: Principal) -> list[TaskRun]:
    """Tasks waiting for a verifier, oldest first, excluding the verifier's own work."""
    principal.require(P.FIELD_VERIFY)
    runs = await session.scalars(
        select(TaskRun)
        .where(TaskRun.state == "verifier_review", TaskRun.assignee_id != principal.user_id)
        .order_by(TaskRun.state_changed_at)
    )
    out = []
    for r in runs:
        try:
            await get_project_ref(session, principal, r.project_id)
        except NotFound:
            continue
        out.append(r)
    return out


async def get_run(
    session: AsyncSession, principal: Principal, run_id: uuid.UUID
) -> tuple[TaskRun, list[RunEvent], list[RunEvidence], list[RunCheck], list[str]]:
    run = await _load(session, principal, run_id)
    events = list(
        await session.scalars(
            select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)
        )
    )
    evidence = list(
        await session.scalars(
            select(RunEvidence)
            .where(RunEvidence.run_id == run.id)
            .order_by(RunEvidence.captured_at)
        )
    )
    checks = list(
        await session.scalars(
            select(RunCheck).where(RunCheck.run_id == run.id).order_by(RunCheck.attempt)
        )
    )
    return run, events, evidence, checks, await _open_dependencies(session, run)


async def events_after(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    after: int,
    limit: int = 100,
    *,
    latest: bool = False,
) -> list[RunEvent]:
    """The live feed: every event after the cursor `after` (the last `seq` the client saw).
    With `latest`, the newest `limit` events instead, oldest first: where a feed starts."""
    principal.require(P.FIELD_READ)
    await get_project_ref(session, principal, project_id)
    stmt = (
        select(RunEvent)
        .where(RunEvent.project_id == project_id, RunEvent.seq > after)
        .order_by(RunEvent.seq.desc() if latest else RunEvent.seq)
        .limit(min(limit, 500))
    )
    if not (principal.has(P.FIELD_MANAGE) or principal.has(P.FIELD_VERIFY)):
        mine = select(TaskRun.id).where(
            TaskRun.project_id == project_id, TaskRun.assignee_id == principal.user_id
        )
        stmt = stmt.where(RunEvent.run_id.in_(mine))
    rows = list(await session.scalars(stmt))
    return rows[::-1] if latest else rows


async def summary(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> dict[str, Any]:
    """For the Director: tasks by state, blocked ones with reasons, late starts, open deviations
    and time against plan."""
    principal.require(P.FIELD_READ)
    await get_project_ref(session, principal, project_id)
    runs = await session.scalars(
        select(TaskRun).where(TaskRun.project_id == project_id).order_by(TaskRun.task_ref)
    )
    return summarise_runs(list(runs), utcnow())


def summarise_runs(runs: list[TaskRun], now: datetime) -> dict[str, Any]:
    """One project's task runs summed up. Shared by the field summary and the Director's
    dashboard, so "late", "overdue" and "failing" mean the same on both."""
    counts = dict.fromkeys((*FLOW, "blocked"), 0)
    for r in runs:
        counts[r.state] = counts.get(r.state, 0) + 1
    total = len(runs)
    return {
        "counts": counts,
        "total": total,
        "closed_share": round(counts["closed"] / total, 4) if total else 0.0,
        "blocked": [r for r in runs if r.state == "blocked"],
        "late": [
            r
            for r in runs
            if r.state in ("assigned", "accepted") and r.planned_start < now - timedelta(minutes=30)
        ],
        "overdue": [
            r for r in runs if r.state not in ("verifier_review", "closed") and r.planned_end < now
        ],
        "failing_checks": [
            r for r in runs if r.state == "configured" and r.last_check_passed is False
        ],
        "rework": sum(r.rework_count for r in runs),
    }


# ------------------------------------------------------------------ the engineer's actions


async def accept(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
) -> TaskRun:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "assigned", msg="Only a newly assigned task can be accepted.")
    cap = _captured(captured_at)
    run.accepted_at = cap
    ids = await _transition(
        session,
        principal,
        run,
        "accept",
        "accepted",
        client_event_id=client_event_id,
        captured_at=cap,
    )
    return await _commit_and_send(session, run, ids)


async def depart(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
    lat: float | None,
    lng: float | None,
    accuracy_m: float | None,
) -> TaskRun:
    """ "On my way": recorded with the location, not a state of its own (ADR 0015)."""
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "accepted", msg="Accept the task before you set off.")
    _check_location(lat, lng)
    cap = _captured(captured_at)
    _log(
        session,
        run,
        principal,
        "depart",
        client_event_id=client_event_id,
        captured_at=cap,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
    )
    await session.commit()
    await session.refresh(run)
    return run


async def codes_on(session: AsyncSession) -> bool:
    """Whether check-in and hand over need the customer's one-time code (ADR 0025)."""
    return await flags.is_enabled(session, "field_customer_codes")


async def _confirm(
    session: AsyncSession, run: TaskRun, purpose: str, code: str | None
) -> dict[str, Any]:
    """The customer's code when codes are on; otherwise the step goes ahead without one."""
    if not await codes_on(session):
        return {"customer_code": "off"}
    if not code:
        raise ValidationFailed("Enter the code the customer received.", code="code_required")
    ch = await _consume_code(session, run, purpose, code)
    return {"confirmed_by_contact": str(ch.contact_id)}


async def request_code(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    purpose: str,
) -> dict[str, Any]:
    """Send a one-time code to the customer's sign-off contact. The engineer never sees it."""
    if not await codes_on(session):
        raise Conflict("Customer codes are switched off.", code="codes_off")
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if purpose == "check_in":
        _need(run, "accepted", msg="Accept the task before asking for a visit code.")
        waiting = await _open_dependencies(session, run)
        if waiting:
            raise Conflict(
                f"These tasks must be handed over first: {', '.join(waiting)}.",
                code="dependencies_open",
                extra={"tasks": waiting},
            )
    elif purpose == "handover":
        _need(run, "engine_check", msg="The configuration check must pass before the hand over.")
        if not run.last_check_passed:
            raise Conflict("The configuration check has not passed.", code="check_not_passed")
    else:
        raise ValidationFailed("The purpose must be check_in or handover.")
    contacts = await get_sign_off_contacts(session, principal, run.project_id)
    if not contacts:
        raise Conflict(
            "The customer has no contact with an email address. Add one before the visit.",
            code="customer_contact_missing",
        )
    contact = contacts[0]
    recent = await session.scalar(
        select(func.count())
        .select_from(OtpChallenge)
        .where(
            OtpChallenge.run_id == run.id,
            OtpChallenge.purpose == purpose,
            OtpChallenge.created_at > utcnow() - timedelta(hours=1),
        )
    )
    if (recent or 0) >= OTP_MAX_PER_HOUR:
        raise Conflict(
            "Too many codes were requested. Try again in an hour.", code="too_many_codes"
        )
    for old in await session.scalars(
        select(OtpChallenge).where(
            OtpChallenge.run_id == run.id,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
        )
    ):
        old.consumed_at = utcnow()  # a new code replaces the old one
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(8)
    ch = OtpChallenge(
        run_id=run.id,
        purpose=purpose,
        contact_id=contact.id,
        sent_to=_mask(contact.email),
        salt=salt,
        code_hash=_hash(salt, code),
        expires_at=utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    session.add(ch)
    project = await get_project_ref(session, principal, run.project_id)
    n = queue_email(
        session,
        to_address=contact.email,
        template="otp_check_in" if purpose == "check_in" else "otp_handover",
        context={
            "name": contact.full_name,
            "engineer": await _name(session, run.assignee_id),
            "project": project.name,
            "place": project.name,
            "task": run.title,
            "code": code,
            "minutes": OTP_TTL_MINUTES,
        },
        related=("task_run", str(run.id)),
    )
    _log(session, run, principal, f"code_sent_{purpose}", detail={"to": ch.sent_to})
    await record(
        session,
        audit_context(principal),
        action=f"send_{purpose}_code",
        entity_type="task_run",
        entity_id=run.id,
        after={"to": ch.sent_to},
        only_changes=False,
    )
    await session.commit()
    await deliver_now(get_sessionmaker(), [n.id])
    return {"sent_to": ch.sent_to, "expires_at": ch.expires_at, "valid_minutes": OTP_TTL_MINUTES}


async def _consume_code(
    session: AsyncSession, run: TaskRun, purpose: str, code: str
) -> OtpChallenge:
    ch = await session.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.run_id == run.id,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
        )
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if ch is None:
        raise Conflict("Ask the customer for a code first.", code="otp_not_requested")
    if ch.expires_at < utcnow():
        raise Conflict("That code has expired. Ask for a new one.", code="otp_expired")
    if ch.attempts >= OTP_MAX_ATTEMPTS:
        raise Conflict("Too many wrong codes. Ask for a new one.", code="otp_locked")
    if not hmac.compare_digest(ch.code_hash, _hash(ch.salt, code)):
        ch.attempts += 1
        left = OTP_MAX_ATTEMPTS - ch.attempts
        await session.commit()  # the failed try must be remembered
        raise ValidationFailed(
            "That code is not right."
            + (f" {left} tries left." if left else " Ask for a new code."),
            code="otp_invalid",
            extra={"attempts_left": left},
        )
    ch.consumed_at = utcnow()
    return ch


async def check_in(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    code: str | None,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
    lat: float | None,
    lng: float | None,
    accuracy_m: float | None,
) -> TaskRun:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "accepted", msg="Accept the task before you check in.")
    waiting = await _open_dependencies(session, run)
    if waiting:
        raise Conflict(
            f"These tasks must be handed over first: {', '.join(waiting)}.",
            code="dependencies_open",
            extra={"tasks": waiting},
        )
    missing = await _missing(session, run, "check_in")
    if missing:
        raise Conflict(
            "Add the arrival evidence first.",
            code="evidence_missing",
            extra={"evidence_missing": missing},
        )
    _check_location(lat, lng)
    if lat is None or lng is None:
        raise ValidationFailed(
            "Check-in needs the phone's location. Turn on location for this app, step outside "
            "if the signal is weak, and try again.",
            code="location_required",
        )
    cap = _captured(captured_at)
    confirmed = await _confirm(session, run, "check_in", code)
    run.checked_in_at = cap
    ids = await _transition(
        session,
        principal,
        run,
        "check_in",
        "checked_in",
        detail=confirmed,
        client_event_id=client_event_id,
        captured_at=cap,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
    )
    return await _commit_and_send(session, run, ids)


async def add_evidence(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    requirement_index: int,
    client_id: uuid.UUID,
    data: bytes | None,
    filename: str | None,
    text_value: str | None,
    note: str | None,
    captured_at: datetime | None,
    client_ip: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    accuracy_m: float | None = None,
    location_note: str | None = None,
    stamped: bytes | None = None,
    stamped_name: str | None = None,
) -> RunEvidence:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    existing = await session.scalar(
        select(RunEvidence).where(RunEvidence.run_id == run.id, RunEvidence.client_id == client_id)
    )
    if existing:
        return existing  # a resent upload after a dropped connection
    return await _store_evidence(
        session,
        principal,
        run,
        requirement_index=requirement_index,
        client_id=client_id,
        data=data,
        filename=filename,
        text_value=text_value,
        note=note,
        captured_at=captured_at,
        client_ip=client_ip,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
        location_note=location_note,
        stamped=stamped,
        stamped_name=stamped_name,
        via="app",
    )


def _requirement(run: TaskRun, index: int) -> tuple[dict[str, Any], str]:
    if not 0 <= index < len(run.evidence_reqs):
        raise NotFound("There is no such evidence requirement.")
    req = run.evidence_reqs[index]
    stage = req.get("stage", "work")
    if run.state not in EVIDENCE_WINDOW[stage]:
        raise Conflict(
            f"This evidence belongs to the {stage.replace('_', ' ')} part of the visit.",
            code="bad_state",
            extra={"state": run.state},
        )
    return req, stage


async def _parse_summary(run: TaskRun, name: str, data: bytes) -> dict[str, Any]:
    """What an uploaded configuration export contains, shown to the engineer at once: the brand
    found, how many settings could be read, and how many of the task's target settings the
    check can judge from this file."""
    facts = engine.read_export(name, data)
    if facts is None:
        return {
            "readable": False,
            "brand": None,
            "format": None,
            "settings_read": 0,
            "targets_total": len(run.baseline),
            "targets_from_file": 0,
            "message": "Saved. The file could not be read as settings, so the check uses the "
            "values you record.",
        }
    covered = 0
    if run.baseline:
        result = await engine.driver_for(run.device_type).check(
            run.baseline, run.actuals, [engine.ExportFile(name, data)]
        )
        covered = sum(1 for f in result.fields if f.source == "export")
    brand = facts.brand
    return {
        "readable": True,
        "brand": brand,
        "format": facts.shape,
        "settings_read": len(facts.facts),
        "targets_total": len(run.baseline),
        "targets_from_file": covered,
        "message": (
            f"{brand.title() if brand else 'Unknown brand'} export, {len(facts.facts)} settings "
            f"read. {covered} of {len(run.baseline)} target settings are checked from this file."
        ),
    }


async def _store_evidence(
    session: AsyncSession,
    principal: Principal,
    run: TaskRun,
    *,
    requirement_index: int,
    client_id: uuid.UUID,
    data: bytes | None,
    filename: str | None,
    text_value: str | None,
    note: str | None,
    captured_at: datetime | None,
    client_ip: str | None,
    lat: float | None,
    lng: float | None,
    accuracy_m: float | None,
    location_note: str | None,
    stamped: bytes | None,
    stamped_name: str | None,
    via: str,
) -> RunEvidence:
    run_id = run.id
    req, stage = _requirement(run, requirement_index)
    _check_location(lat, lng)
    has_location = lat is not None and lng is not None
    if stage == "check_in" and req["type"] in STAMPABLE and not has_location:
        raise ValidationFailed(
            "The arrival photo needs the phone's location. Turn on location for this app and "
            "take the photo again.",
            code="location_required",
        )
    cap = _captured(captured_at)
    file_id: uuid.UUID | None = None
    stamped_id: uuid.UUID | None = None
    parse: dict[str, Any] | None = None
    text_clean = (text_value or "").strip() or None
    if req["type"] in FILE_PURPOSE:
        if not data:
            raise ValidationFailed(f"Attach a file for: {req['label']}.", code="file_required")
        if req["type"] == "config_export":
            parse = await _parse_summary(run, filename or "export", data)
        ref = await store_upload(
            session,
            principal,
            data=data,
            filename=filename or "evidence",
            purpose=FILE_PURPOSE[req["type"]],
            project_id=run.project_id,
            client_ip=client_ip,
        )
        file_id = ref.id
        if stamped and req["type"] in STAMPABLE:
            sref = await store_upload(
                session,
                principal,
                data=stamped,
                filename=stamped_name or "stamped.jpg",
                purpose="evidence_photo",
                project_id=run.project_id,
                client_ip=client_ip,
            )
            stamped_id = sref.id
        run = await _load(session, principal, run_id)  # store_upload committed
    elif req["type"] == "serial":
        if not text_clean:
            raise ValidationFailed("Type the serial number.", code="text_required")
    elif not (text_clean or note):
        raise ValidationFailed("Write the note.", code="text_required")
    ev = RunEvidence(
        run_id=run.id,
        project_id=run.project_id,
        requirement_index=requirement_index,
        type=req["type"],
        file_id=file_id,
        text_value=text_clean,
        note=note,
        client_id=client_id,
        captured_at=cap,
        uploaded_by=principal.user_id,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
        location_note=None
        if has_location
        else ((location_note or "").strip()[:200] or "Location not available"),
        stamped_file_id=stamped_id,
        parse=parse,
        via=via,
    )
    session.add(ev)
    _log(
        session,
        run,
        principal,
        "evidence_added",
        captured_at=cap,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
        detail={
            "requirement": requirement_index,
            "type": req["type"],
            "label": req["label"],
            "stage": stage,
            **({"via": via} if via != "app" else {}),
        },
    )
    await session.commit()
    await session.refresh(ev)
    return ev


async def finish_prechecks(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
) -> TaskRun:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "checked_in", msg="Check in before the prechecks.")
    missing = await _missing(session, run, "prechecks")
    if missing:
        raise Conflict(
            "Confirm the backup and the access first.",
            code="evidence_missing",
            extra={"evidence_missing": missing},
        )
    cap = _captured(captured_at)
    ids = await _transition(
        session,
        principal,
        run,
        "prechecks_done",
        "prechecks_done",
        client_event_id=client_event_id,
        captured_at=cap,
    )
    return await _commit_and_send(session, run, ids)


async def complete_step(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    index: int,
    *,
    note: str | None,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
) -> TaskRun:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "prechecks_done", msg="Finish the prechecks before the configuration steps.")
    done = sum(1 for s in run.steps if s["done"])
    if not 0 <= index < len(run.steps):
        raise NotFound("There is no such step.")
    if run.steps[index]["done"]:
        return run  # already done: a double tap or a resend, not a mistake
    if index != done:
        raise Conflict(
            f"Steps go in order. Do step {done + 1} next.",
            code="step_order",
            extra={"next_step": done},
        )
    cap = _captured(captured_at)
    steps = [dict(s) for s in run.steps]
    steps[index]["done"], steps[index]["done_at"] = True, cap.isoformat()
    run.steps = steps
    _log(
        session,
        run,
        principal,
        "step_done",
        client_event_id=client_event_id,
        captured_at=cap,
        detail={"step": index, "text": steps[index]["text"], "note": note},
    )
    await session.commit()
    await session.refresh(run)
    return run


async def record_actuals(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    values: dict[str, str],
    *,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
) -> TaskRun:
    """What the engineer found or set for each target setting, as seen on the device."""
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "prechecks_done", "configured", msg="Record values while configuring.")
    keys = {f["key"] for f in run.baseline}
    unknown = sorted(set(values) - keys)
    if unknown:
        raise ValidationFailed(
            f"These settings are not in the target: {', '.join(unknown)}.", code="unknown_setting"
        )
    cap = _captured(captured_at)
    actuals = dict(run.actuals)
    for k, v in values.items():
        actuals[k] = {"value": str(v).strip()[:200], "at": cap.isoformat()}
    run.actuals = actuals
    _log(
        session,
        run,
        principal,
        "values_recorded",
        client_event_id=client_event_id,
        captured_at=cap,
        detail={"settings": sorted(values)},
    )
    await session.commit()
    await session.refresh(run)
    return run


async def mark_configured(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
) -> TaskRun:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "prechecks_done", msg="Finish the prechecks first.")
    open_steps = [s["text"] for s in run.steps if not s["done"]]
    unrecorded = [f["label"] for f in run.baseline if f["key"] not in run.actuals]
    if open_steps or unrecorded:
        raise Conflict(
            "Finish every step and record every target setting first.",
            code="work_incomplete",
            extra={"steps_left": open_steps, "values_missing": unrecorded},
        )
    cap = _captured(captured_at)
    ids = await _transition(
        session,
        principal,
        run,
        "configured",
        "configured",
        client_event_id=client_event_id,
        captured_at=cap,
    )
    return await _commit_and_send(session, run, ids)


async def submit_evidence(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
) -> TaskRun:
    """Evidence complete: the engine check runs at once. A failed critical or major setting sends
    the task back to configured with the deviations listed."""
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "configured", msg="Mark the work configured before sending the evidence.")
    missing = await _missing(session, run, "work")
    if missing:
        raise Conflict(
            "Add all required evidence first.",
            code="evidence_missing",
            extra={"evidence_missing": missing},
        )
    cap = _captured(captured_at)
    _log(
        session,
        run,
        principal,
        "evidence_uploaded",
        to_state="evidence_uploaded",
        client_event_id=client_event_id,
        captured_at=cap,
    )
    # Only exports from the work itself: the export taken before any change (the rollback
    # point) shows the old configuration and must never pass or fail the check.
    work_reqs = {i for i, r in enumerate(run.evidence_reqs) if r.get("stage", "work") == "work"}
    exports: list[engine.ExportFile] = []
    for ev in await session.scalars(
        select(RunEvidence)
        .where(
            RunEvidence.run_id == run.id,
            RunEvidence.type == "config_export",
            RunEvidence.file_id.is_not(None),
        )
        .order_by(RunEvidence.created_at)
    ):
        if ev.requirement_index not in work_reqs:
            continue
        ref, data = await read_file_system(session, ev.file_id)  # type: ignore[arg-type]
        exports.append(engine.ExportFile(ref.original_name, data))
    result = await engine.driver_for(run.device_type).check(run.baseline, run.actuals, exports)
    attempt = 1 + int(
        await session.scalar(
            select(func.count()).select_from(RunCheck).where(RunCheck.run_id == run.id)
        )
        or 0
    )
    critical = sum(1 for f in result.deviations if f.severity == "critical")
    session.add(
        RunCheck(
            run_id=run.id,
            project_id=run.project_id,
            attempt=attempt,
            driver=result.driver,
            passed=result.passed,
            deviations=len(result.deviations),
            critical_open=critical,
            result=result.as_dict(),
        )
    )
    run.last_check_passed = result.passed
    summary = result.as_dict()
    outbox.publish(
        session,
        DomainEvent(
            event_type=CHECK_COMPLETED,
            aggregate_type="task_run",
            aggregate_id=str(run.id),
            actor_id=principal.user_id,
            payload={
                "project_id": str(run.project_id),
                "run_id": str(run.id),
                "task_ref": run.task_ref,
                "device": run.asset,
                "attempt": attempt,
                "passed": result.passed,
                "driver": result.driver,
                "fields": summary["fields"],
            },
        ),
    )
    _log(
        session,
        run,
        None,
        "engine_check",
        to_state="engine_check",
        detail={
            "attempt": attempt,
            "passed": result.passed,
            "deviations": summary["deviations"],
            "not_checked": summary["not_checked"],
        },
    )
    note = None
    if not result.passed:
        run.rework_count += 1
        failed = "; ".join(
            f"{f.label}: {f.reason}" for f in result.deviations if f.severity in engine.BLOCKING
        )
        _log(
            session,
            run,
            None,
            "engine_mismatch",
            to_state="configured",
            detail={"attempt": attempt},
        )
        note = f"The configuration check failed: {failed}"
    project = await get_project_ref(session, principal, run.project_id)
    ids = await _announce(session, principal, run, project, note)
    assignee = await get_user_summary(session, run.assignee_id)
    if not result.passed and assignee is not None:
        n = await queue_email_to_user(
            session,
            user_id=assignee.id,
            email=assignee.email,
            template="run_returned",
            context={
                "name": assignee.full_name,
                "task": run.title,
                "project": project.name,
                "reason": note or "",
            },
            dedupe_key=f"returned:{run.id}:{attempt}",
        )
        ids.append(n.id)
    return await _commit_and_send(session, run, ids)


async def hand_over(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    code: str | None,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
    lat: float | None,
    lng: float | None,
    accuracy_m: float | None,
) -> TaskRun:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, "engine_check", msg="The configuration check must pass before the hand over.")
    if not run.last_check_passed:
        raise Conflict("The configuration check has not passed.", code="check_not_passed")
    _check_location(lat, lng)
    cap = _captured(captured_at)
    confirmed = await _confirm(session, run, "handover", code)
    run.handed_over_at = cap
    ids = await _transition(
        session,
        principal,
        run,
        "hand_over",
        "verifier_review",
        detail=confirmed,
        client_event_id=client_event_id,
        captured_at=cap,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
    )
    project = await get_project_ref(session, principal, run.project_id)
    last = await session.scalar(
        select(RunCheck).where(RunCheck.run_id == run.id).order_by(RunCheck.attempt.desc()).limit(1)
    )
    eng = await _name(session, run.assignee_id)
    for m in await get_project_members(session, principal, run.project_id):
        if m.project_role == "technical_lead" and m.user_id != run.assignee_id:
            u = await get_user_summary(session, m.user_id)
            if u and u.is_active:
                n = await queue_email_to_user(
                    session,
                    user_id=u.id,
                    email=u.email,
                    template="verify_requested",
                    context={
                        "name": u.full_name,
                        "engineer": eng,
                        "task": run.title,
                        "project": project.name,
                        "not_checked": last.result.get("not_checked", 0) if last else 0,
                    },
                    dedupe_key=f"verify:{run.id}:{run.rework_count}:{u.id}",
                )
                ids.append(n.id)
    return await _commit_and_send(session, run, ids)


async def block(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    reason: str,
    client_event_id: uuid.UUID | None,
    captured_at: datetime | None,
) -> TaskRun:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    if await _seen(session, run.id, client_event_id):
        return run
    _need(run, *BLOCKABLE, msg="Only a task in progress can be blocked.")
    cap = _captured(captured_at)
    run.blocked_from, run.block_reason = run.state, reason
    ids = await _transition(
        session,
        principal,
        run,
        "block",
        "blocked",
        note=f"Reason: {reason}",
        detail={"reason": reason},
        client_event_id=client_event_id,
        captured_at=cap,
    )
    return await _commit_and_send(session, run, ids)


# ------------------------------------------------------------------ manager and verifier actions


async def unblock(
    session: AsyncSession, principal: Principal, run_id: uuid.UUID, *, note: str
) -> TaskRun:
    principal.require(P.FIELD_MANAGE)
    run = await _load(session, principal, run_id)
    if run.state != "blocked" or not run.blocked_from:
        raise Conflict("This task is not blocked.", code="bad_state")
    back = run.blocked_from
    run.blocked_from = run.block_reason = None
    ids = await _transition(
        session, principal, run, "unblock", back, note=note, detail={"note": note}
    )
    await record(
        session,
        audit_context(principal),
        action="unblock_run",
        entity_type="task_run",
        entity_id=run.id,
        after={"to": back, "note": note},
        only_changes=False,
    )
    return await _commit_and_send(session, run, ids)


async def reassign(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    assignee_id: uuid.UUID,
    reason: str,
) -> TaskRun:
    principal.require(P.FIELD_MANAGE)
    run = await _load(session, principal, run_id)
    if run.state not in ("assigned", "accepted", "blocked"):
        raise Conflict(
            "A task that has started on site cannot be handed to someone else.", code="bad_state"
        )
    if run.state == "blocked" and run.blocked_from not in ("accepted",):
        raise Conflict("Work has started on site; unblock it instead.", code="bad_state")
    u = await get_user_summary(session, assignee_id)
    if u is None or not u.is_active or Role.FIELD_ENGINEER not in u.roles:
        raise ValidationFailed("Choose an active field engineer.")
    members = await get_project_members(session, principal, run.project_id)
    if assignee_id not in {m.user_id for m in members}:
        raise ValidationFailed("Add this engineer to the project team first.")
    old = run.assignee_id
    run.assignee_id = assignee_id
    search_index(session, task_doc(run), principal.user_id)
    run.blocked_from = run.block_reason = None
    ids = await _transition(
        session,
        principal,
        run,
        "reassign",
        "assigned",
        note=f"Reassigned: {reason}",
        detail={"from": str(old), "to": str(assignee_id), "reason": reason},
    )
    project = await get_project_ref(session, principal, run.project_id)
    n = await queue_email_to_user(
        session,
        user_id=assignee_id,
        email=u.email,
        template="task_assigned",
        context={
            "name": u.full_name,
            "count": 1,
            "project": project.name,
            "first_start": to_ist(run.planned_start).strftime("%d %b %Y, %H:%M"),
        },
        dedupe_key=f"reassign:{run.id}:{assignee_id}:{run.version}",
    )
    ids.append(n.id)
    await record(
        session,
        audit_context(principal),
        action="reassign_run",
        entity_type="task_run",
        entity_id=run.id,
        before={"assignee": str(old)},
        after={"assignee": str(assignee_id), "reason": reason},
    )
    return await _commit_and_send(session, run, ids)


async def decide(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    approve: bool,
    reason: str | None,
) -> TaskRun:
    """The verifier closes the task or sends it back to configured. The engineer who did the
    work can never verify it."""
    principal.require(P.FIELD_VERIFY)
    run = await _load(session, principal, run_id)
    _need(run, "verifier_review", msg="Only handed over work can be verified.")
    ensure_different_people(run.assignee_id, principal.user_id, "task")
    project = await get_project_ref(session, principal, run.project_id)
    if approve:
        run.closed_at, run.verified_by = utcnow(), principal.user_id
        ids = await _transition(
            session, principal, run, "verify", "closed", detail={"reason": reason}
        )
    else:
        if not reason or len(reason.strip()) < 5:
            raise ValidationFailed("Say what must be fixed.", code="reason_required")
        run.rework_count += 1
        ids = await _transition(
            session,
            principal,
            run,
            "verifier_reject",
            "configured",
            note=f"Sent back by the verifier: {reason}",
            detail={"reason": reason},
        )
        assignee = await get_user_summary(session, run.assignee_id)
        if assignee:
            n = await queue_email_to_user(
                session,
                user_id=assignee.id,
                email=assignee.email,
                template="run_returned",
                context={
                    "name": assignee.full_name,
                    "task": run.title,
                    "project": project.name,
                    "reason": reason,
                },
                dedupe_key=f"rejected:{run.id}:{run.rework_count}",
            )
            ids.append(n.id)
    await record(
        session,
        audit_context(principal),
        action="verify_run" if approve else "reject_run",
        entity_type="task_run",
        entity_id=run.id,
        after={"state": run.state, "reason": reason},
        only_changes=False,
    )
    return await _commit_and_send(session, run, ids)


# ------------------------------------------------------------------ guidance for the phone


def next_action(run: TaskRun, have: set[int], waiting: list[str], codes: bool = True) -> str:
    """One plain sentence: what the engineer (or the office) should do next on this task."""

    def missing(stage: str) -> list[str]:
        return [
            r["label"]
            for i, r in enumerate(run.evidence_reqs)
            if r.get("stage", "work") == stage and r.get("required", True) and i not in have
        ]

    s = run.state
    if s == "assigned":
        return "Accept the task."
    if s == "accepted":
        if waiting:
            return f"Wait until {', '.join(waiting)} is handed over."
        if m := missing("check_in"):
            return f"Add: {m[0]}."
        return (
            "Send the visit code to the customer and enter it to check in."
            if codes
            else "Check in."
        )
    if s == "checked_in":
        m = missing("prechecks")
        return f"Add: {m[0]}." if m else "Mark the prechecks done."
    if s == "prechecks_done":
        step = next((i for i, x in enumerate(run.steps) if not x["done"]), None)
        if step is not None:
            return f"Step {step + 1}: {run.steps[step]['text']}"
        unrecorded = [f["label"] for f in run.baseline if f["key"] not in run.actuals]
        if unrecorded:
            return f"Record the value for: {unrecorded[0]}."
        return "Mark the work configured."
    if s == "configured":
        m = missing("work")
        todo = f"add: {m[0]}." if m else "send the evidence for the check."
        if run.rework_count:
            return f"Fix what was sent back, then {todo}"
        return todo[0].upper() + todo[1:]
    if s == "evidence_uploaded":
        return "The configuration check is running."
    if s == "engine_check":
        return (
            "Send the hand over code to the customer and enter it."
            if codes
            else "Show the customer the finished work, then hand over."
        )
    if s == "verifier_review":
        return "Waiting for a verifier."
    if s == "closed":
        return "Done. Nothing more to do."
    return f"Blocked: {run.block_reason}. The project manager decides what happens next."


# ------------------------------------------------------------------ configuration before and after

# Keys and lines that may hold a secret are never shown in a comparison.
_SECRET = re.compile(r"pass|secret|psk|key|community|token|hash|cert|private|credential", re.I)
MAX_DIFF_ROWS = 300


def _shown(key: str, value: str | None) -> str | None:
    if value is None:
        return None
    return "(hidden)" if _SECRET.search(key) else value[:300]


def _latest_for(evidence: list[RunEvidence], indexes: set[int]) -> RunEvidence | None:
    hits = [e for e in evidence if e.requirement_index in indexes and e.file_id is not None]
    return max(hits, key=lambda e: e.created_at) if hits else None


async def config_diff(
    session: AsyncSession, principal: Principal, run_id: uuid.UUID
) -> dict[str, Any]:
    """The export taken before any change against the latest export from the work: the rollback
    point and what the work changed. Settings are compared when both files can be read as
    settings; otherwise lines are."""
    run = await _load(session, principal, run_id)
    reqs = run.evidence_reqs
    before_idx = {
        i
        for i, r in enumerate(reqs)
        if r.get("stage") == "prechecks" and r["type"] == "config_export"
    }
    after_idx = {
        i
        for i, r in enumerate(reqs)
        if r.get("stage", "work") == "work" and r["type"] == "config_export"
    }
    if not before_idx or not after_idx:
        return {
            "available": False,
            "reason": "This task does not take a configuration export before and after the work.",
        }
    evidence = list(await session.scalars(select(RunEvidence).where(RunEvidence.run_id == run.id)))
    before, after = _latest_for(evidence, before_idx), _latest_for(evidence, after_idx)
    if before is None or after is None:
        return {
            "available": False,
            "reason": "Waiting for "
            + ("the export before the work" if before is None else "the export after the work")
            + ".",
        }
    b_ref, b_data = await read_file(session, principal, before.file_id)  # type: ignore[arg-type]
    a_ref, a_data = await read_file(session, principal, after.file_id)  # type: ignore[arg-type]
    out: dict[str, Any] = {
        "available": True,
        "before_file": b_ref.original_name,
        "after_file": a_ref.original_name,
        "before_at": before.created_at,
        "after_at": after.created_at,
    }
    fb, fa = (
        engine.read_export(b_ref.original_name, b_data),
        engine.read_export(a_ref.original_name, a_data),
    )
    changes: list[dict[str, Any]] = []
    if fb and fa and fb.facts and fa.facts:
        unchanged = 0
        for key in sorted(set(fb.facts) | set(fa.facts)):
            old, new = fb.facts.get(key), fa.facts.get(key)
            if old == new:
                unchanged += 1
                continue
            kind = "added" if old is None else "removed" if new is None else "changed"
            changes.append(
                {"key": key, "before": _shown(key, old), "after": _shown(key, new), "change": kind}
            )
        out.update(method="settings", brand=fa.brand or fb.brand, unchanged=unchanged)
    else:

        def lines(data: bytes) -> list[str]:
            text = data.decode("utf-8", errors="replace")
            return [ln.rstrip() for ln in text.splitlines() if ln.strip()]

        old_lines, new_lines = lines(b_data), lines(a_data)
        matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        unchanged = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                unchanged += i2 - i1
                continue
            for k in range(i1, i2):
                ln = old_lines[k]
                changes.append(
                    {
                        "key": f"line {k + 1}",
                        "before": "(hidden)" if _SECRET.search(ln) else ln[:300],
                        "after": None,
                        "change": "removed",
                    }
                )
            for k in range(j1, j2):
                ln = new_lines[k]
                changes.append(
                    {
                        "key": f"line {k + 1}",
                        "before": None,
                        "after": "(hidden)" if _SECRET.search(ln) else ln[:300],
                        "change": "added",
                    }
                )
        out.update(method="lines", brand=None, unchanged=unchanged)
    out["truncated"] = len(changes) > MAX_DIFF_ROWS
    out["changes"] = changes[:MAX_DIFF_ROWS]
    return out


# ------------------------------------------------------------------ single-use upload links


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _qr_svg(text: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    return str(img.to_string(encoding="unicode"))


async def create_upload_link(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    requirement_index: int,
    base_url: str,
) -> dict[str, Any]:
    """A link (and QR code) that lets one configuration export for this task be uploaded from
    any browser, once, within 15 minutes. Making a new link cancels the previous unused one."""
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    req, _stage = _requirement(run, requirement_index)
    if req["type"] != "config_export":
        raise ValidationFailed(
            "Upload links are only for configuration exports.", code="not_an_export"
        )
    now = utcnow()
    await session.execute(
        update(FieldUploadLink)
        .where(
            FieldUploadLink.run_id == run.id,
            FieldUploadLink.requirement_index == requirement_index,
            FieldUploadLink.used_at.is_(None),
            FieldUploadLink.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = secrets.token_urlsafe(24)
    link = FieldUploadLink(
        run_id=run.id,
        project_id=run.project_id,
        requirement_index=requirement_index,
        token_hash=_token_hash(token),
        created_by=principal.user_id,
        expires_at=now + timedelta(minutes=UPLOAD_LINK_MINUTES),
    )
    session.add(link)
    await session.flush()
    _log(
        session,
        run,
        principal,
        "upload_link_made",
        detail={"requirement": requirement_index, "label": req["label"]},
    )
    await record(
        session,
        audit_context(principal),
        action="upload_link_created",
        entity_type="task_run",
        entity_id=str(run.id),
        after={"requirement": requirement_index, "expires_at": link.expires_at.isoformat()},
        only_changes=False,
    )
    await session.commit()
    path = f"/upload/{token}"
    url = base_url.rstrip("/") + path
    return {
        "url": url,
        "path": path,
        "expires_at": link.expires_at,
        "valid_minutes": UPLOAD_LINK_MINUTES,
        "qr_svg": _qr_svg(url),
    }


async def _usable_link(session: AsyncSession, token: str) -> FieldUploadLink:
    link = await session.scalar(
        select(FieldUploadLink).where(FieldUploadLink.token_hash == _token_hash(token))
    )
    if link is None or link.revoked_at is not None:
        raise NotFound(
            "This upload link is not valid. Ask the engineer for a new one.", code="link_invalid"
        )
    if link.used_at is not None:
        raise Conflict(
            "This upload link was already used. Ask the engineer for a new one.", code="link_used"
        )
    if link.expires_at <= utcnow():
        raise Conflict(
            "This upload link has expired. Ask the engineer for a new one.", code="link_expired"
        )
    return link


async def upload_link_info(session: AsyncSession, token: str) -> dict[str, Any]:
    """What the person holding the link sees: the task and what to upload. No customer contacts,
    no prices, no other evidence."""
    link = await _usable_link(session, token)
    run = await session.get(TaskRun, link.run_id)
    if run is None:  # pragma: no cover (cascade delete)
        raise NotFound("This upload link is not valid.", code="link_invalid")
    req = run.evidence_reqs[link.requirement_index]
    names = await project_briefs(
        session,
        await _link_principal(session, link, None),
        {run.project_id},
    )
    brief = names.get(run.project_id) or {}
    return {
        "task_ref": run.task_ref,
        "title": run.title,
        "asset": run.asset,
        "label": req["label"],
        "project": brief.get("name", ""),
        "expires_at": link.expires_at,
        "accept": ".txt,.conf,.cfg,.json,.zip,.xml,.exp",
    }


async def _link_principal(
    session: AsyncSession, link: FieldUploadLink, ip: str | None
) -> Principal:
    p = await principal_for_link(
        session,
        link.created_by,
        link_id=link.id,
        permissions=frozenset(
            {P.FIELD_READ, P.FIELD_WORK, P.FILE_UPLOAD, P.PROJECT_READ, P.CUSTOMER_READ}
        ),
        ip=ip,
    )
    if p is None:
        raise NotFound("This upload link is not valid.", code="link_invalid")
    return p


async def upload_via_link(
    session: AsyncSession,
    token: str,
    *,
    data: bytes,
    filename: str,
    client_ip: str | None,
) -> dict[str, Any]:
    """Store the export as the engineer's evidence. The link is claimed first, in its own
    statement, so two uploads at the same moment cannot both use it; if the file is refused
    (virus, wrong type) the claim is released and the link can be tried again until it expires."""
    link = await _usable_link(session, token)
    link_id = link.id
    claimed = await session.scalar(
        update(FieldUploadLink)
        .where(FieldUploadLink.id == link_id, FieldUploadLink.used_at.is_(None))
        .values(used_at=utcnow(), used_ip=(client_ip or "")[:64] or None)
        .returning(FieldUploadLink.id)
    )
    await session.commit()
    if claimed is None:
        raise Conflict(
            "This upload link was already used. Ask the engineer for a new one.", code="link_used"
        )
    try:
        link = await session.get(FieldUploadLink, link_id)  # type: ignore[assignment]
        principal = await _link_principal(session, link, client_ip)
        run = await _load(session, principal, link.run_id)
        if run.assignee_id != link.created_by:
            raise Conflict("This task was handed to another engineer.", code="link_invalid")
        ev = await _store_evidence(
            session,
            principal,
            run,
            requirement_index=link.requirement_index,
            client_id=link_id,
            data=data,
            filename=filename,
            text_value=None,
            note=None,
            captured_at=None,
            client_ip=client_ip,
            lat=None,
            lng=None,
            accuracy_m=None,
            location_note="Uploaded through a link from another device",
            stamped=None,
            stamped_name=None,
            via="link",
        )
    except Exception:
        await session.rollback()
        await session.execute(
            update(FieldUploadLink)
            .where(FieldUploadLink.id == link_id)
            .values(used_at=None, used_ip=None)
        )
        await session.commit()
        raise
    await session.execute(
        update(FieldUploadLink).where(FieldUploadLink.id == link_id).values(evidence_id=ev.id)
    )
    await record(
        session,
        audit_context(principal),
        action="upload_link_used",
        entity_type="task_run",
        entity_id=str(ev.run_id),
        after={"evidence": str(ev.id), "file": filename[:120], "ip": client_ip},
        only_changes=False,
    )
    await session.commit()
    return {"received": True, "file_name": filename[:200], "parse": ev.parse}


# ------------------------------------------------------------------ phones and workload


async def report_device_status(
    session: AsyncSession,
    principal: Principal,
    *,
    pending: int,
    failed: int,
    oldest_pending_at: datetime | None,
    last_sync_at: datetime | None,
    app_version: str | None,
    platform: str | None,
) -> None:
    """The phone says how much saved work it holds. Sent on every sync and when the app opens."""
    principal.require(P.FIELD_WORK)
    row = await session.get(FieldDeviceStatus, principal.user_id)
    if row is None:
        row = FieldDeviceStatus(user_id=principal.user_id, reported_at=utcnow())
        session.add(row)
    now = utcnow()
    row.pending, row.failed = pending, failed
    row.oldest_pending_at = min(oldest_pending_at, now) if oldest_pending_at else None
    row.last_sync_at = min(last_sync_at, now) if last_sync_at else row.last_sync_at
    row.reported_at = now
    row.app_version, row.platform = app_version, platform
    await session.commit()


def _engineer_state(status: FieldDeviceStatus | None, now: datetime) -> tuple[str, str]:
    """synced, waiting (unsent work on the phone), refused (the server refused saved work),
    quiet (no word for a while) or never (the app has not reported yet)."""
    if status is None:
        return "never", "The app has not reported from this engineer's phone yet."
    seen = to_ist(status.reported_at).strftime("%d %b %H:%M")
    last = to_ist(status.last_sync_at).strftime("%d %b %H:%M") if status.last_sync_at else "never"
    if status.failed:
        return "refused", f"{status.failed} saved item(s) refused by the server, last seen {seen}"
    quiet = now - status.reported_at > timedelta(minutes=QUIET_AFTER_MINUTES)
    if status.pending:
        where = "offline" if quiet else "online"
        waiting = f"{status.pending} item(s) waiting on the phone"
        return "waiting", f"{where}, {waiting}, last sync {last}"
    if quiet:
        return "quiet", f"nothing waiting on the phone, last seen {seen}"
    return "synced", f"online, everything sent, last sync {last}"


async def engineer_statuses(session: AsyncSession, principal: Principal) -> list[dict[str, Any]]:
    """Every field engineer: open work, and whether their phone holds unsent work. For the
    Director and project managers, so a quiet task is not mistaken for a stuck one."""
    if not (principal.has(P.FIELD_MANAGE) or principal.has(P.DASHBOARD_READ)):
        raise Forbidden()
    engineers = await users_with_role(session, Role.FIELD_ENGINEER)
    ids = [e.id for e in engineers]
    if not ids:
        return []
    statuses = {
        s.user_id: s
        for s in await session.scalars(
            select(FieldDeviceStatus).where(FieldDeviceStatus.user_id.in_(ids))
        )
    }
    counts: dict[uuid.UUID, dict[str, int]] = {i: {"open": 0, "now": 0, "blocked": 0} for i in ids}
    for uid, state, n in (
        await session.execute(
            select(TaskRun.assignee_id, TaskRun.state, func.count())
            .where(TaskRun.assignee_id.in_(ids), TaskRun.state != "closed")
            .group_by(TaskRun.assignee_id, TaskRun.state)
        )
    ).all():
        c = counts[uid]
        c["open"] += int(n)
        if state in ("checked_in", "prechecks_done", "configured", "evidence_uploaded"):
            c["now"] += int(n)
        if state == "blocked":
            c["blocked"] += int(n)
    activity = dict(
        (
            await session.execute(
                select(RunEvent.actor_id, func.max(RunEvent.at))
                .where(RunEvent.actor_id.in_(ids))
                .group_by(RunEvent.actor_id)
            )
        ).all()
    )
    now = utcnow()
    out: list[dict[str, Any]] = []
    for e in engineers:
        st = statuses.get(e.id)
        state, summary = _engineer_state(st, now)
        c = counts[e.id]
        out.append(
            {
                "user_id": e.id,
                "full_name": e.full_name,
                "open_tasks": c["open"],
                "working_now": c["now"],
                "blocked": c["blocked"],
                "pending": st.pending if st else 0,
                "failed": st.failed if st else 0,
                "oldest_pending_at": st.oldest_pending_at if st else None,
                "last_sync_at": st.last_sync_at if st else None,
                "last_seen_at": st.reported_at if st else None,
                "last_activity_at": activity.get(e.id),
                "state": state,
                "summary": summary,
            }
        )
    order = {"refused": 0, "waiting": 1, "quiet": 2, "never": 3, "synced": 4}
    out.sort(key=lambda r: (order[r["state"]], -r["open_tasks"], r["full_name"]))
    return out


async def workload(
    session: AsyncSession, principal: Principal, days: int = 14
) -> list[dict[str, Any]]:
    """For the project manager: each engineer's planned hours per day for the next two weeks,
    with open, blocked and overdue tasks, from the tasks in the field."""
    principal.require(P.FIELD_MANAGE)
    from app.core.timeutil import today_ist

    engineers = await users_with_role(session, Role.FIELD_ENGINEER)
    ids = [e.id for e in engineers]
    if not ids:
        return []
    start = today_ist()
    horizon = [start + timedelta(days=i) for i in range(days)]
    runs = list(
        await session.scalars(
            select(TaskRun).where(TaskRun.assignee_id.in_(ids), TaskRun.state != "closed")
        )
    )
    now = utcnow()
    out: list[dict[str, Any]] = []
    for e in engineers:
        mine = [r for r in runs if r.assignee_id == e.id]
        per_day: dict[date, list[float]] = {d: [] for d in horizon}
        for r in mine:
            d = to_ist(r.planned_start).date()
            if d in per_day:
                hours = max((r.planned_end - r.planned_start).total_seconds() / 3600, 0.0)
                per_day[d].append(min(hours, 10.0))
        out.append(
            {
                "user_id": e.id,
                "full_name": e.full_name,
                "open_tasks": len(mine),
                "blocked": sum(1 for r in mine if r.state == "blocked"),
                "overdue": sum(
                    1
                    for r in mine
                    if r.planned_end < now and r.state not in ("verifier_review", "closed")
                ),
                "hours_next_14_days": round(sum(sum(v) for v in per_day.values()), 1),
                "days": [
                    {"day": d.isoformat(), "tasks": len(v), "hours": round(sum(v), 1)}
                    for d, v in per_day.items()
                ],
            }
        )
    out.sort(key=lambda r: (-r["hours_next_14_days"], r["full_name"]))
    return out
