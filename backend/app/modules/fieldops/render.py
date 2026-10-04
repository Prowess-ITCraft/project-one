"""The checklist record of one field task as HTML and PDF (DESIGN.md section 8): the timeline of
states with time and place, the steps, the evidence (photos embedded), each configuration check
and the verifier's decision. Contacts are shown masked. No prices."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.documents import RenderedDocument, render_pdf, template_env
from app.core.timeutil import format_long_date, to_ist, today_ist
from app.modules.boq.contracts import get_company_profile
from app.modules.customers.contracts import get_customer_ref, get_project_ref
from app.modules.fieldops import service
from app.modules.files.contracts import read_file
from app.modules.identity.contracts import Principal, get_user_summary

_env = template_env(Path(__file__).parent / "html")
MAX_IMAGES = 20
IMAGE_KINDS = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _when(dt: Any) -> str:
    return to_ist(dt).strftime("%d %b %Y %H:%M") if dt else ""


async def checklist_context(
    session: AsyncSession, principal: Principal, run_id: uuid.UUID
) -> dict[str, Any]:
    run, events, evidence, checks, waiting = await service.get_run(session, principal, run_id)
    project = await get_project_ref(session, principal, run.project_id)
    customer = await get_customer_ref(session, principal, project.customer_id)
    names: dict[uuid.UUID, str] = {}

    async def name(uid: uuid.UUID | None) -> str:
        if uid is None:
            return "Project One"
        if uid not in names:
            u = await get_user_summary(session, uid)
            names[uid] = u.full_name if u else "Unknown"
        return names[uid]

    timeline = []
    for e in events:
        if e.from_state == e.to_state and e.action not in ("depart", "evidence_added", "step_done"):
            continue
        place = f"{e.lat:.5f}, {e.lng:.5f}" if e.lat is not None and e.lng is not None else ""
        timeline.append(
            {
                "when": _when(e.captured_at or e.at),
                "action": e.action.replace("_", " "),
                "to": (
                    (
                        "configuration check passed"
                        if e.detail.get("passed")
                        else "configuration check failed"
                    )
                    if e.action == "engine_check"
                    else service.STATE_LABEL.get(e.to_state or "", e.to_state or "")
                ),
                "who": await name(e.actor_id),
                "place": place,
                "detail": e.detail.get("reason")
                or e.detail.get("text")
                or e.detail.get("label")
                or "",
            }
        )

    items = []
    images = 0
    for ev in evidence:
        req = run.evidence_reqs[ev.requirement_index]
        image = None
        if ev.file_id and ev.type in ("photo", "screenshot") and images < MAX_IMAGES:
            ref, data = await read_file(session, principal, ev.file_id)
            if ref.kind in IMAGE_KINDS:
                image = f"data:{IMAGE_KINDS[ref.kind]};base64,{base64.b64encode(data).decode()}"
                images += 1
        items.append(
            {
                "label": req["label"],
                "stage": req.get("stage", "work").replace("_", " "),
                "type": ev.type.replace("_", " "),
                "text": ev.text_value or "",
                "note": ev.note or "",
                "when": _when(ev.captured_at),
                "by": await name(ev.uploaded_by),
                "image": image,
            }
        )

    def by_code(action: str) -> bool:
        """Whether the latest check-in or hand over was confirmed with the customer's code;
        not so while customer codes are switched off (ADR 0025)."""
        last = [e for e in events if e.action == action]
        return bool(last) and "confirmed_by_contact" in (last[-1].detail or {})

    return {
        "company": await get_company_profile(session),
        "title": f"Task record {run.task_ref}",
        "file_name": f"{project.code}-{run.task_ref}-record.pdf",
        "customer": customer.display_name,
        "project": project.name,
        "run": {
            "ref": run.task_ref,
            "title": run.title,
            "asset": run.asset or "",
            "state": service.STATE_LABEL[run.state],
            "engineer": await name(run.assignee_id),
            "planned": f"{_when(run.planned_start)} to {_when(run.planned_end)}",
            "checked_in": _when(run.checked_in_at),
            "checked_in_by_code": by_code("check_in"),
            "handed_over": _when(run.handed_over_at),
            "handed_over_by_code": by_code("hand_over"),
            "closed": _when(run.closed_at),
            "verified_by": await name(run.verified_by) if run.verified_by else "",
            "rework": run.rework_count,
        },
        "steps": [
            {
                "text": s["text"],
                "done": s["done"],
                "when": (s.get("done_at") or "")[:16].replace("T", " "),
            }
            for s in run.steps
        ],
        "baseline": [
            {
                "label": f["label"],
                "expected": f["expected"],
                "severity": f.get("severity", ""),
                "actual": (run.actuals.get(f["key"]) or {}).get("value", ""),
            }
            for f in run.baseline
        ],
        "checks": [
            {
                "attempt": c.attempt,
                "when": _when(c.created_at),
                "passed": c.passed,
                "fields": c.result.get("fields", []),
            }
            for c in checks
        ],
        "timeline": timeline,
        "evidence": items,
        "printed": format_long_date(today_ist()),
        "waiting_on": waiting,
    }


def render_html(ctx: dict[str, Any]) -> str:
    return _env.get_template("checklist.html").render(**ctx)


def render_checklist_pdf(ctx: dict[str, Any]) -> RenderedDocument:
    return render_pdf(render_html(ctx))
