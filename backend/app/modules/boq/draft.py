"""The BOQ draft: a strict document model, edit operations, numbering, totals and checks.

Everything here is pure (no database). The service loads and saves the draft and adds catalogue
and price-book facts. A person can change anything; the model only makes sure the result is
consistent, totals are right, and problems are named.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.core.money import Amount, NonNegativeAmount, RatePercent, gst_amount, line_amount, quantize

PriceSource = Literal["price_book", "manual", "none"]
EXPIRING_DAYS = 2
MAX_LINES = 400


def new_id() -> str:
    return uuid.uuid4().hex[:10]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_M):
    kind: Literal["template", "catalogue", "manual", "recommended", "unmatched"] = "manual"
    gap_codes: list[str] = Field(default_factory=list)
    template_key: str | None = None
    note: str | None = None


class PriceRef(_M):
    price_id: str | None = None
    valid_until: date | None = None
    quoted_on: date | None = None
    supplier: str | None = None


class Line(_M):
    id: str = Field(default_factory=new_id)
    section_id: str
    option_group: str | None = None
    title: Annotated[str, Field(min_length=1, max_length=300)]
    description: Annotated[str, Field(max_length=2000)] = ""
    inclusions: list[Annotated[str, Field(max_length=300)]] = Field(
        default_factory=list, max_length=60
    )
    qty: Annotated[int, Field(ge=0, le=1_000_000)] = 1
    uom: Annotated[str, Field(min_length=1, max_length=20)] = "nos"
    unit_price: NonNegativeAmount | None = None
    cost: NonNegativeAmount | None = None
    gst_rate: RatePercent = Decimal("18.00")
    price_source: PriceSource = "none"
    price_ref: PriceRef | None = None
    manual_price_reason: Annotated[str, Field(max_length=300)] | None = None
    hint_price: NonNegativeAmount | None = None
    hint_note: Annotated[str, Field(max_length=300)] | None = None
    item_id: str | None = None
    item_code: str | None = None
    vendor: str | None = None
    stock_status: str | None = None
    eol_date: date | None = None
    alternative_of: str | None = None
    source: Source = Field(default_factory=Source)
    notes: Annotated[str, Field(max_length=1000)] | None = None


class Section(_M):
    id: str = Field(default_factory=new_id)
    group_id: str
    title: Annotated[str, Field(min_length=1, max_length=200)]


class Group(_M):
    id: str = Field(default_factory=new_id)
    title: Annotated[str, Field(min_length=1, max_length=80)]


class Party(_M):
    name: str = ""
    address_lines: list[str] = Field(default_factory=list, max_length=6)


class Settings(_M):
    quote_date: date | None = None
    validity_days: int = Field(default=5, ge=1, le=365)
    gst_default: RatePercent = Decimal("18.00")
    show_totals: bool = False
    show_gst_rows: bool = False
    intro: Annotated[str, Field(max_length=500)] = ""
    customer: Party = Field(default_factory=Party)
    signatory_name: Annotated[str, Field(max_length=120)] = ""
    signatory_designation: Annotated[str, Field(max_length=120)] = ""
    budget_ceiling: Amount | None = None


class Draft(_M):
    settings: Settings = Field(default_factory=Settings)
    groups: list[Group] = Field(default_factory=list, max_length=8)
    sections: list[Section] = Field(default_factory=list, max_length=60)
    lines: list[Line] = Field(default_factory=list, max_length=MAX_LINES)
    terms: list[Annotated[str, Field(max_length=600)]] = Field(default_factory=list, max_length=40)
    selected_options: dict[str, str] = Field(default_factory=dict)


def empty_draft(groups: tuple[str, ...] = ("High Priority", "To Consider")) -> Draft:
    return Draft(groups=[Group(title=t) for t in groups])


class OpError(ValueError):
    def __init__(self, message: str, code: str = "boq_op_invalid") -> None:
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ operations

LINE_FIELDS = {
    "title",
    "description",
    "inclusions",
    "qty",
    "uom",
    "unit_price",
    "cost",
    "gst_rate",
    "option_group",
    "notes",
    "manual_price_reason",
    "vendor",
    "stock_status",
}


class AddSection(_M):
    op: Literal["add_section"] = "add_section"
    group_id: str
    title: str = Field(min_length=1, max_length=200)
    index: int | None = None


class UpdateSection(_M):
    op: Literal["update_section"] = "update_section"
    id: str
    title: str | None = Field(default=None, min_length=1, max_length=200)
    group_id: str | None = None


class DeleteSection(_M):
    op: Literal["delete_section"] = "delete_section"
    id: str
    move_lines_to: str | None = None


class AddLine(_M):
    op: Literal["add_line"] = "add_line"
    section_id: str
    index: int | None = None
    line: dict[str, Any]


class UpdateLine(_M):
    op: Literal["update_line"] = "update_line"
    id: str
    fields: dict[str, Any] = Field(min_length=1)


class DeleteLine(_M):
    op: Literal["delete_line"] = "delete_line"
    id: str


class MoveLine(_M):
    op: Literal["move_line"] = "move_line"
    id: str
    section_id: str
    index: int | None = None


class AddGroup(_M):
    op: Literal["add_group"] = "add_group"
    title: str = Field(min_length=1, max_length=80)
    index: int | None = None


class UpdateGroup(_M):
    op: Literal["update_group"] = "update_group"
    id: str
    title: str = Field(min_length=1, max_length=80)


class DeleteGroup(_M):
    op: Literal["delete_group"] = "delete_group"
    id: str
    move_sections_to: str | None = None


class UpdateSettings(_M):
    op: Literal["update_settings"] = "update_settings"
    fields: dict[str, Any] = Field(min_length=1)


class SetTerms(_M):
    op: Literal["set_terms"] = "set_terms"
    terms: list[str] = Field(max_length=40)


class SetOption(_M):
    op: Literal["set_option"] = "set_option"
    group: str
    letter: str | None = None


Op = Annotated[
    AddSection
    | UpdateSection
    | DeleteSection
    | AddLine
    | UpdateLine
    | DeleteLine
    | MoveLine
    | AddGroup
    | UpdateGroup
    | DeleteGroup
    | UpdateSettings
    | SetTerms
    | SetOption,
    Field(discriminator="op"),
]
OPS: TypeAdapter[list[Op]] = TypeAdapter(list[Op])


def _sec(d: Draft, sid: str) -> Section:
    for s in d.sections:
        if s.id == sid:
            return s
    raise OpError(f"There is no section '{sid}'.")


def _line(d: Draft, lid: str) -> Line:
    for ln in d.lines:
        if ln.id == lid:
            return ln
    raise OpError(f"There is no line '{lid}'.")


def _insert_at(seq: list[Any], item: Any, index: int | None) -> None:
    if index is None or index >= len(seq):
        seq.append(item)
    else:
        seq.insert(max(index, 0), item)


def _place_line(d: Draft, line: Line, section_id: str, index: int | None) -> None:
    """Insert `line` so that, among lines of its section, it sits at `index`."""
    in_section = [i for i, x in enumerate(d.lines) if x.section_id == section_id]
    if index is None or index >= len(in_section):
        pos = (in_section[-1] + 1) if in_section else _section_end_position(d, section_id)
    else:
        pos = in_section[max(index, 0)]
    d.lines.insert(pos, line)


def _section_end_position(d: Draft, section_id: str) -> int:
    order = {s.id: i for i, s in enumerate(d.sections)}
    me = order[section_id]
    later = [i for i, x in enumerate(d.lines) if order.get(x.section_id, -1) > me]
    return later[0] if later else len(d.lines)


def _set_line_fields(ln: Line, fields: dict[str, Any], *, creating: bool = False) -> None:
    bad = set(fields) - LINE_FIELDS
    if bad:
        raise OpError(f"These line fields cannot be changed here: {', '.join(sorted(bad))}.")
    data = ln.model_dump()
    priced_by_hand = "unit_price" in fields
    data.update(fields)
    if priced_by_hand and fields["unit_price"] is not None:
        reason = (data.get("manual_price_reason") or "").strip()
        if len(reason) < 3:
            raise OpError(
                "A price entered by hand needs a short reason, for example the quote it came from.",
                "manual_price_reason",
            )
        data["price_source"], data["price_ref"], data["manual_price_reason"] = (
            "manual",
            None,
            reason,
        )
    elif priced_by_hand:
        data["price_source"], data["price_ref"], data["manual_price_reason"] = "none", None, None
    try:
        new = Line.model_validate(data)
    except ValueError as exc:
        raise OpError(f"That value is not valid: {str(exc).splitlines()[-1]}") from exc
    for k in Line.model_fields:
        setattr(ln, k, getattr(new, k))


def apply_ops(draft: Draft, raw_ops: list[dict[str, Any]]) -> tuple[Draft, list[str]]:
    """Apply operations to a copy. Returns the new draft and a short description per operation.
    All-or-nothing: any error leaves the original untouched."""
    try:
        ops = OPS.validate_python(raw_ops)
    except ValueError as exc:
        raise OpError(f"The edit is not valid: {str(exc).splitlines()[0]}") from exc
    if not ops:
        raise OpError("Nothing to change.")
    d = draft.model_copy(deep=True)
    notes: list[str] = []

    def gids() -> set[str]:
        return {g.id for g in d.groups}

    for op in ops:
        if isinstance(op, AddSection):
            if op.group_id not in gids():
                raise OpError(f"There is no group '{op.group_id}'.")
            _insert_at(d.sections, Section(group_id=op.group_id, title=op.title), op.index)
            notes.append(f"added section {op.title}")
        elif isinstance(op, UpdateSection):
            s = _sec(d, op.id)
            if op.title:
                s.title = op.title
            if op.group_id:
                if op.group_id not in gids():
                    raise OpError(f"There is no group '{op.group_id}'.")
                s.group_id = op.group_id
            notes.append(f"changed section {s.title}")
        elif isinstance(op, DeleteSection):
            s = _sec(d, op.id)
            inside = [x for x in d.lines if x.section_id == s.id]
            if inside and not op.move_lines_to:
                raise OpError(
                    "This section still has lines. Move them to another section or delete them first.",
                    "section_not_empty",
                )
            if op.move_lines_to:
                _sec(d, op.move_lines_to)
                for x in inside:
                    x.section_id = op.move_lines_to
            d.sections = [x for x in d.sections if x.id != s.id]
            notes.append(f"deleted section {s.title}")
        elif isinstance(op, AddLine):
            _sec(d, op.section_id)
            data = {"section_id": op.section_id, **op.line}
            fields = {k: v for k, v in data.items() if k in LINE_FIELDS}
            base = Line(
                section_id=op.section_id,
                title=str(data.get("title") or "New line"),
                **{
                    k: data[k]
                    for k in (
                        "item_id",
                        "item_code",
                        "source",
                        "price_ref",
                        "price_source",
                        "hint_price",
                        "hint_note",
                        "eol_date",
                        "alternative_of",
                    )
                    if k in data
                },
            )
            _set_line_fields(base, fields, creating=True)
            if len(d.lines) >= MAX_LINES:
                raise OpError(f"A BOQ can have at most {MAX_LINES} lines.")
            _place_line(d, base, op.section_id, op.index)
            notes.append(f"added line {base.title}")
        elif isinstance(op, UpdateLine):
            ln = _line(d, op.id)
            _set_line_fields(ln, op.fields)
            notes.append(f"changed line {ln.title}")
        elif isinstance(op, DeleteLine):
            ln = _line(d, op.id)
            d.lines = [x for x in d.lines if x.id != op.id]
            notes.append(f"removed line {ln.title}")
        elif isinstance(op, MoveLine):
            ln = _line(d, op.id)
            _sec(d, op.section_id)
            d.lines = [x for x in d.lines if x.id != op.id]
            ln.section_id = op.section_id
            _place_line(d, ln, op.section_id, op.index)
            notes.append(f"moved line {ln.title}")
        elif isinstance(op, AddGroup):
            _insert_at(d.groups, Group(title=op.title), op.index)
            notes.append(f"added group {op.title}")
        elif isinstance(op, UpdateGroup):
            g = next((x for x in d.groups if x.id == op.id), None)
            if g is None:
                raise OpError(f"There is no group '{op.id}'.")
            g.title = op.title
            notes.append(f"renamed group {op.title}")
        elif isinstance(op, DeleteGroup):
            g = next((x for x in d.groups if x.id == op.id), None)
            if g is None:
                raise OpError(f"There is no group '{op.id}'.")
            inside_secs = [sec for sec in d.sections if sec.group_id == g.id]
            if inside_secs and not op.move_sections_to:
                raise OpError(
                    "This group still has sections. Move them to another group first.",
                    "group_not_empty",
                )
            if op.move_sections_to:
                if op.move_sections_to not in gids() or op.move_sections_to == g.id:
                    raise OpError("Choose another existing group to move the sections to.")
                for sec in inside_secs:
                    sec.group_id = op.move_sections_to
            d.groups = [x for x in d.groups if x.id != g.id]
            notes.append(f"deleted group {g.title}")
        elif isinstance(op, UpdateSettings):
            data = d.settings.model_dump()
            data.update(op.fields)
            try:
                d.settings = Settings.model_validate(data)
            except ValueError as exc:
                raise OpError(f"That setting is not valid: {str(exc).splitlines()[-1]}") from exc
            notes.append("changed settings")
        elif isinstance(op, SetTerms):
            d.terms = [t.strip() for t in op.terms if t.strip()]
            notes.append("changed the terms")
        elif isinstance(op, SetOption):
            letters = {o.letter for o in option_members(d).get(op.group, [])}
            if op.letter is None:
                d.selected_options.pop(op.group, None)
            elif op.letter not in letters:
                raise OpError(f"Option {op.letter} does not exist in group '{op.group}'.")
            else:
                d.selected_options[op.group] = op.letter
            notes.append(f"selected option {op.letter or 'none'} for {op.group}")

    # Re-validate the whole document; drop selections for options that no longer exist.
    try:
        d = Draft.model_validate(d.model_dump())
    except ValueError as exc:
        raise OpError(f"The edit leaves the BOQ invalid: {str(exc).splitlines()[-1]}") from exc
    members = option_members(d)
    d.selected_options = {
        g: ltr
        for g, ltr in d.selected_options.items()
        if any(m.letter == ltr for m in members.get(g, []))
    }
    return d, notes


# ------------------------------------------------------------------ numbering and totals


class Numbered(BaseModel):
    line: Line
    ref: str
    number: int
    letter: str | None
    group_id: str
    section_title: str


def ordered_lines(d: Draft) -> list[tuple[Line, Section, Group]]:
    gorder = {g.id: i for i, g in enumerate(d.groups)}
    groups = {g.id: g for g in d.groups}
    sections = sorted(d.sections, key=lambda s: (gorder.get(s.group_id, 99), d.sections.index(s)))
    out: list[tuple[Line, Section, Group]] = []
    for s in sections:
        for ln in d.lines:
            if ln.section_id == s.id:
                out.append((ln, s, groups[s.group_id]))
    return out


def numbered(d: Draft) -> list[Numbered]:
    """Display numbers: 1, 2, 3 ... and options share a number with letters: 6A, 6B."""
    out: list[Numbered] = []
    n = 0
    option_number: dict[str, int] = {}
    option_count: dict[str, int] = {}
    for ln, s, g in ordered_lines(d):
        if ln.option_group:
            if ln.option_group not in option_number:
                n += 1
                option_number[ln.option_group] = n
                option_count[ln.option_group] = 0
            num = option_number[ln.option_group]
            letter = chr(ord("A") + option_count[ln.option_group])
            option_count[ln.option_group] += 1
            out.append(
                Numbered(
                    line=ln,
                    ref=f"{num}{letter}",
                    number=num,
                    letter=letter,
                    group_id=g.id,
                    section_title=s.title,
                )
            )
        else:
            n += 1
            out.append(
                Numbered(
                    line=ln, ref=str(n), number=n, letter=None, group_id=g.id, section_title=s.title
                )
            )
    return out


def option_members(d: Draft) -> dict[str, list[Numbered]]:
    groups: dict[str, list[Numbered]] = {}
    for x in numbered(d):
        if x.line.option_group:
            groups.setdefault(x.line.option_group, []).append(x)
    return groups


class LineResult(BaseModel):
    id: str
    ref: str
    amount: Amount | None
    gst: Amount | None
    flags: list[str]


class Totals(BaseModel):
    fixed: Amount
    options: dict[str, dict[str, Amount]]
    selected: dict[str, str]
    subtotal_min: Amount
    subtotal_max: Amount
    gst_min: Amount
    gst_max: Amount
    total_min: Amount
    total_max: Amount
    complete: bool  # every option group has a selection, so min equals max


class Computed(BaseModel):
    lines: list[LineResult]
    totals: Totals
    blockers: list[str]
    warnings: list[str]


def _days_left(ref: PriceRef | None, today: date) -> int | None:
    return (ref.valid_until - today).days if ref and ref.valid_until else None


def line_flags(ln: Line, today: date) -> list[str]:
    flags: list[str] = []
    if ln.unit_price is None:
        flags.append("no_price")
    if ln.qty == 0:
        flags.append("zero_qty")
    if ln.price_source == "price_book":
        days = _days_left(ln.price_ref, today)
        if days is not None and days < 0:
            flags.append("price_expired")
        elif days is not None and days <= EXPIRING_DAYS:
            flags.append("price_expiring")
    if ln.price_source == "manual":
        flags.append("manual_price")
    if ln.unit_price is not None and ln.cost is not None and ln.unit_price < ln.cost:
        flags.append("below_cost")
    if ln.stock_status in ("out_of_stock",):
        flags.append("out_of_stock")
    elif ln.stock_status in ("on_order",):
        flags.append("on_order")
    if ln.eol_date and ln.eol_date <= today:
        flags.append("end_of_life")
    if ln.source.kind == "unmatched":
        flags.append("needs_manual")
    return flags


BLOCKING = {"no_price", "price_expired", "zero_qty"}


def compute(d: Draft, today: date) -> Computed:
    nums = numbered(d)
    results: list[LineResult] = []
    amounts: dict[str, Decimal] = {}
    gsts: dict[str, Decimal] = {}
    for x in nums:
        ln = x.line
        amt = line_amount(ln.unit_price, ln.qty) if ln.unit_price is not None else None
        gst = gst_amount(amt, ln.gst_rate) if amt is not None else None
        if amt is not None and gst is not None:
            amounts[ln.id], gsts[ln.id] = amt, gst
        results.append(
            LineResult(id=ln.id, ref=x.ref, amount=amt, gst=gst, flags=line_flags(ln, today))
        )

    fixed_ids = [x.line.id for x in nums if not x.line.option_group]
    fixed = quantize(sum((amounts.get(i, Decimal(0)) for i in fixed_ids), Decimal(0)))
    fixed_gst = quantize(sum((gsts.get(i, Decimal(0)) for i in fixed_ids), Decimal(0)))
    members = option_members(d)
    options: dict[str, dict[str, Decimal]] = {}
    opt_gst: dict[str, dict[str, Decimal]] = {}
    for g, xs in members.items():
        options[g] = {x.letter or "?": amounts.get(x.line.id, Decimal(0)) for x in xs}
        opt_gst[g] = {x.letter or "?": gsts.get(x.line.id, Decimal(0)) for x in xs}
    sub_min = sub_max = fixed
    g_min = g_max = fixed_gst
    complete = True
    for g, by in options.items():
        pick = d.selected_options.get(g)
        if pick and pick in by:
            sub_min += by[pick]
            sub_max += by[pick]
            g_min += opt_gst[g][pick]
            g_max += opt_gst[g][pick]
        else:
            complete = False
            sub_min += min(by.values())
            sub_max += max(by.values())
            g_min += min(opt_gst[g].values())
            g_max += max(opt_gst[g].values())
    totals = Totals(
        fixed=fixed,
        options={g: {k: quantize(v) for k, v in by.items()} for g, by in options.items()},
        selected=dict(d.selected_options),
        subtotal_min=quantize(sub_min),
        subtotal_max=quantize(sub_max),
        gst_min=quantize(g_min),
        gst_max=quantize(g_max),
        total_min=quantize(sub_min + g_min),
        total_max=quantize(sub_max + g_max),
        complete=complete,
    )

    blockers: list[str] = []
    warnings: list[str] = []
    by_id = {x.line.id: x for x in nums}
    for r in results:
        title = by_id[r.id].line.title[:60]
        for f in r.flags:
            msg = {
                "no_price": f"Line {r.ref} has no price: {title}",
                "price_expired": f"Line {r.ref} uses an expired price: {title}",
                "zero_qty": f"Line {r.ref} has quantity 0: {title}",
            }.get(f)
            if msg:
                blockers.append(msg)
            else:
                text = {
                    "price_expiring": f"Line {r.ref} price expires within {EXPIRING_DAYS} days",
                    "manual_price": f"Line {r.ref} has a price entered by hand",
                    "below_cost": f"Line {r.ref} is priced below cost",
                    "out_of_stock": f"Line {r.ref} is out of stock",
                    "on_order": f"Line {r.ref} is on order, not in stock",
                    "end_of_life": f"Line {r.ref} is end of life",
                    "needs_manual": f"Line {r.ref} needs a person to choose the product",
                }.get(f)
                if text:
                    warnings.append(text)
    for g, xs in members.items():
        if len(xs) < 2:
            warnings.append(f"Option group '{g}' has only one option")
    ceiling = d.settings.budget_ceiling
    if ceiling is not None and totals.subtotal_min > ceiling:
        warnings.append(f"Even the lowest total exceeds the customer's budget ceiling of {ceiling}")
    return Computed(lines=results, totals=totals, blockers=blockers, warnings=warnings)


# ------------------------------------------------------------------ version diff


def diff(old: Draft | None, new: Draft) -> dict[str, Any]:
    """A short, honest summary of what changed between two versions."""
    if old is None:
        return {"first": True, "lines": len(new.lines), "added": [], "removed": [], "changed": []}
    o = {ln.id: ln for ln in old.lines}
    n = {ln.id: ln for ln in new.lines}
    changed: list[dict[str, Any]] = []
    for lid, ln in n.items():
        if lid in o:
            a, b = o[lid], ln
            delta = {}
            for k in ("title", "qty", "unit_price", "gst_rate", "option_group"):
                if getattr(a, k) != getattr(b, k):
                    delta[k] = [str(getattr(a, k)), str(getattr(b, k))]
            if delta:
                changed.append({"line": b.title[:80], **delta})
    return {
        "first": False,
        "added": [ln.title[:80] for lid, ln in n.items() if lid not in o],
        "removed": [ln.title[:80] for lid, ln in o.items() if lid not in n],
        "changed": changed,
        "lines": len(new.lines),
    }


def summarise(delta: dict[str, Any]) -> str:
    if delta.get("first"):
        return f"First version, {delta['lines']} lines."
    parts = []
    if delta["added"]:
        parts.append(f"{len(delta['added'])} added")
    if delta["removed"]:
        parts.append(f"{len(delta['removed'])} removed")
    if delta["changed"]:
        parts.append(f"{len(delta['changed'])} changed")
    return (
        ", ".join(parts).capitalize() + "."
        if parts
        else "No line changes (terms or settings only)."
    )
