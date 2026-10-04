"""What the completion report says, gathered from the other modules' contracts. No prices.

Sections (see the PRD): scope delivered, exclusions (waivers), before and after scores on the
four lenses, configuration summary per device, deviations, and recommendations still open.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.timeutil import format_long_date, to_ist, today_ist
from app.modules.boq.contracts import get_accepted_boq
from app.modules.customers.contracts import get_customer_ref, get_project_ref
from app.modules.fieldops.contracts import check_summaries, list_run_refs
from app.modules.identity.contracts import Principal, get_user_summary
from app.modules.infra.contracts import get_locked_gaps
from app.modules.prismsuite.contracts import get_approved_audit
from app.modules.verification.contracts import project_deviations

# The four lenses and the PrismSuite headline score each one is read from (as in infra).
LENSES = (
    ("productivity", "Productivity", "performance"),
    ("resilience", "Resilience", "high_availability"),
    ("security", "Security", "security"),
    ("health", "Health", "system_health"),
)


def _score(snapshot: Any, key: str) -> Decimal | None:
    s = getattr(snapshot.scores, key, None)
    try:
        return Decimal(str(s.value)) if s is not None and s.value is not None else None
    except (InvalidOperation, ValueError):
        return None


def lens_table(before: Any, after: Any | None) -> list[dict[str, Any]]:
    rows = []
    for key, label, source in LENSES:
        b = _score(before, source) if before is not None else None
        a = _score(after, source) if after is not None else None
        rows.append(
            {
                "key": key,
                "label": label,
                "before": str(b) if b is not None else None,
                "after": str(a) if a is not None else None,
                "change": str(a - b) if a is not None and b is not None else None,
            }
        )
    return rows


async def build_content(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, waivers: list[Any]
) -> dict[str, Any]:
    project = await get_project_ref(session, principal, project_id)
    customer = await get_customer_ref(session, principal, project.customer_id)
    names: dict[uuid.UUID, str] = {}

    async def name(uid: uuid.UUID | None) -> str | None:
        if uid is None:
            return None
        if uid not in names:
            u = await get_user_summary(session, uid)
            names[uid] = u.full_name if u else "Unknown"
        return names[uid]

    runs = await list_run_refs(session, principal, project_id)
    checks = await check_summaries(session, principal, project_id)
    waived_tasks = {
        w.target_id: w for w in waivers if w.scope == "task" and w.status == "acknowledged"
    }

    delivered, exclusions, config = [], [], []
    for r in runs:
        if r.state == "closed":
            delivered.append(
                {
                    "ref": r.task_ref,
                    "title": r.title,
                    "device": r.asset,
                    "closed": format_long_date(to_ist(r.closed_at).date()) if r.closed_at else None,
                    "verified_by": await name(r.verified_by),
                }
            )
        if r.id in checks:
            c = checks[r.id]
            config.append({"ref": r.task_ref, "device": r.asset or r.title, **c})
    for w in waivers:
        if w.status == "acknowledged":
            exclusions.append(
                {
                    "what": w.target_label,
                    "kind": w.kind.replace("_", " "),
                    "reason": w.reason,
                    "approved_by": await name(w.decided_by),
                    "acknowledged_by": w.acknowledged_name,
                }
            )

    try:
        before = (await get_approved_audit(session, principal, project_id, "baseline")).snapshot
    except NotFound:
        before = None
    try:
        after = (await get_approved_audit(session, principal, project_id, "rescan")).snapshot
    except NotFound:
        after = None

    deviations = await project_deviations(session, principal, project_id)
    closed_devs = [d for d in deviations if d.status != "open"]
    open_devs = [d for d in deviations if d.status == "open"]

    quote_ref = po = None
    covered: set[str] = set()
    try:
        boq = await get_accepted_boq(session, principal, project_id)
        quote_ref, po = boq.quote_ref, boq.po_number
        for ln in boq.lines:
            covered.update(ln.source_gaps)
    except NotFound:
        pass
    open_recs = []
    try:
        gaps = await get_locked_gaps(session, principal, project_id)
        for g in gaps.gaps:
            if g.code not in covered and str(g.id) not in covered:
                open_recs.append(
                    {
                        "code": g.code,
                        "title": g.title,
                        "lens": g.lens,
                        "priority": g.priority,
                        "recommendation": g.recommendation,
                    }
                )
    except NotFound:
        pass

    starts = [r.checked_in_at for r in runs if r.checked_in_at]
    ends = [r.closed_at for r in runs if r.closed_at]
    return {
        "project": {"id": str(project.id), "code": project.code, "name": project.name},
        "customer": {
            "name": customer.display_name,
            "legal_name": customer.legal_name,
            "address_lines": list(customer.address_lines),
        },
        "quote_ref": quote_ref,
        "po_number": po,
        "work_started": format_long_date(to_ist(min(starts)).date()) if starts else None,
        "work_finished": format_long_date(to_ist(max(ends)).date()) if ends else None,
        "delivered": delivered,
        "exclusions": exclusions,
        "waived_task_ids": [str(t) for t in waived_tasks],
        "lenses": lens_table(before, after),
        "baseline_ref": before.header.report_reference if before is not None else None,
        "rescan_ref": after.header.report_reference if after is not None else None,
        "configuration": config,
        "deviations_closed": [
            {
                "task": d.task_ref,
                "label": d.label,
                "severity": d.severity,
                "status": d.status,
                "resolution": d.resolution,
            }
            for d in closed_devs
        ],
        "deviations_open": [
            {
                "task": d.task_ref,
                "label": d.label,
                "severity": d.severity,
                "expected": d.expected,
                "actual": d.actual,
            }
            for d in open_devs
        ],
        "open_recommendations": open_recs,
        "verifiers": sorted(
            {n for r in runs if r.verified_by and (n := await name(r.verified_by))}
        ),
        "printed": format_long_date(today_ist()),
    }
