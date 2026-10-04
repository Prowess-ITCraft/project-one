"""Field work: the gated state machine for a task in the field (ADR 0015).

    assigned -> accepted -> checked_in -> prechecks_done -> configured -> evidence_uploaded
             -> engine_check -> verifier_review -> closed

- Check-in needs the customer's one-time code, a site photo and every dependency handed over.
- Prechecks need backup and access confirmed with evidence.
- Configured needs every step ticked in order and a value recorded for every target setting.
- Evidence uploaded needs every required item; the engine check then runs at once. A failed
  critical or major setting sends the task back to configured.
- Hand over needs the customer's second code and a passed check; the task goes to a verifier.
- The verifier (never the engineer who did the work) closes it or sends it back to configured.

Nothing can be skipped. Every action is recorded with who, when and where, and every state
change notifies the customer's sign-off contact, the Directors and the project manager.
Offline work arrives later with `client_event_id` and `captured_at`, so repeats are harmless.
Field work never carries prices.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
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
    OtpChallenge,
    RunCheck,
    RunEvent,
    RunEvidence,
    TaskRun,
)
from app.modules.files.contracts import read_file_system, store_upload
from app.modules.identity.contracts import (
    P,
    Principal,
    Role,
    audit_context,
    ensure_different_people,
    get_user_summary,
    users_with_role,
)
from app.modules.notifications.contracts import deliver_now, queue_email, queue_email_to_user
from app.modules.planning.contracts import get_baselined_plan

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
    backup = (
        {"type": "screenshot", "label": "Backup of the current configuration", "required": True}
        if device_type in NETWORK_DEVICES
        else {
            "type": "note",
            "label": "Backup confirmed: who took it and where it is",
            "required": True,
        }
    )
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
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, after: int, limit: int = 100
) -> list[RunEvent]:
    """The live feed: every event after the cursor `after` (the last `seq` the client saw)."""
    principal.require(P.FIELD_READ)
    await get_project_ref(session, principal, project_id)
    stmt = (
        select(RunEvent)
        .where(RunEvent.project_id == project_id, RunEvent.seq > after)
        .order_by(RunEvent.seq)
        .limit(min(limit, 500))
    )
    if not (principal.has(P.FIELD_MANAGE) or principal.has(P.FIELD_VERIFY)):
        mine = select(TaskRun.id).where(
            TaskRun.project_id == project_id, TaskRun.assignee_id == principal.user_id
        )
        stmt = stmt.where(RunEvent.run_id.in_(mine))
    return list(await session.scalars(stmt))


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


async def request_code(
    session: AsyncSession,
    principal: Principal,
    run_id: uuid.UUID,
    purpose: str,
) -> dict[str, Any]:
    """Send a one-time code to the customer's sign-off contact. The engineer never sees it."""
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
    code: str,
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
    cap = _captured(captured_at)
    ch = await _consume_code(session, run, "check_in", code)
    run.checked_in_at = cap
    ids = await _transition(
        session,
        principal,
        run,
        "check_in",
        "checked_in",
        detail={"confirmed_by_contact": str(ch.contact_id)},
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
) -> RunEvidence:
    run = await _load(session, principal, run_id)
    _mine(principal, run)
    existing = await session.scalar(
        select(RunEvidence).where(RunEvidence.run_id == run.id, RunEvidence.client_id == client_id)
    )
    if existing:
        return existing  # a resent upload after a dropped connection
    if not 0 <= requirement_index < len(run.evidence_reqs):
        raise NotFound("There is no such evidence requirement.")
    req = run.evidence_reqs[requirement_index]
    stage = req.get("stage", "work")
    if run.state not in EVIDENCE_WINDOW[stage]:
        raise Conflict(
            f"This evidence belongs to the {stage.replace('_', ' ')} part of the visit.",
            code="bad_state",
            extra={"state": run.state},
        )
    cap = _captured(captured_at)
    file_id: uuid.UUID | None = None
    text_clean = (text_value or "").strip() or None
    if req["type"] in FILE_PURPOSE:
        if not data:
            raise ValidationFailed(f"Attach a file for: {req['label']}.", code="file_required")
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
    )
    session.add(ev)
    _log(
        session,
        run,
        principal,
        "evidence_added",
        captured_at=cap,
        detail={
            "requirement": requirement_index,
            "type": req["type"],
            "label": req["label"],
            "stage": stage,
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
    exports: list[engine.ExportFile] = []
    for ev in await session.scalars(
        select(RunEvidence).where(
            RunEvidence.run_id == run.id,
            RunEvidence.type == "config_export",
            RunEvidence.file_id.is_not(None),
        )
    ):
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
    code: str,
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
    ch = await _consume_code(session, run, "handover", code)
    run.handed_over_at = cap
    ids = await _transition(
        session,
        principal,
        run,
        "hand_over",
        "verifier_review",
        detail={"confirmed_by_contact": str(ch.contact_id)},
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


def next_action(run: TaskRun, have: set[int], waiting: list[str]) -> str:
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
        return "Send the visit code to the customer and enter it to check in."
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
        return "Send the hand over code to the customer and enter it."
    if s == "verifier_review":
        return "Waiting for a verifier."
    if s == "closed":
        return "Done. Nothing more to do."
    return f"Blocked: {run.block_reason}. The project manager decides what happens next."
