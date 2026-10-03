"""Response models for the BOQ API, so the web client's types are generated, not hand written."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class LineOut(_Out):
    id: str
    section_id: str
    group_id: str
    ref: str
    number: int = 0
    letter: str | None = None
    option_group: str | None = None
    title: str
    description: str = ""
    inclusions: list[str] = []
    qty: int
    uom: str
    unit_price: str | None = None
    cost: str | None = None
    gst_rate: str
    amount: str | None = None
    gst: str | None = None
    price_source: str
    price_ref: dict[str, Any] | None = None
    manual_price_reason: str | None = None
    hint_price: str | None = None
    hint_note: str | None = None
    item_id: str | None = None
    item_code: str | None = None
    vendor: str | None = None
    stock_status: str | None = None
    eol_date: str | None = None
    alternative_of: str | None = None
    source: dict[str, Any]
    notes: str | None = None
    flags: list[str] = []


class SectionOut(_Out):
    id: str
    group_id: str
    title: str


class GroupOut(_Out):
    id: str
    title: str


class TotalsOut(_Out):
    fixed: str
    options: dict[str, dict[str, str]]
    selected: dict[str, str]
    subtotal_min: str
    subtotal_max: str
    gst_min: str
    gst_max: str
    total_min: str
    total_max: str
    complete: bool


class BoqOut(_Out):
    id: str
    project_id: str
    status: str
    stage: str
    quote_ref: str | None = None
    draft_rev: int
    settings: dict[str, Any]
    groups: list[GroupOut]
    sections: list[SectionOut]
    lines: list[LineOut]
    terms: list[str]
    selected_options: dict[str, str]
    totals: TotalsOut
    blockers: list[str]
    warnings: list[str]
    generation_report: dict[str, Any] = {}
    changes: list[str] | None = None


class VersionViewOut(_Out):
    id: str
    boq_id: str
    number: int
    state: str
    quote_ref: str
    change_summary: str
    delta: dict[str, Any]
    issued_at: str
    totals: dict[str, Any]
    selected_options: dict[str, str]
    po_number: str | None = None
    po_date: str | None = None
    accepted_at: str | None = None
    settings: dict[str, Any]
    groups: list[GroupOut]
    sections: list[SectionOut]
    lines: list[dict[str, Any]]
    terms: list[str]


class VersionRowOut(_Out):
    number: int
    state: str
    quote_ref: str
    change_summary: str
    issued_at: str
    totals: dict[str, Any]
    po_number: str | None = None


class EditRowOut(_Out):
    at: str
    by: str
    action: str
    reason: str
    detail: list[str]
