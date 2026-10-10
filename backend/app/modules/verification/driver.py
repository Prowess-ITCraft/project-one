"""The export-aware configuration check (ADR 0015, 0019), registered with field work for the device
types that have a brand parser. Settings proven by a configuration export are judged from the
export; everything else falls back to the values the engineer recorded.

A failure read through a mapping that is not yet confirmed against a real export never sends the
work back on its own: it is passed to the verifier with the reason. Guessed key names must not
block an engineer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.modules.fieldops.contracts import (
    AnswerDriver,
    CheckResult,
    ExportFile,
    FieldResult,
    passes,
)
from app.modules.verification.exports import apply_rule, parse_export
from app.modules.verification.models import BrandFieldMap


async def load_maps(brands: set[str]) -> dict[tuple[str, str], BrandFieldMap]:
    async with get_sessionmaker()() as s:
        rows = await s.scalars(select(BrandFieldMap).where(BrandFieldMap.brand.in_(brands)))
        return {(m.brand, m.field_key): m for m in rows}


class ExportDriver:
    """Brand exports first, recorded answers for the rest."""

    def __init__(self, device_type: str) -> None:
        self.device_type = device_type
        self.name = "exports.v1"

    async def check(
        self,
        baseline: list[dict[str, Any]],
        actuals: dict[str, Any],
        exports: Sequence[ExportFile] = (),
    ) -> CheckResult:
        answers = AnswerDriver()
        parsed = [p for e in exports if (p := parse_export(e.name, e.data)) is not None]
        if not parsed:
            return answers.check_answers(baseline, actuals)
        facts: dict[str, dict[str, str]] = {}
        for p in parsed:  # a later export of the same brand wins
            facts.setdefault(p.brand, {}).update(p.facts)
        maps = await load_maps(set(facts))
        out: list[FieldResult] = []
        for f in baseline:
            hit = None
            for brand, kv in facts.items():
                m = maps.get((brand, f["key"]))
                if m is None:
                    continue
                key = next((k for k in m.keys if k in kv), None)
                if key is not None:
                    hit = (brand, m, key, kv[key])
                    break
            if hit is None:
                out.append(answers.judge_field(f, actuals))
                continue
            brand, m, key, value = hit
            outcome, reason = apply_rule(m.rule, value)
            reason = f"From the {brand} export, {key} = {value}. {reason}"
            if not m.verified:
                reason += " The key mapping is not confirmed yet."
                if outcome == "fail":
                    outcome = "not_checked"
                    reason += " The verifier decides."
            out.append(
                FieldResult(
                    key=f["key"],
                    label=f.get("label", f["key"]),
                    expected=f["expected"],
                    actual=value[:300],
                    severity=f.get("severity", "minor"),
                    outcome=outcome,
                    reason=reason[:500],
                    source="export",
                )
            )
        brands = "+".join(sorted(facts))
        return CheckResult(f"{brands}.exports.v1", passes(out), out)
