"""Flatten a PrismSuite AuditSnapshot into long-format facts for the audit findings dataset.

One row per fact: (report, category, key, number or text). The long shape lets reports from
different PrismSuite versions share one dataset and makes "score by customer over time" a
plain group-by. Personal data (user and system names) is deliberately left out.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.modules.prismsuite.snapshot import AuditSnapshot, Score


def _num(v: Decimal | int | None) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def flatten(snap: AuditSnapshot) -> list[dict[str, Any]]:
    h = snap.header
    base = {
        "report_ref": h.report_reference,
        "customer": h.customer_name,
        "audit_date": h.audit_date,
    }
    rows: list[dict[str, Any]] = []

    def add(
        category: str,
        key: str,
        num: Decimal | int | None = None,
        text: str | None = None,
        **extra: Any,
    ) -> None:
        rows.append(
            {
                **base,
                "category": category,
                "key": key,
                "value_num": _num(num),
                "value_text": text,
                **extra,
            }
        )

    def score(cat: str, key: str, s: Score | None) -> None:
        if s is not None and (s.value is not None or s.label):
            add(cat, key, s.value, s.label, out_of=_num(s.out_of))

    sc = snap.scores
    for key in (
        "system_health",
        "it_structure_health",
        "performance",
        "high_availability",
        "security",
    ):
        score("score", key, getattr(sc, key))
    score("score", "server_hardening", snap.server_hardening_score)
    for group, items in (
        ("health", snap.component_scores.health),
        ("high_availability", snap.component_scores.high_availability),
        ("performance", snap.component_scores.performance),
        ("security", snap.component_scores.security),
    ):
        for comp, s in items.items():
            score("component_score", f"{group}.{comp}", s)

    for key, val in snap.assets.model_dump().items():
        if val is not None:
            add("asset_count", key, val)

    up = snap.upgrades
    add("upgrade_need", "ram_upgrades", up.ram_upgrade_count)
    add("upgrade_need", "licence_upgrades", up.licence_upgrade_count)
    add("upgrade_need", "conflicting_antivirus", up.conflicting_av_count)
    for lic in up.licence:
        add("upgrade_detail", f"licence.{lic.current}", lic.count, lic.upgrade_to)
    for r in up.ram:
        add("upgrade_detail", "ram", r.count, r.description)

    for d in snap.devices:
        add(
            "device",
            d.category.value,
            None,
            d.brand_model,
            managed=d.managed,
            used_percent=_num(d.storage_used_percent),
        )

    add("vulnerability_total", "total", snap.vulnerabilities.total)
    for v in snap.vulnerabilities.listed:
        add(
            "vulnerability",
            v.cve_id or "",
            v.cvss,
            v.title,
            severity=v.severity.value if v.severity else None,
        )
    for rec in snap.recommendations:
        add("recommendation", rec.area, None, rec.recommendation)
    return rows
