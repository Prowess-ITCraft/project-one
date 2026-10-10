from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session, get_sessionmaker
from app.core.documents import rendered
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.core.ratelimit import Limit, check
from app.modules.fieldops import render, service
from app.modules.fieldops.schemas import (
    BlockIn,
    CheckOut,
    ClientIn,
    CodeIn,
    CodeSentOut,
    ConfigDiffOut,
    DecisionIn,
    DeviceStatusIn,
    EngineerStatusOut,
    EventOut,
    EvidenceOut,
    LocatedIn,
    MyRunOut,
    NoteIn,
    ProjectBriefOut,
    ReassignIn,
    RunDetailOut,
    RunOut,
    StepIn,
    SummaryOut,
    UploadLinkDoneOut,
    UploadLinkIn,
    UploadLinkInfoOut,
    UploadLinkOut,
    ValuesIn,
    WorkloadOut,
)
from app.modules.files.contracts import read_limited
from app.modules.identity.contracts import P, Principal, require

project_router = APIRouter(prefix="/projects/{project_id}/field", tags=["field work"])
router = APIRouter(prefix="/field", tags=["field work"])
public_router = APIRouter(prefix="/public/field-upload", tags=["public"])
Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]
Reader = Annotated[Principal, Depends(require(P.FIELD_READ))]
Worker = Annotated[Principal, Depends(require(P.FIELD_WORK))]
Manager = Annotated[Principal, Depends(require(P.FIELD_MANAGE))]
Verifier = Annotated[Principal, Depends(require(P.FIELD_VERIFY))]
STREAM_SECONDS = 25
STREAM_POLL_SECONDS = 2.0


def _run(r: Any) -> RunOut:
    return RunOut.model_validate(r, from_attributes=True)


async def _detail(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> RunDetailOut:
    run, events, evidence, checks, waiting = await service.get_run(session, principal, run_id)
    brief = (await service.project_briefs(session, principal, {run.project_id})).get(run.project_id)
    codes = await service.codes_on(session)
    return RunDetailOut(
        run=_run(run),
        project=ProjectBriefOut(**brief) if brief else None,
        events=[EventOut.model_validate(e, from_attributes=True) for e in events],
        evidence=[EvidenceOut.model_validate(e, from_attributes=True) for e in evidence],
        checks=[CheckOut.model_validate(c, from_attributes=True) for c in checks],
        waiting_on=waiting,
        next_action=service.next_action(
            run, {e.requirement_index for e in evidence}, waiting, codes
        ),
        customer_codes=codes,
    )


# ------------------------------------------------------------------ project level


@project_router.post("/start", response_model=list[RunOut], status_code=status.HTTP_201_CREATED)
async def start(session: Session, principal: Manager, project_id: uuid.UUID, idem: Idem) -> Any:
    """Turn the locked plan into tasks for the engineers and tell each of them."""

    async def work() -> list[dict[str, Any]]:
        runs = await service.start_field_work(session, principal, project_id)
        return [_run(r).model_dump(mode="json") for r in runs]

    return await run_idempotent(idem, str(principal.user_id), 201, work)


@project_router.get("/runs", response_model=list[RunOut])
async def project_runs(
    session: Session,
    principal: Reader,
    project_id: uuid.UUID,
    state: Annotated[str | None, Query(max_length=20)] = None,
) -> list[RunOut]:
    return [_run(r) for r in await service.list_runs(session, principal, project_id, state)]


@project_router.get("/summary", response_model=SummaryOut)
async def project_summary(session: Session, principal: Reader, project_id: uuid.UUID) -> SummaryOut:
    """For the Director: tasks by state, blocked with reasons, late, overdue, failing checks."""
    s = await service.summary(session, principal, project_id)
    return SummaryOut(
        counts=s["counts"],
        total=s["total"],
        closed_share=s["closed_share"],
        blocked=[_run(r) for r in s["blocked"]],
        late=[_run(r) for r in s["late"]],
        overdue=[_run(r) for r in s["overdue"]],
        failing_checks=[_run(r) for r in s["failing_checks"]],
        rework=s["rework"],
    )


@project_router.get("/events", response_model=list[EventOut])
async def project_events(
    session: Session,
    principal: Reader,
    project_id: uuid.UUID,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    latest: bool = False,
) -> list[EventOut]:
    """Polling fallback for the live feed: events after the last `seq` you saw. `latest=true`
    gives the newest `limit` events instead, which is where a feed should start."""
    return [
        EventOut.model_validate(e, from_attributes=True)
        for e in await service.events_after(
            session, principal, project_id, after, limit, latest=latest
        )
    ]


@project_router.get("/stream")
async def project_stream(
    request: Request,
    session: Session,
    principal: Reader,
    project_id: uuid.UUID,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Server-sent events: each new field event as it happens. The stream ends after 25 seconds
    and the browser reconnects with `Last-Event-ID`, so nothing is missed."""
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    await service.events_after(session, principal, project_id, cursor, 1)  # access check now
    await session.close()

    async def gen() -> AsyncIterator[str]:
        nonlocal cursor
        yield "retry: 3000\n\n"
        deadline = time.monotonic() + STREAM_SECONDS
        while time.monotonic() < deadline and not await request.is_disconnected():
            async with get_sessionmaker()() as s:
                events = await service.events_after(s, principal, project_id, cursor, 100)
            for e in events:
                cursor = e.seq
                body = EventOut.model_validate(e, from_attributes=True).model_dump(mode="json")
                yield f"id: {e.seq}\nevent: run_event\ndata: {json.dumps(body)}\n\n"
            if not events:
                yield ": waiting\n\n"
                await asyncio.sleep(STREAM_POLL_SECONDS)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------ the engineer


@router.get("/my", response_model=list[MyRunOut])
async def my_tasks(session: Session, principal: Worker) -> list[MyRunOut]:
    """Today and later: the signed-in engineer's open tasks, in planned order, each with the
    project and customer it belongs to."""
    runs = await service.my_runs(session, principal)
    briefs = await service.project_briefs(session, principal, {r.project_id for r in runs})
    out = []
    for r in runs:
        row = MyRunOut.model_validate(r, from_attributes=True)
        b = briefs.get(r.project_id)
        row.project = ProjectBriefOut(**b) if b else None
        out.append(row)
    return out


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def run_detail(session: Session, principal: Reader, run_id: uuid.UUID) -> RunDetailOut:
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/accept", response_model=RunDetailOut)
async def accept(
    session: Session, principal: Worker, run_id: uuid.UUID, body: ClientIn
) -> RunDetailOut:
    await service.accept(
        session,
        principal,
        run_id,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
    )
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/depart", response_model=RunDetailOut)
async def depart(
    session: Session, principal: Worker, run_id: uuid.UUID, body: LocatedIn
) -> RunDetailOut:
    await service.depart(
        session,
        principal,
        run_id,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
        lat=body.lat,
        lng=body.lng,
        accuracy_m=body.accuracy_m,
    )
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/codes/{purpose}", response_model=CodeSentOut)
async def send_code(
    session: Session, principal: Worker, run_id: uuid.UUID, purpose: Literal["check_in", "handover"]
) -> CodeSentOut:
    """Send a one-time code to the customer. The engineer asks the customer for it on site."""
    await check(f"user:{principal.user_id}", Limit("otp", 10, strict=True))
    return CodeSentOut(**await service.request_code(session, principal, run_id, purpose))


@router.post("/runs/{run_id}/check-in", response_model=RunDetailOut)
async def check_in(
    session: Session, principal: Worker, run_id: uuid.UUID, body: CodeIn
) -> RunDetailOut:
    await service.check_in(
        session,
        principal,
        run_id,
        code=body.code,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
        lat=body.lat,
        lng=body.lng,
        accuracy_m=body.accuracy_m,
    )
    return await _detail(session, principal, run_id)


@router.post(
    "/runs/{run_id}/evidence", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED
)
async def add_evidence(
    request: Request,
    session: Session,
    principal: Worker,
    run_id: uuid.UUID,
    requirement_index: Annotated[int, Form(ge=0, le=100)],
    client_id: Annotated[uuid.UUID, Form()],
    captured_at: Annotated[str | None, Form()] = None,
    text_value: Annotated[str | None, Form(max_length=500)] = None,
    note: Annotated[str | None, Form(max_length=2000)] = None,
    lat: Annotated[float | None, Form(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Form(ge=-180, le=180)] = None,
    accuracy_m: Annotated[float | None, Form(ge=0, le=100_000)] = None,
    location_note: Annotated[str | None, Form(max_length=200)] = None,
    file: Annotated[UploadFile | None, File()] = None,
    stamped: Annotated[UploadFile | None, File()] = None,
) -> EvidenceOut:
    """Add one piece of evidence. `client_id` is made on the phone, so a resent upload after a
    dropped connection returns the first one instead of adding a copy.

    Photos may carry `stamped`, a copy with the time, place and task drawn on it; the original
    `file` stays the evidence. The arrival photo needs `lat` and `lng`; elsewhere a missing
    location is recorded with `location_note` saying why."""
    from datetime import datetime

    from app.core.errors import ValidationFailed

    try:
        cap = datetime.fromisoformat(captured_at) if captured_at else None
    except ValueError as exc:
        raise ValidationFailed("captured_at must be an ISO date and time.") from exc
    limit = get_settings().max_upload_bytes
    data = await read_limited(file, limit) if file else None
    stamped_data = await read_limited(stamped, limit) if stamped else None
    ev = await service.add_evidence(
        session,
        principal,
        run_id,
        requirement_index=requirement_index,
        client_id=client_id,
        data=data,
        filename=file.filename if file else None,
        text_value=text_value,
        note=note,
        captured_at=cap,
        client_ip=request.state.client_ip,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
        location_note=location_note,
        stamped=stamped_data,
        stamped_name=stamped.filename if stamped else None,
    )
    return EvidenceOut.model_validate(ev, from_attributes=True)


@router.get("/runs/{run_id}/config-diff", response_model=ConfigDiffOut)
async def config_diff(session: Session, principal: Reader, run_id: uuid.UUID) -> ConfigDiffOut:
    """The configuration export taken before any change (the rollback point) against the export
    after the work. Values that look like secrets are hidden."""
    return ConfigDiffOut(**await service.config_diff(session, principal, run_id))


@router.post(
    "/runs/{run_id}/upload-links",
    response_model=UploadLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def make_upload_link(
    session: Session, principal: Worker, run_id: uuid.UUID, body: UploadLinkIn
) -> UploadLinkOut:
    """A single-use link and QR code, valid for 15 minutes, to upload this task's configuration
    export from another device. The token is shown once and only its hash is kept."""
    await check(f"user:{principal.user_id}", Limit("upload_link", 20, strict=True))
    return UploadLinkOut(
        **await service.create_upload_link(
            session, principal, run_id, body.requirement_index, get_settings().public_base_url
        )
    )


@router.post("/device-status", status_code=status.HTTP_204_NO_CONTENT)
async def device_status(session: Session, principal: Worker, body: DeviceStatusIn) -> Response:
    """The phone reports the work saved on it and not yet sent, so the Director can tell an
    offline phone with work waiting from a quiet task."""
    await service.report_device_status(
        session,
        principal,
        pending=body.pending,
        failed=body.failed,
        oldest_pending_at=body.oldest_pending_at,
        last_sync_at=body.last_sync_at,
        app_version=body.app_version,
        platform=body.platform,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/engineers", response_model=list[EngineerStatusOut])
async def engineers(
    session: Session, principal: Annotated[Principal, Depends(require(P.DASHBOARD_READ))]
) -> list[EngineerStatusOut]:
    """Every field engineer with their open work and their phone's sync state."""
    return [EngineerStatusOut(**r) for r in await service.engineer_statuses(session, principal)]


@router.get("/workload", response_model=list[WorkloadOut])
async def workload(
    session: Session,
    principal: Manager,
    days: Annotated[int, Query(ge=1, le=31)] = 14,
) -> list[WorkloadOut]:
    """Planned hours per engineer per day for the coming days, with open, blocked and overdue
    tasks."""
    return [WorkloadOut(**r) for r in await service.workload(session, principal, days)]


@router.post("/runs/{run_id}/prechecks-done", response_model=RunDetailOut)
async def prechecks_done(
    session: Session, principal: Worker, run_id: uuid.UUID, body: ClientIn
) -> RunDetailOut:
    await service.finish_prechecks(
        session,
        principal,
        run_id,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
    )
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/steps/{index}", response_model=RunDetailOut)
async def step_done(
    session: Session, principal: Worker, run_id: uuid.UUID, index: int, body: StepIn
) -> RunDetailOut:
    await service.complete_step(
        session,
        principal,
        run_id,
        index,
        note=body.note,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
    )
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/values", response_model=RunDetailOut)
async def record_values(
    session: Session, principal: Worker, run_id: uuid.UUID, body: ValuesIn
) -> RunDetailOut:
    """The value seen on the device for each target setting, for the configuration check."""
    await service.record_actuals(
        session,
        principal,
        run_id,
        dict(body.values),
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
    )
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/configured", response_model=RunDetailOut)
async def configured(
    session: Session, principal: Worker, run_id: uuid.UUID, body: ClientIn
) -> RunDetailOut:
    await service.mark_configured(
        session,
        principal,
        run_id,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
    )
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/submit-evidence", response_model=RunDetailOut)
async def submit_evidence(
    session: Session, principal: Worker, run_id: uuid.UUID, body: ClientIn
) -> RunDetailOut:
    """Evidence complete. The configuration check runs at once; a failed critical or major
    setting sends the task back to configured."""
    await service.submit_evidence(
        session,
        principal,
        run_id,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
    )
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/hand-over", response_model=RunDetailOut)
async def hand_over(
    session: Session, principal: Worker, run_id: uuid.UUID, body: CodeIn
) -> RunDetailOut:
    await service.hand_over(
        session,
        principal,
        run_id,
        code=body.code,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
        lat=body.lat,
        lng=body.lng,
        accuracy_m=body.accuracy_m,
    )
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/block", response_model=RunDetailOut)
async def block(
    session: Session, principal: Worker, run_id: uuid.UUID, body: BlockIn
) -> RunDetailOut:
    await service.block(
        session,
        principal,
        run_id,
        reason=body.reason,
        client_event_id=body.client_event_id,
        captured_at=body.captured_at,
    )
    return await _detail(session, principal, run_id)


# ------------------------------------------------------------------ managers and verifiers


@router.post("/runs/{run_id}/unblock", response_model=RunDetailOut)
async def unblock(
    session: Session, principal: Manager, run_id: uuid.UUID, body: NoteIn
) -> RunDetailOut:
    await service.unblock(session, principal, run_id, note=body.note)
    return await _detail(session, principal, run_id)


@router.post("/runs/{run_id}/reassign", response_model=RunDetailOut)
async def reassign(
    session: Session, principal: Manager, run_id: uuid.UUID, body: ReassignIn
) -> RunDetailOut:
    await service.reassign(
        session, principal, run_id, assignee_id=body.assignee_id, reason=body.reason
    )
    return await _detail(session, principal, run_id)


@router.get("/review-queue", response_model=list[RunOut])
async def review_queue(session: Session, principal: Verifier) -> list[RunOut]:
    """Handed over tasks waiting for a verifier, excluding your own work."""
    return [_run(r) for r in await service.review_queue(session, principal)]


@router.post("/runs/{run_id}/decision", response_model=RunDetailOut)
async def decision(
    session: Session, principal: Verifier, run_id: uuid.UUID, body: DecisionIn
) -> RunDetailOut:
    await service.decide(
        session, principal, run_id, approve=body.decision == "approve", reason=body.reason
    )
    return await _detail(session, principal, run_id)


@router.get("/runs/{run_id}/render")
async def render_checklist(
    session: Session, principal: Reader, run_id: uuid.UUID, fmt: Literal["html", "pdf"] = "pdf"
) -> Response:
    """The task's checklist record: timeline, steps, evidence, checks and the verifier's
    decision."""
    ctx = await render.checklist_context(session, principal, run_id)
    if fmt == "html":
        return Response(content=render.render_html(ctx), media_type="text/html; charset=utf-8")
    doc = await rendered(render.render_checklist_pdf, ctx)
    return Response(
        content=doc.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{ctx["file_name"]}"',
            "X-Content-SHA256": doc.sha256,
        },
    )


# ------------------------------------------------------------------ public upload link


async def _public_limit(request: Request, token: str) -> None:
    await check(f"ip:{request.state.client_ip}", Limit("public", 30, strict=True))
    if not 20 <= len(token) <= 100:
        from app.core.errors import NotFound

        raise NotFound(
            "This upload link is not valid. Ask the engineer for a new one.", code="link_invalid"
        )


@public_router.get("/{token}", response_model=UploadLinkInfoOut)
async def upload_link_info(request: Request, session: Session, token: str) -> UploadLinkInfoOut:
    """Which task and which file the link is for. Nothing else about the customer or the job."""
    await _public_limit(request, token)
    return UploadLinkInfoOut(**await service.upload_link_info(session, token))


@public_router.post("/{token}", response_model=UploadLinkDoneOut)
async def upload_with_link(
    request: Request,
    session: Session,
    token: str,
    file: Annotated[UploadFile, File()],
) -> UploadLinkDoneOut:
    """Upload the configuration export once. The link cannot be used again."""
    await _public_limit(request, token)
    data = await read_limited(file, get_settings().max_upload_bytes)
    return UploadLinkDoneOut(
        **await service.upload_via_link(
            session,
            token,
            data=data,
            filename=file.filename or "export.txt",
            client_ip=request.state.client_ip,
        )
    )


routers = [project_router, router, public_router]
