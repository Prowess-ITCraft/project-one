"""The implementation plan and schedule as HTML and PDF (DESIGN.md section 8).

One table per working day in IST (time, task, engineer, asset, downtime), then the downtime
windows agreed with the customer, then the target configuration per device. Plans never carry
prices, so this document is safe to share with field engineers and the customer."""

from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.documents import RenderedDocument, render_pdf, template_env
from app.core.timeutil import format_long_date, to_ist, today_ist
from app.modules.boq.contracts import get_company_profile
from app.modules.customers.contracts import get_customer_ref, get_project_ref
from app.modules.identity.contracts import Principal, get_user_summary
from app.modules.planning import service

_env = template_env(Path(__file__).parent / "html")


def _hours(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


async def plan_context(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> dict[str, Any] | None:
    got = await service.get_plan(session, principal, project_id)
    if got is None:
        return None
    plan, tasks, baselines, windows = got
    project = await get_project_ref(session, principal, project_id)
    customer = await get_customer_ref(session, principal, project.customer_id)
    names: dict[uuid.UUID, str] = {}
    for t in tasks:
        if t.assignee_id and t.assignee_id not in names:
            u = await get_user_summary(session, t.assignee_id)
            names[t.assignee_id] = u.full_name if u else "Unknown"

    days: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unscheduled: list[dict[str, Any]] = []
    for t in tasks:
        row = {
            "ref": t.ref,
            "title": t.title,
            "asset": t.asset or "",
            "engineer": names.get(t.assignee_id, "Not assigned")
            if t.assignee_id
            else "Not assigned",
            "minutes": _hours(t.minutes),
            "downtime": t.requires_downtime,
            "after": ", ".join(t.depends_on),
            "start": to_ist(t.start_at).strftime("%H:%M") if t.start_at else "",
            "end": to_ist(t.end_at).strftime("%H:%M") if t.end_at else "",
        }
        if t.start_at:
            days[format_long_date(to_ist(t.start_at).date())].append(row)
        else:
            unscheduled.append(row)

    return {
        "company": await get_company_profile(session),
        "title": f"Implementation plan {plan.number}",
        "project": project.name,
        "project_code": project.code,
        "customer": customer.display_name,
        "plan_number": plan.number,
        "status": "Locked" if plan.status == "baselined" else "Draft",
        "boq_ref": plan.boq_quote_ref,
        "printed": format_long_date(today_ist()),
        "task_count": len(tasks),
        "total": _hours(sum(t.minutes for t in tasks)),
        "days": list(days.items()),
        "unscheduled": unscheduled,
        "windows": [
            {
                "from": to_ist(w.start_at).strftime("%d %b %Y %H:%M"),
                "to": to_ist(w.end_at).strftime("%d %b %Y %H:%M"),
                "note": w.note or "",
            }
            for w in windows
        ],
        "baselines": [
            {"label": b.device_label, "type": b.device_type, "task": b.task_ref, "fields": b.fields}
            for b in baselines
        ],
        "warnings": plan.warnings,
    }


def render_html(ctx: dict[str, Any]) -> str:
    return _env.get_template("plan.html").render(**ctx)


def render_plan_pdf(ctx: dict[str, Any]) -> RenderedDocument:
    return render_pdf(render_html(ctx))
