"""BOQ workflow: generate, edit, pricing approval, issue, accept with a purchase order."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.errors import Conflict, Forbidden, NotFound, StaleVersion, ValidationFailed
from app.core.events import DomainEvent
from app.core.money import quantize
from app.core.sequences import next_value
from app.core.timeutil import financial_year_code, today_ist, utcnow
from app.modules.audit_log.contracts import record
from app.modules.boq import draft as d
from app.modules.boq.generate import build_draft, line_from_item
from app.modules.boq.models import (
    Boq,
    BoqEdit,
    BoqTemplate,
    BoqVersion,
    CompanySettings,
    RecoWeights,
)
from app.modules.boq.recommend import DEFAULT_WEIGHTS
from app.modules.boq.seed import DEFAULT_COMPANY
from app.modules.boq.templates import validate_body
from app.modules.catalogue.contracts import find_item_by_code, get_item_ref, get_price_quote
from app.modules.customers.contracts import (
    Stage,
    artifact_locked_event,
    get_brief_ref,
    get_customer_ref,
    get_project_ref,
)
from app.modules.datasets.contracts import boq_history
from app.modules.files.contracts import get_file
from app.modules.identity.contracts import P, Principal, audit_context, ensure_different_people
from app.modules.infra.contracts import get_locked_gaps

ARTIFACT = "boq_version"
VERSION_ISSUED = "boq.version_issued"
BOQ_ACCEPTED = "boq.accepted"


# ------------------------------------------------------------------ master data


async def company(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(CompanySettings, "company")
    # Settings saved before a key existed fall back to its default (for example the logo).
    return {**DEFAULT_COMPANY, **(dict(row.data) if row else {})}


async def save_company(
    session: AsyncSession, principal: Principal, data: dict[str, Any], version: int | None
) -> dict[str, Any]:
    principal.require(P.SETTINGS_EDIT)
    row = await session.get(CompanySettings, "company")
    if row is None:
        session.add(CompanySettings(key="company", data=data, updated_by=principal.user_id))
        before = None
    else:
        if version != row.version:
            raise StaleVersion()
        before = dict(row.data)
        row.data, row.updated_by = data, principal.user_id
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="company_saved",
        entity_type="company_settings",
        entity_id="company",
        before=before,
        after=data,
    )
    await session.commit()
    return data


async def weights_for(session: AsyncSession, segment: str | None) -> dict[str, float]:
    row = await session.get(RecoWeights, segment) if segment else None
    row = row or await session.get(RecoWeights, "default")
    return {**DEFAULT_WEIGHTS, **(dict(row.weights) if row else {})}


async def save_weights(
    session: AsyncSession, principal: Principal, segment: str, weights: dict[str, float]
) -> dict[str, float]:
    principal.require(P.SETTINGS_EDIT)
    if set(weights) - set(DEFAULT_WEIGHTS):
        raise ValidationFailed(
            f"Unknown weights: {', '.join(sorted(set(weights) - set(DEFAULT_WEIGHTS)))}."
        )
    if any(v < 0 or v > 1 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValidationFailed("Each weight is between 0 and 1 and they cannot all be zero.")
    row = await session.get(RecoWeights, segment)
    if row is None:
        session.add(RecoWeights(segment=segment, weights=weights, updated_by=principal.user_id))
    else:
        row.weights, row.updated_by = weights, principal.user_id
    await record(
        session,
        audit_context(principal),
        action="weights_saved",
        entity_type="reco_weights",
        entity_id=segment,
        after=weights,
        only_changes=False,
    )
    await session.commit()
    return weights


async def list_templates(session: AsyncSession) -> list[BoqTemplate]:
    return list(await session.scalars(select(BoqTemplate).order_by(BoqTemplate.gap_type)))


async def save_template(
    session: AsyncSession,
    principal: Principal,
    *,
    gap_type: str,
    body: dict[str, Any],
    active: bool,
    version: int | None,
) -> BoqTemplate:
    principal.require(P.TEMPLATE_EDIT)
    try:
        parsed = validate_body(body)
    except ValueError as exc:
        raise ValidationFailed(
            f"The template is not valid: {str(exc).splitlines()[-1]}", code="template_invalid"
        ) from exc
    for ln in parsed.lines:
        if ln.item_code:
            try:
                await find_item_by_code(session, principal, ln.item_code)
            except NotFound as exc:
                raise ValidationFailed(
                    f"Line '{ln.key}' names {ln.item_code}, which is not in the catalogue.",
                    code="template_item_missing",
                ) from exc
    row = await session.scalar(select(BoqTemplate).where(BoqTemplate.gap_type == gap_type))
    before = None
    if row is None:
        row = BoqTemplate(
            gap_type=gap_type,
            title=parsed.title,
            lines=[ln.model_dump(mode="json", exclude_none=True) for ln in parsed.lines],
            active=active,
            updated_by=principal.user_id,
        )
        session.add(row)
    else:
        if version != row.version:
            raise StaleVersion()
        before = {"title": row.title, "lines": row.lines, "active": row.active}
        row.title, row.lines, row.active = (
            parsed.title,
            [ln.model_dump(mode="json", exclude_none=True) for ln in parsed.lines],
            active,
        )
        row.revision += 1
        row.updated_by = principal.user_id
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="template_saved",
        entity_type="boq_template",
        entity_id=row.id,
        before=before,
        after={"gap_type": gap_type, "title": row.title, "lines": row.lines, "active": active},
        only_changes=False,
    )
    await session.commit()
    await session.refresh(row)
    return row


# ------------------------------------------------------------------ helpers


def _draft(b: Boq) -> d.Draft:
    return d.Draft.model_validate(b.draft)


def _store(b: Boq, draft: d.Draft) -> None:
    b.draft = draft.model_dump(mode="json")


async def _load(
    session: AsyncSession, principal: Principal, boq_id: uuid.UUID, *, lock: bool = False
) -> Boq:
    principal.require(P.BOQ_READ)
    b = await session.get(Boq, boq_id, with_for_update=lock)
    if b is None:
        raise NotFound("BOQ not found.")
    await get_project_ref(session, principal, b.project_id)  # object-level access
    return b


async def for_project(session: AsyncSession, principal: Principal, project_id: uuid.UUID) -> Boq:
    principal.require(P.BOQ_READ)
    await get_project_ref(session, principal, project_id)
    b = await session.scalar(select(Boq).where(Boq.project_id == project_id))
    if b is None:
        raise NotFound("This project has no BOQ yet.")
    return b


async def _log(
    session: AsyncSession, b: Boq, principal: Principal, action: str, reason: str, detail: list[str]
) -> None:
    session.add(
        BoqEdit(
            boq_id=b.id,
            by=principal.user_id,
            action=action,
            reason=reason,
            detail=detail,
            draft_rev=b.version,
        )
    )
    await record(
        session,
        audit_context(principal),
        action=f"boq_{action}",
        entity_type="boq",
        entity_id=b.id,
        after={"reason": reason, "detail": detail[:12]},
        only_changes=False,
    )


def _editable(b: Boq) -> None:
    if b.status != "draft":
        raise Conflict(
            f"This BOQ is {b.status}. Return the project to the BOQ stage and reopen it to change it.",
            code="boq_locked",
        )


def _reset_review(b: Boq) -> bool:
    """Any edit after submission voids the pricing review: the approver saw a different BOQ."""
    if b.stage != "drafting":
        b.stage, b.submitted_by, b.pricing_approved_by = "drafting", None, None
        return True
    return False


async def editors(session: AsyncSession, b: Boq) -> set[uuid.UUID]:
    last = await session.scalar(
        select(BoqVersion.issued_at)
        .where(BoqVersion.boq_id == b.id)
        .order_by(BoqVersion.number.desc())
        .limit(1)
    )
    stmt = select(BoqEdit.by).where(
        BoqEdit.boq_id == b.id,
        BoqEdit.action.in_(("generated", "edited", "prices_refreshed", "reopened")),
    )
    if last:
        stmt = stmt.where(BoqEdit.at > last)
    return set(await session.scalars(stmt))


# ------------------------------------------------------------------ generate and view


async def generate(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, *, replace: bool
) -> Boq:
    principal.require(P.BOQ_EDIT)
    project = await get_project_ref(session, principal, project_id)
    if project.current_stage != Stage.BOQ:
        raise Conflict(
            "The project is not at the BOQ stage yet. Approve the gap analysis first.",
            code="not_boq_stage",
        )
    existing = await session.scalar(
        select(Boq).where(Boq.project_id == project_id).with_for_update()
    )
    if existing is not None and not replace:
        raise Conflict(
            "This project already has a BOQ. Edit it, or generate again with replace to start over.",
            code="boq_exists",
        )
    if existing is not None:
        _editable(existing)
    gapset = await get_locked_gaps(session, principal, project_id)
    brief = await get_brief_ref(session, principal, project_id)
    customer = await get_customer_ref(session, principal, project.customer_id)
    comp = await company(session)
    templates = {t.gap_type: t for t in await list_templates(session) if t.active}
    today = today_ist()
    draft, report = await build_draft(
        session,
        principal,
        gapset=gapset,
        brief=brief,
        customer=customer,
        templates=templates,
        company=comp,
        weights=await weights_for(session, brief.company_size if brief else None),
        today=today,
    )
    scope = ", ".join(dict.fromkeys(s.title for s in draft.sections))[:160] or "your requirements"
    draft.settings = d.Settings(
        quote_date=today,
        validity_days=int(comp.get("default_validity_days", 5)),
        gst_default=comp.get("gst_default", "18.00"),
        intro=str(comp.get("intro", "")).replace("{scope}", scope),
        customer=d.Party(name=customer.legal_name, address_lines=list(customer.address_lines)),
        signatory_name=comp.get("signatory_name", ""),
        signatory_designation=comp.get("signatory_designation", ""),
        budget_ceiling=brief.budget_ceiling if brief else None,
    )
    draft.terms = [
        t.replace("{gst}", str(draft.settings.gst_default).rstrip("0").rstrip(".")).replace(
            "{validity}", str(draft.settings.validity_days)
        )
        for t in comp.get("terms", [])
    ]
    if existing is None:
        b = Boq(
            project_id=project_id,
            draft=draft.model_dump(mode="json"),
            source_register_id=gapset.register_id,
            generation_report=report,
            created_by=principal.user_id,
        )
        session.add(b)
        await session.flush()
    else:
        b = existing
        _store(b, draft)
        b.source_register_id, b.generation_report = gapset.register_id, report
        b.stage, b.submitted_by, b.pricing_approved_by = "drafting", None, None
    await _log(
        session,
        b,
        principal,
        "generated",
        f"Drafted from gap register v{gapset.number}",
        [f"{len(draft.lines)} lines", f"{len(report['unmatched'])} unmatched gaps"],
    )
    await session.commit()
    await session.refresh(b)
    return b


def view(b: Boq, principal: Principal) -> dict[str, Any]:
    draft = _draft(b)
    comp = d.compute(draft, today_ist())
    out = draft.model_dump(mode="json")
    if not principal.has(P.PRICE_READ):
        for ln in out["lines"]:
            ln["cost"] = None
    numbered = {n.line.id: n for n in d.numbered(draft)}
    lines = []
    for r in comp.lines:
        ln = next(x for x in out["lines"] if x["id"] == r.id)
        lines.append(
            {
                **ln,
                "ref": r.ref,
                "number": numbered[r.id].number,
                "letter": numbered[r.id].letter,
                "amount": str(r.amount) if r.amount is not None else None,
                "gst": str(r.gst) if r.gst is not None else None,
                "flags": r.flags,
                "group_id": numbered[r.id].group_id,
            }
        )
    return {
        "id": str(b.id),
        "project_id": str(b.project_id),
        "status": b.status,
        "stage": b.stage,
        "quote_ref": b.quote_ref,
        "draft_rev": b.version,
        "settings": out["settings"],
        "groups": out["groups"],
        "sections": out["sections"],
        "lines": lines,
        "terms": out["terms"],
        "selected_options": out["selected_options"],
        "totals": comp.totals.model_dump(mode="json"),
        "blockers": comp.blockers,
        "warnings": comp.warnings,
        "generation_report": b.generation_report,
    }


# ------------------------------------------------------------------ edits


async def edit(
    session: AsyncSession,
    principal: Principal,
    boq_id: uuid.UUID,
    *,
    draft_rev: int,
    reason: str,
    ops: list[dict[str, Any]],
) -> Boq:
    principal.require(P.BOQ_EDIT)
    b = await _load(session, principal, boq_id, lock=True)
    _editable(b)
    if b.version != draft_rev:
        raise StaleVersion()
    try:
        new, notes = d.apply_ops(_draft(b), ops)
    except d.OpError as exc:
        raise ValidationFailed(str(exc), code=exc.code) from exc
    _store(b, new)
    reset = _reset_review(b)
    await _log(
        session,
        b,
        principal,
        "edited",
        reason,
        notes + (["pricing review withdrawn"] if reset else []),
    )
    await session.commit()
    await session.refresh(b)
    return b


async def refresh_prices(
    session: AsyncSession, principal: Principal, boq_id: uuid.UUID, *, draft_rev: int, reason: str
) -> tuple[Boq, list[str]]:
    """Pull the current price book price into every line that came from the price book or has no
    price. Lines priced by hand are never touched."""
    principal.require(P.BOQ_EDIT)
    b = await _load(session, principal, boq_id, lock=True)
    _editable(b)
    if b.version != draft_rev:
        raise StaleVersion()
    draft = _draft(b)
    changes: list[str] = []
    for ln in draft.lines:
        if ln.price_source == "manual" or not ln.item_id:
            continue
        item = await get_item_ref(session, principal, uuid.UUID(ln.item_id))
        q = await get_price_quote(session, principal, item.id)
        if q.usable and q.selling is not None:
            new_price = quantize(q.selling)
            if ln.unit_price != new_price or ln.price_source != "price_book":
                changes.append(f"{ln.title[:50]}: {ln.unit_price} to {new_price}")
            ln.unit_price, ln.cost, ln.price_source = new_price, q.cost, "price_book"
            ln.price_ref = d.PriceRef(
                price_id=str(q.price_id) if q.price_id else None, valid_until=q.valid_until
            )
            ln.hint_price = ln.hint_note = None
        elif ln.price_source == "price_book":
            changes.append(f"{ln.title[:50]}: price no longer valid ({q.state})")
            ln.unit_price, ln.price_source, ln.price_ref = None, "none", None
            ln.hint_price = quantize(q.selling) if q.selling is not None else None
            ln.hint_note = "Price expired. Enter the current price."
    _store(b, draft)
    _reset_review(b)
    await _log(session, b, principal, "prices_refreshed", reason, changes[:30] or ["no change"])
    await session.commit()
    await session.refresh(b)
    return b, changes


async def add_from_catalogue(
    session: AsyncSession,
    principal: Principal,
    boq_id: uuid.UUID,
    *,
    draft_rev: int,
    reason: str,
    item_code: str,
    section_id: str,
    qty: int,
    option_group: str | None,
) -> Boq:
    """Add a catalogue item as a line, with its inclusions and the current price if valid."""
    principal.require(P.BOQ_EDIT)
    b = await _load(session, principal, boq_id, lock=True)
    _editable(b)
    if b.version != draft_rev:
        raise StaleVersion()
    item = await find_item_by_code(session, principal, item_code)
    quote = await get_price_quote(session, principal, item.id)
    draft = _draft(b)
    if not any(s.id == section_id for s in draft.sections):
        raise ValidationFailed("Choose an existing section.")
    line = line_from_item(
        item,
        qty,
        quote,
        section_id=section_id,
        source=d.Source(kind="catalogue"),
        option_group=option_group,
    )
    draft.lines.append(line)
    try:
        draft, _ = (
            d.apply_ops(draft, [{"op": "update_settings", "fields": {}}])
            if False
            else (d.Draft.model_validate(draft.model_dump()), [])
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    _store(b, draft)
    _reset_review(b)
    await _log(session, b, principal, "edited", reason, [f"added catalogue item {item.name}"])
    await session.commit()
    await session.refresh(b)
    return b


async def line_history(
    session: AsyncSession, principal: Principal, boq_id: uuid.UUID, line_id: str
) -> dict[str, Any]:
    b = await _load(session, principal, boq_id)
    line = next((x for x in _draft(b).lines if x.id == line_id), None)
    if line is None:
        raise NotFound("Line not found.")
    hit = (await boq_history(session, [line.title]))[line.title]
    return {
        "line": line.title,
        "matched": hit.matched,
        "occurrences": hit.occurrences,
        "customers": hit.customers,
        "typical_qty": hit.typical_qty,
        "last_seen": str(hit.last_seen) if hit.last_seen else None,
        "median_unit_price": str(hit.median_unit_price)
        if hit.median_unit_price is not None
        else None,
        "min_unit_price": str(hit.min_unit_price) if hit.min_unit_price is not None else None,
        "max_unit_price": str(hit.max_unit_price) if hit.max_unit_price is not None else None,
        "note": "From past BOQs in the library. Advice only: prices change, enter the current one.",
    }


# ------------------------------------------------------------------ pricing review and issue


def _blockers(b: Boq, today: date) -> list[str]:
    return d.compute(_draft(b), today).blockers


async def submit_for_pricing(session: AsyncSession, principal: Principal, boq_id: uuid.UUID) -> Boq:
    principal.require(P.BOQ_EDIT)
    b = await _load(session, principal, boq_id, lock=True)
    _editable(b)
    if b.stage != "drafting":
        raise Conflict("This BOQ is already waiting for pricing review.", code="already_submitted")
    blockers = _blockers(b, today_ist())
    if blockers:
        raise Conflict(
            "Fix these before pricing review: "
            + "; ".join(blockers[:5])
            + (f" and {len(blockers) - 5} more." if len(blockers) > 5 else "."),
            code="boq_blockers",
            extra={"blockers": blockers},
        )
    b.stage, b.submitted_by = "pricing_review", principal.user_id
    await _log(session, b, principal, "submitted", "Submitted for pricing review", [])
    await session.commit()
    await session.refresh(b)
    return b


async def decide_pricing(
    session: AsyncSession,
    principal: Principal,
    boq_id: uuid.UUID,
    *,
    approve: bool,
    note: str | None,
) -> Boq:
    principal.require(P.BOQ_APPROVE_PRICING)
    b = await _load(session, principal, boq_id, lock=True)
    if b.stage != "pricing_review":
        raise Conflict("This BOQ is not waiting for pricing review.", code="not_in_review")
    # The person who drafted or edited this BOQ cannot approve its pricing.
    for person in await editors(session, b) | ({b.submitted_by} if b.submitted_by else set()):
        ensure_different_people(person, principal.user_id, "BOQ pricing")
    if approve:
        blockers = _blockers(b, today_ist())  # prices may have expired since submission
        if blockers:
            raise Conflict(
                "Prices changed since submission: " + "; ".join(blockers[:5]),
                code="boq_blockers",
                extra={"blockers": blockers},
            )
        b.stage, b.pricing_approved_by = "pricing_approved", principal.user_id
        await _log(session, b, principal, "pricing_approved", note or "Pricing approved", [])
    else:
        if not note or len(note.strip()) < 3:
            raise ValidationFailed("Say what needs to change.")
        b.stage, b.submitted_by, b.pricing_approved_by = "drafting", None, None
        await _log(session, b, principal, "pricing_rejected", note, [])
    await session.commit()
    await session.refresh(b)
    return b


async def issue(session: AsyncSession, principal: Principal, boq_id: uuid.UUID) -> BoqVersion:
    principal.require(P.BOQ_ISSUE)
    b = await _load(session, principal, boq_id, lock=True)
    _editable(b)
    if b.stage != "pricing_approved" or b.pricing_approved_by is None:
        raise Conflict(
            "Pricing must be approved by a sales head or the director before a BOQ is issued.",
            code="pricing_not_approved",
        )
    today = today_ist()
    blockers = _blockers(b, today)
    if blockers:
        raise Conflict(
            "Prices changed since approval: " + "; ".join(blockers[:5]),
            code="boq_blockers",
            extra={"blockers": blockers},
        )
    draft = _draft(b)
    comp = d.compute(draft, today)
    prev = await session.scalar(
        select(BoqVersion)
        .where(BoqVersion.boq_id == b.id)
        .order_by(BoqVersion.number.desc())
        .limit(1)
    )
    if b.quote_ref is None:
        c = await company(session)
        fy = financial_year_code(today)
        seq = await next_value(session, f"quote:{fy}")
        b.quote_ref = (
            f"{c.get('quote_prefix', 'ITCraft')}/{principal.initials.upper()}/{fy}/{seq:03d}"
        )
    delta = d.diff(d.Draft.model_validate(prev.content) if prev else None, draft)
    if prev is not None:
        prev.state = "superseded"
    v = BoqVersion(
        boq_id=b.id,
        project_id=b.project_id,
        number=(prev.number + 1) if prev else 1,
        quote_ref=b.quote_ref,
        content=draft.model_dump(mode="json"),
        totals=comp.totals.model_dump(mode="json"),
        change_summary=d.summarise(delta),
        delta=delta,
        issued_by=principal.user_id,
        pricing_approved_by=b.pricing_approved_by,
        selected_options=dict(draft.selected_options),
    )
    session.add(v)
    b.stage, b.submitted_by, b.pricing_approved_by = (
        "drafting",
        None,
        None,
    )  # the draft carries on towards the next version
    await session.flush()
    await _log(session, b, principal, "issued", f"Issued v{v.number}", [v.change_summary])
    outbox.publish(
        session,
        DomainEvent(
            event_type=VERSION_ISSUED,
            aggregate_type="boq",
            aggregate_id=str(b.id),
            actor_id=principal.user_id,
            payload={
                "project_id": str(b.project_id),
                "version": v.number,
                "quote_ref": b.quote_ref,
            },
        ),
    )
    await session.commit()
    await session.refresh(v)
    return v


# ------------------------------------------------------------------ versions and acceptance


async def list_versions(
    session: AsyncSession, principal: Principal, boq_id: uuid.UUID
) -> list[BoqVersion]:
    await _load(session, principal, boq_id)
    return list(
        await session.scalars(
            select(BoqVersion).where(BoqVersion.boq_id == boq_id).order_by(BoqVersion.number.desc())
        )
    )


async def get_version(
    session: AsyncSession, principal: Principal, boq_id: uuid.UUID, number: int
) -> BoqVersion:
    await _load(session, principal, boq_id)
    v = await session.scalar(
        select(BoqVersion).where(BoqVersion.boq_id == boq_id, BoqVersion.number == number)
    )
    if v is None:
        raise NotFound("That version does not exist.")
    return v


async def compare_versions(
    session: AsyncSession, principal: Principal, boq_id: uuid.UUID, older: int, newer: int
) -> dict[str, Any]:
    """What changed between any two issued versions, not only neighbours. Uses the same diff as
    the change summary stored on each version, so the two always agree."""
    if older == newer:
        raise ValidationFailed("Pick two different versions to compare.")
    older, newer = sorted((older, newer))
    a = await get_version(session, principal, boq_id, older)
    b = await get_version(session, principal, boq_id, newer)
    delta = d.diff(d.Draft.model_validate(a.content), d.Draft.model_validate(b.content))
    return {
        "older": {"number": a.number, "state": a.state, "totals": a.totals},
        "newer": {"number": b.number, "state": b.state, "totals": b.totals},
        "summary": d.summarise(delta),
        "added": delta["added"],
        "removed": delta["removed"],
        "changed": delta["changed"],
    }


def version_view(v: BoqVersion, principal: Principal) -> dict[str, Any]:
    draft = d.Draft.model_validate(v.content)
    comp = d.compute(draft, today_ist())
    numbered = {n.line.id: n for n in d.numbered(draft)}
    lines = []
    for r in comp.lines:
        ln = next(x for x in draft.lines if x.id == r.id).model_dump(mode="json")
        if not principal.has(P.PRICE_READ):
            ln["cost"] = None
        lines.append(
            {
                **ln,
                "ref": r.ref,
                "amount": str(r.amount) if r.amount is not None else None,
                "gst": str(r.gst) if r.gst is not None else None,
                "letter": numbered[r.id].letter,
                "group_id": numbered[r.id].group_id,
            }
        )
    return {
        "id": str(v.id),
        "boq_id": str(v.boq_id),
        "number": v.number,
        "state": v.state,
        "quote_ref": v.quote_ref,
        "change_summary": v.change_summary,
        "delta": v.delta,
        "issued_at": v.issued_at.isoformat(),
        "totals": v.totals,
        "selected_options": v.selected_options,
        "po_number": v.po_number,
        "po_date": str(v.po_date) if v.po_date else None,
        "accepted_at": v.accepted_at.isoformat() if v.accepted_at else None,
        "settings": draft.settings.model_dump(mode="json"),
        "groups": [g.model_dump(mode="json") for g in draft.groups],
        "sections": [s.model_dump(mode="json") for s in draft.sections],
        "lines": lines,
        "terms": draft.terms,
    }


async def accept(
    session: AsyncSession,
    principal: Principal,
    boq_id: uuid.UUID,
    number: int,
    *,
    po_number: str,
    po_date: date,
    po_file_id: uuid.UUID | None,
    selected: dict[str, str],
    note: str | None,
) -> BoqVersion:
    """The customer accepted: lock the version with their purchase order and chosen options."""
    principal.require(P.BOQ_ACCEPT)
    b = await _load(session, principal, boq_id, lock=True)
    v = await get_version(session, principal, boq_id, number)
    latest = await session.scalar(
        select(BoqVersion.number)
        .where(BoqVersion.boq_id == boq_id)
        .order_by(BoqVersion.number.desc())
        .limit(1)
    )
    if v.state != "issued" or v.number != latest:
        raise Conflict("Only the latest issued version can be accepted.", code="not_latest")
    if po_date > today_ist():
        raise ValidationFailed("The purchase order date cannot be in the future.")
    if po_file_id is not None:
        await get_file(session, principal, po_file_id)  # must exist and be visible to the caller
    draft = d.Draft.model_validate(v.content)
    groups = d.option_members(draft)
    chosen = {**draft.selected_options, **selected}
    for g, members in groups.items():
        if chosen.get(g) not in {m.letter for m in members}:
            raise ValidationFailed(
                f"The customer must choose one option for '{g}'.", code="option_required"
            )
    draft.selected_options = {g: chosen[g] for g in groups}
    comp = d.compute(draft, today_ist())
    v.state, v.po_number, v.po_date, v.po_file_id = (
        "accepted",
        po_number.strip(),
        po_date,
        po_file_id,
    )
    v.accepted_by, v.accepted_at, v.accepted_note = principal.user_id, utcnow(), note
    v.selected_options, v.totals = dict(draft.selected_options), comp.totals.model_dump(mode="json")
    v.content = draft.model_dump(mode="json")
    b.status = "accepted"
    await session.flush()
    outbox.publish(
        session,
        artifact_locked_event(
            project_id=b.project_id,
            stage=Stage.BOQ,
            artifact_type=ARTIFACT,
            artifact_id=str(v.id),
            artifact_version=v.number,
            title=f"BOQ {v.quote_ref} v{v.number}, PO {v.po_number}",
            locked_by=principal.user_id,
        ),
    )
    outbox.publish(
        session,
        DomainEvent(
            event_type=BOQ_ACCEPTED,
            aggregate_type="boq",
            aggregate_id=str(b.id),
            actor_id=principal.user_id,
            payload={
                "project_id": str(b.project_id),
                "version_id": str(v.id),
                "version": v.number,
                "po_number": v.po_number,
            },
        ),
    )
    await _log(
        session,
        b,
        principal,
        "accepted",
        f"Accepted v{v.number} with PO {v.po_number}",
        [f"options {dict(draft.selected_options)}"],
    )
    await session.commit()
    await session.refresh(v)
    return v


async def reopen(
    session: AsyncSession, principal: Principal, boq_id: uuid.UUID, reason: str
) -> Boq:
    """After the project is returned to the BOQ stage, start a new draft from the accepted
    version. The accepted version stays as it was."""
    principal.require(P.BOQ_EDIT)
    b = await _load(session, principal, boq_id, lock=True)
    if b.status != "accepted":
        raise Conflict("Only an accepted BOQ needs reopening.", code="not_accepted")
    project = await get_project_ref(session, principal, b.project_id)
    if project.current_stage != Stage.BOQ:
        raise Conflict(
            "Return the project to the BOQ stage first (a director or approver can do this).",
            code="not_boq_stage",
        )
    acc = await session.scalar(
        select(BoqVersion).where(BoqVersion.boq_id == b.id, BoqVersion.state == "accepted")
    )
    if acc is None:
        raise Conflict("No accepted version found.")
    draft = d.Draft.model_validate(acc.content)
    draft.selected_options = {}
    _store(b, draft)
    b.status, b.stage, b.submitted_by, b.pricing_approved_by = "draft", "drafting", None, None
    await _log(session, b, principal, "reopened", reason, [f"from v{acc.number}"])
    await session.commit()
    await session.refresh(b)
    return b


async def edit_log(
    session: AsyncSession, principal: Principal, boq_id: uuid.UUID, limit: int = 100
) -> list[BoqEdit]:
    await _load(session, principal, boq_id)
    return list(
        await session.scalars(
            select(BoqEdit)
            .where(BoqEdit.boq_id == boq_id)
            .order_by(BoqEdit.at.desc())
            .limit(min(limit, 300))
        )
    )


def _forbid(_: Any) -> None:  # pragma: no cover
    raise Forbidden()
