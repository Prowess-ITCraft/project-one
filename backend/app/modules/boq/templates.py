"""BOQ templates: one per gap type, each a list of lines with a quantity rule.

A line names a catalogue item by code, or asks the recommender for the best N products in a
category (which become options A, B). Quantity rules: fixed, per fact (for example endpoints),
per gap (the gap's own count), per site, or a small safe expression. Nothing here uses eval.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core import safeexpr
from app.modules.infra.facts import FACT_CATALOGUE

Role = Literal["supply", "setup", "support", "service", "licence"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QtyRule(_M):
    rule: Literal["fixed", "per_fact", "per_gap", "per_site", "expr"]
    n: int | None = Field(default=None, ge=0, le=100_000)
    fact: str | None = None
    mult: int = Field(default=1, ge=1, le=1000)
    expr: Annotated[str, Field(max_length=200)] | None = None

    @model_validator(mode="after")
    def _check(self) -> QtyRule:
        if self.rule == "fixed" and self.n is None:
            raise ValueError("A fixed quantity needs n.")
        if self.rule == "per_fact" and (self.fact not in FACT_CATALOGUE):
            raise ValueError("per_fact needs a known fact, for example endpoint.count.")
        if self.rule == "expr":
            if not self.expr:
                raise ValueError("An expression rule needs expr.")
            try:
                safeexpr.evaluate(self.expr, _probe_names())
            except safeexpr.ExprError as exc:
                raise ValueError(f"The expression is not valid: {exc}") from exc
        return self


class RecommendSpec(_M):
    category: Annotated[str, Field(max_length=40)]
    count: int = Field(default=2, ge=1, le=3)


class TemplateLine(_M):
    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,40}$")]
    role: Role = "supply"
    item_code: Annotated[str, Field(max_length=40)] | None = None
    recommend: RecommendSpec | None = None
    qty: QtyRule
    option_group: Annotated[str, Field(max_length=40)] | None = None
    section: Annotated[str, Field(max_length=200)] | None = None
    note: Annotated[str, Field(max_length=300)] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> TemplateLine:
        if (self.item_code is None) == (self.recommend is None):
            raise ValueError("Give either item_code or recommend, not both.")
        return self


class TemplateBody(_M):
    title: Annotated[str, Field(min_length=3, max_length=200)]
    lines: list[TemplateLine] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _unique_keys(self) -> TemplateBody:
        keys = [ln.key for ln in self.lines]
        if len(set(keys)) != len(keys):
            raise ValueError("Line keys must be unique within a template.")
        return self


def _probe_names() -> dict[str, Any]:
    names: dict[str, Any] = {k.replace(".", "_"): 1 for k in FACT_CATALOGUE}
    names.update({"gap_qty": 1, "sites": 1, "users": 1})
    return names


def resolve_qty(
    rule: QtyRule, *, facts: dict[str, Any], gap_qty: int | None, sites: int, users: int | None
) -> tuple[int, str | None]:
    """The quantity and, when it cannot be worked out, a short reason a person can act on."""
    if rule.rule == "fixed":
        return int(rule.n or 0), None
    if rule.rule == "per_site":
        return max(sites, 1) * rule.mult, None
    if rule.rule == "per_gap":
        if gap_qty is None:
            return 1, "The gap has no count, so quantity 1 was used. Check it."
        return gap_qty * rule.mult, None
    if rule.rule == "per_fact":
        v = facts.get(rule.fact or "")
        if not isinstance(v, int | float) or isinstance(v, bool):
            return 1, f"'{rule.fact}' is not in the audit, so quantity 1 was used. Check it."
        return math.ceil(v) * rule.mult, None
    names: dict[str, Any] = {
        k.replace(".", "_"): v
        for k, v in facts.items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }
    names.update({"gap_qty": gap_qty, "sites": sites, "users": users})
    try:
        value = safeexpr.evaluate(rule.expr or "0", names)
    except safeexpr.ExprError as exc:
        return 1, f"Quantity rule failed ({exc}); quantity 1 was used. Check it."
    return max(int(value.to_integral_value(rounding="ROUND_CEILING")), 0), None


def validate_body(raw: dict[str, Any]) -> TemplateBody:
    return TemplateBody.model_validate(raw)


def _d(v: Decimal | None) -> str | None:  # pragma: no cover - tiny helper kept for readability
    return None if v is None else str(v)


# ------------------------------------------------------------------ seed templates

SEED: list[dict[str, Any]] = [
    {
        "gap_type": "conflicting_av",
        "title": "Conflicting antivirus: system sanitization",
        "lines": [
            {
                "key": "sanitize",
                "role": "service",
                "item_code": "SVC-SANITIZE",
                "qty": {"rule": "per_fact", "fact": "endpoint.count"},
                "section": "Sanitization, End Point Security & Managed Switch",
                "note": "Per endpoint, matching the sample quotation.",
            },
        ],
    },
    {
        "gap_type": "no_unified_eps",
        "title": "No unified EPS: XDR licence and EPS service",
        "lines": [
            {
                "key": "xdr",
                "role": "licence",
                "item_code": "LIC-ACRONIS-XDR",
                "qty": {"rule": "per_fact", "fact": "endpoint.count"},
                "section": "Sanitization, End Point Security & Managed Switch",
            },
            {
                "key": "eps-service",
                "role": "service",
                "item_code": "SVC-EPS-SETUP",
                "qty": {"rule": "fixed", "n": 1},
                "section": "Sanitization, End Point Security & Managed Switch",
            },
        ],
    },
    {
        "gap_type": "server_xdr",
        "title": "Server XDR",
        "lines": [
            {
                "key": "xdr-server",
                "role": "licence",
                "item_code": "LIC-ACRONIS-XDR",
                "qty": {"rule": "per_fact", "fact": "server.count"},
                "section": "Servers",
            }
        ],
    },
    {
        "gap_type": "unmanaged_switch",
        "title": "Managed switch with setup and support",
        "lines": [
            {
                "key": "switch",
                "role": "supply",
                "item_code": "HW-SW-CISCO-C1300-24T",
                "qty": {"rule": "per_fact", "fact": "switch.unmanaged_count"},
                "section": "Sanitization, End Point Security & Managed Switch",
            },
            {
                "key": "switch-setup",
                "role": "setup",
                "item_code": "SVC-SWITCH-SETUP",
                "qty": {"rule": "per_fact", "fact": "switch.unmanaged_count"},
                "section": "Sanitization, End Point Security & Managed Switch",
            },
        ],
    },
    {
        "gap_type": "firewall_underconfigured",
        "title": "Firewall: reconfigure or replace, with setup and support",
        "lines": [
            {
                "key": "fw-reconfig",
                "role": "service",
                "item_code": "SVC-FW-RECONFIG",
                "qty": {"rule": "fixed", "n": 1},
                "option_group": "firewall",
                "section": "Firewall Options",
            },
            {
                "key": "fw-device",
                "role": "supply",
                "recommend": {"category": "firewall", "count": 2},
                "qty": {"rule": "fixed", "n": 1},
                "option_group": "firewall",
                "section": "Firewall Options",
            },
            {
                "key": "fw-setup",
                "role": "setup",
                "item_code": "SVC-FW-SETUP",
                "qty": {"rule": "fixed", "n": 1},
                "section": "Firewall Options",
            },
            {
                "key": "fw-support",
                "role": "support",
                "item_code": "SVC-FW-SUPPORT",
                "qty": {"rule": "fixed", "n": 1},
                "section": "Firewall Options",
            },
        ],
    },
    {
        "gap_type": "backup_at_risk",
        "title": "NAS and backup",
        "lines": [
            {
                "key": "nas",
                "role": "supply",
                "item_code": "HW-NAS",
                "qty": {"rule": "fixed", "n": 1},
                "section": "Backup and recovery",
            }
        ],
    },
    {
        "gap_type": "no_disaster_recovery",
        "title": "Disaster recovery",
        "lines": [
            {
                "key": "odr",
                "role": "licence",
                "item_code": "SW-PHOENIX-ODR",
                "qty": {"rule": "fixed", "n": 1},
                "section": "Backup and recovery",
            }
        ],
    },
    {
        "gap_type": "server_not_hardened",
        "title": "Server hardening",
        "lines": [
            {
                "key": "harden",
                "role": "service",
                "item_code": "SVC-SRV-HARDEN",
                "qty": {"rule": "per_fact", "fact": "server.count"},
                "section": "Servers",
            }
        ],
    },
    {
        "gap_type": "underspec_hardware",
        "title": "Memory upgrade",
        "lines": [
            {
                "key": "ram",
                "role": "supply",
                "item_code": "HW-RAM-UPG-8GB",
                "qty": {"rule": "per_gap"},
                "section": "Hardware and licences",
            }
        ],
    },
    {
        "gap_type": "outdated_licence",
        "title": "Office licence upgrade",
        "lines": [
            {
                "key": "office",
                "role": "licence",
                "item_code": "LIC-OFFICE-2024",
                "qty": {"rule": "per_gap"},
                "section": "Hardware and licences",
            }
        ],
    },
    {
        "gap_type": "os_end_of_support",
        "title": "Operating system upgrade",
        "lines": [
            {
                "key": "os",
                "role": "licence",
                "item_code": "LIC-WIN-11-PRO",
                "qty": {"rule": "per_gap"},
                "section": "Hardware and licences",
            }
        ],
    },
    {
        "gap_type": "no_second_dc",
        "title": "Server for AD and DC",
        "lines": [
            {
                "key": "addc",
                "role": "supply",
                "item_code": "HW-SRV-ADDC",
                "qty": {"rule": "fixed", "n": 1},
                "section": "Servers",
            }
        ],
    },
    {
        "gap_type": "no_dlp",
        "title": "Data loss prevention",
        "lines": [
            {
                "key": "dlp",
                "role": "licence",
                "item_code": "SW-DLP",
                "qty": {"rule": "fixed", "n": 1},
                "section": "Data protection",
            }
        ],
    },
]
