"""Draft a BOQ from a locked gap register. The engine proposes; people decide.

For every open gap: find its template, work out quantities from the audit facts, pick catalogue
items (or ask the recommender for the best two as options A and B), swap out-of-stock items for
the listed alternative, respect brands the customer excluded, and pull prices from the price
book. A price that is missing or expired is NOT guessed: the line is left unpriced with the last
known price as a hint, for a person to enter by hand.

The result is a normal draft. Every line can be edited, deleted or replaced.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.boq import draft as d
from app.modules.boq.models import BoqTemplate
from app.modules.boq.recommend import DEFAULT_WEIGHTS, Candidate, Context, Ranked, score_candidates
from app.modules.boq.templates import TemplateBody, TemplateLine, resolve_qty
from app.modules.catalogue.contracts import (
    ItemRef,
    PriceQuote,
    find_item_by_code,
    get_item_ref,
    get_market_data,
    get_price_quote,
    list_items_by_category,
    resolve_orderable,
)
from app.modules.customers.contracts import BriefRef, CustomerRef
from app.modules.datasets.contracts import boq_history
from app.modules.identity.contracts import Principal
from app.modules.infra.contracts import GapRef, GapSet

GROUP_FOR = {"high": "High Priority", "consider": "To Consider"}


def _money(v: Decimal | None) -> Decimal | None:
    return None if v is None else Decimal(v).quantize(Decimal("0.01"))


def line_from_item(
    item: ItemRef,
    qty: int,
    quote: PriceQuote | None,
    *,
    section_id: str,
    source: d.Source,
    option_group: str | None,
    swapped_from: str | None = None,
) -> d.Line:
    priced = quote is not None and quote.usable and quote.selling is not None
    hint = None
    hint_note = None
    if quote is not None and not priced and quote.selling is not None:
        hint = _money(quote.selling)
        hint_note = f"Last quoted price, expired {quote.valid_until}. Enter the current price."
    return d.Line(
        section_id=section_id,
        option_group=option_group,
        title=item.name,
        description=item.description or "",
        inclusions=list(item.inclusions),
        qty=qty,
        uom=item.uom,
        unit_price=_money(quote.selling) if priced and quote else None,
        cost=_money(quote.cost) if priced and quote else None,
        gst_rate=item.gst_rate,
        price_source="price_book" if priced else "none",
        price_ref=d.PriceRef(
            price_id=str(quote.price_id) if quote and quote.price_id else None,
            valid_until=quote.valid_until if quote else None,
        )
        if priced
        else None,
        hint_price=hint,
        hint_note=hint_note,
        item_id=str(item.id),
        item_code=item.code,
        vendor=item.vendor_name,
        stock_status=item.stock_status,
        eol_date=item.eol_date or item.eos_date,
        alternative_of=swapped_from,
        source=source,
    )


async def _candidates(
    session: AsyncSession, principal: Principal, category: str, ctx: Context
) -> list[Candidate]:
    items = await list_items_by_category(session, principal, category)
    cands: list[Candidate] = []
    for it in items:
        use, swapped = it, None
        if it.stock_status == "out_of_stock" and it.alternative_item_id:
            use, swapped = await resolve_orderable(session, principal, it.id), it.name
            if use.id == it.id:
                swapped = None
            else:
                use = await get_item_ref(session, principal, use.id)
        quote = await get_price_quote(session, principal, use.id)
        market = await get_market_data(session, principal, use.id)
        cands.append(Candidate(use, quote, market, 0, swapped))
    hist = await boq_history(session, [c.item.name for c in cands])
    for c in cands:
        c.history_count = hist[c.item.name].occurrences
    return cands


async def rank_category(
    session: AsyncSession,
    principal: Principal,
    category: str,
    ctx: Context,
    weights: dict[str, float] | None,
) -> tuple[list[Ranked], list[Any]]:
    cands = await _candidates(session, principal, category, ctx)
    by_id: dict[uuid.UUID, Candidate] = {}
    for c in cands:
        first = by_id.get(c.item.id)
        if first is None:
            by_id[c.item.id] = c
        elif c.swapped_from and not first.swapped_from:
            first.swapped_from = c.swapped_from  # it is also the stand-in for an out-of-stock item
    unique = list(by_id.values())
    return score_candidates(unique, ctx, weights)


async def build_draft(
    session: AsyncSession,
    principal: Principal,
    *,
    gapset: GapSet,
    brief: BriefRef | None,
    customer: CustomerRef,
    templates: dict[str, BoqTemplate],
    company: dict[str, Any],
    weights: dict[str, float] | None,
    today: date,
) -> tuple[d.Draft, dict[str, Any]]:
    facts = gapset.facts
    users = (brief.users_12m or brief.users_now) if brief else None
    users = users or (
        int(facts["endpoint.count"]) if isinstance(facts.get("endpoint.count"), int) else None
    )
    sites = brief.sites if brief else 1
    preferred = brief.preferred_brands if brief else ()
    excluded = brief.excluded_brands if brief else ()

    draft = d.empty_draft(tuple(company.get("groups") or GROUP_FOR.values()))
    by_title = {g.title: g for g in draft.groups}
    hp = by_title.get("High Priority", draft.groups[0])
    tc = by_title.get("To Consider", draft.groups[-1])
    sections: dict[tuple[str, str], d.Section] = {}
    index: dict[tuple[str, str | None, str], d.Line] = {}
    report: dict[str, Any] = {
        "register": gapset.number,
        "matched": [],
        "unmatched": [],
        "swaps": [],
        "excluded": [],
        "unpriced": [],
        "recommendations": {},
        "notes": [],
    }

    def section_for(group: d.Group, title: str) -> d.Section:
        key = (group.id, title)
        if key not in sections:
            s = d.Section(group_id=group.id, title=title)
            sections[key] = s
            draft.sections.append(s)
        return sections[key]

    def add(line: d.Line, gap: GapRef, group: d.Group, dedupe_key: str | None) -> None:
        if dedupe_key:
            for other_group in (hp, tc):
                prev = index.get((dedupe_key, line.option_group, other_group.id))
                if prev is not None:
                    prev.qty = max(prev.qty, line.qty)
                    if gap.code not in prev.source.gap_codes:
                        prev.source.gap_codes.append(gap.code)
                    if group is hp and other_group is tc:  # a high priority gap lifts the line
                        sec = section_for(
                            hp, next(s.title for s in draft.sections if s.id == prev.section_id)
                        )
                        prev.section_id = sec.id
                        index.pop((dedupe_key, line.option_group, tc.id))
                        index[(dedupe_key, line.option_group, hp.id)] = prev
                    return
            index[(dedupe_key, line.option_group, group.id)] = line
        draft.lines.append(line)

    order = {"high": 0, "consider": 1}
    for gap in sorted(gapset.gaps, key=lambda g: (order.get(g.priority, 9), g.code)):
        group = hp if gap.priority == "high" else tc
        tpl = templates.get(gap.gap_type)
        if tpl is None or not tpl.active:
            sec = section_for(group, "To be priced by hand")
            draft.lines.append(
                d.Line(
                    section_id=sec.id,
                    title=gap.title,
                    qty=gap.qty_hint or 1,
                    description=gap.recommendation or "",
                    source=d.Source(
                        kind="unmatched",
                        gap_codes=[gap.code],
                        note="No BOQ template for this gap type",
                    ),
                    notes="No template matched this gap. Choose the product and enter the price.",
                )
            )
            report["unmatched"].append(
                {"gap": gap.code, "gap_type": gap.gap_type, "title": gap.title}
            )
            continue
        body = TemplateBody.model_validate({"title": tpl.title, "lines": tpl.lines})
        gap_qty = gap.qty_hint or (len(gap.affected) or None)
        for tl in body.lines:
            qty, qty_msg = resolve_qty(
                tl.qty, facts=facts, gap_qty=gap_qty, sites=sites, users=users
            )
            if qty_msg:
                report["notes"].append(f"{gap.code} {tl.key}: {qty_msg}")
            sec = section_for(group, tl.section or tpl.title)
            src = d.Source(kind="template", gap_codes=[gap.code], template_key=tl.key)
            if tl.recommend:
                await _add_recommended(
                    session,
                    principal,
                    tl,
                    qty,
                    sec,
                    gap,
                    src,
                    brief,
                    users,
                    preferred,
                    excluded,
                    weights,
                    today,
                    report,
                    add,
                    group,
                )
            else:
                await _add_item(
                    session, principal, tl, qty, sec, gap, src, excluded, report, add, group
                )
            report["matched"].append({"gap": gap.code, "template_line": tl.key, "qty": qty})
    return draft, report


async def _add_item(
    session: AsyncSession,
    principal: Principal,
    tl: TemplateLine,
    qty: int,
    sec: d.Section,
    gap: GapRef,
    src: d.Source,
    excluded: tuple[str, ...],
    report: dict[str, Any],
    add: Any,
    group: d.Group,
) -> None:
    assert tl.item_code
    try:
        item = await find_item_by_code(session, principal, tl.item_code)
    except NotFound:
        add(
            d.Line(
                section_id=sec.id,
                title=f"{tl.item_code} (not in the catalogue)",
                qty=qty,
                source=d.Source(
                    kind="unmatched",
                    gap_codes=[gap.code],
                    template_key=tl.key,
                    note="Item code missing from the catalogue",
                ),
                notes="The template names an item that is not in the catalogue. Choose a product.",
            ),
            gap,
            group,
            None,
        )
        report["unmatched"].append(
            {
                "gap": gap.code,
                "gap_type": gap.gap_type,
                "title": f"Missing catalogue item {tl.item_code}",
            }
        )
        return
    use = await resolve_orderable(session, principal, item.id)
    swapped = None
    if use.id != item.id:
        swapped = item.name
        use = await get_item_ref(session, principal, use.id)
        report["swaps"].append({"from": item.name, "to": use.name, "reason": "out of stock"})
    if use.vendor_name and use.vendor_name.strip().lower() in {x.strip().lower() for x in excluded}:
        add(
            d.Line(
                section_id=sec.id,
                title=f"{use.name}: brand excluded by the customer",
                qty=qty,
                source=d.Source(
                    kind="unmatched",
                    gap_codes=[gap.code],
                    template_key=tl.key,
                    note="Excluded brand",
                ),
                notes=f"The customer excludes {use.vendor_name}. Choose another product.",
            ),
            gap,
            group,
            None,
        )
        report["excluded"].append({"gap": gap.code, "item": use.name, "brand": use.vendor_name})
        return
    quote = await get_price_quote(session, principal, use.id)
    if not quote.usable:
        report["unpriced"].append({"item": use.name, "state": quote.state})
    src = d.Source(
        kind="catalogue" if tl.role == "service" else "template",
        gap_codes=src.gap_codes,
        template_key=tl.key,
        note=tl.note,
    )
    add(
        line_from_item(
            use,
            qty,
            quote,
            section_id=sec.id,
            source=src,
            option_group=tl.option_group,
            swapped_from=swapped,
        ),
        gap,
        group,
        str(use.id),
    )


async def _add_recommended(
    session: AsyncSession,
    principal: Principal,
    tl: TemplateLine,
    qty: int,
    sec: d.Section,
    gap: GapRef,
    src: d.Source,
    brief: BriefRef | None,
    users: int | None,
    preferred: tuple[str, ...],
    excluded: tuple[str, ...],
    weights: dict[str, float] | None,
    today: date,
    report: dict[str, Any],
    add: Any,
    group: d.Group,
) -> None:
    assert tl.recommend
    cat = tl.recommend.category
    budget = (
        Decimal(brief.category_budgets[cat]) if brief and cat in brief.category_budgets else None
    )
    ctx = Context(users=users, preferred=preferred, excluded=excluded, budget=budget, today=today)
    ranked, rejected = await rank_category(session, principal, cat, ctx, weights)
    report["recommendations"][f"{gap.code}:{tl.key}"] = {
        "category": cat,
        "ranked": [
            {
                "item": r.candidate.item.name,
                "score": r.score,
                "reasons": r.reasons,
                "criteria": r.criteria,
            }
            for r in ranked
        ],
        "rejected": [{"item": x.item.name, "reason": x.reason} for x in rejected],
    }
    chosen = ranked[: tl.recommend.count]
    if not chosen:
        add(
            d.Line(
                section_id=sec.id,
                title=f"No {cat} fits the requirements",
                qty=qty,
                option_group=tl.option_group,
                source=d.Source(
                    kind="unmatched",
                    gap_codes=[gap.code],
                    template_key=tl.key,
                    note="No candidate passed the filters",
                ),
                notes="The recommender found no product that passes the filters. Choose one by hand.",
            ),
            gap,
            group,
            None,
        )
        report["unmatched"].append(
            {"gap": gap.code, "gap_type": gap.gap_type, "title": f"No {cat} candidate"}
        )
        return
    for r in chosen:
        if r.candidate.swapped_from:
            report["swaps"].append(
                {
                    "from": r.candidate.swapped_from,
                    "to": r.candidate.item.name,
                    "reason": "out of stock",
                }
            )
        quote = r.candidate.price
        if quote is None or not quote.usable:
            report["unpriced"].append(
                {"item": r.candidate.item.name, "state": quote.state if quote else "missing"}
            )
        s = d.Source(
            kind="recommended",
            gap_codes=[gap.code],
            template_key=tl.key,
            note="; ".join(r.reasons)[:280],
        )
        add(
            line_from_item(
                r.candidate.item,
                qty,
                quote,
                section_id=sec.id,
                source=s,
                option_group=tl.option_group or tl.key,
                swapped_from=r.candidate.swapped_from,
            ),
            gap,
            group,
            str(r.candidate.item.id),
        )


__all__ = ["DEFAULT_WEIGHTS", "build_draft", "line_from_item", "rank_category"]
