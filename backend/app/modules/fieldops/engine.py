"""The engine check: actual configuration against the target baseline (ADR 0015).

A driver compares what the engineer recorded for each baseline field with what the plan expects.
Drivers sit behind `ConfigCheckDriver`, chosen per device type. v1 has one driver,
`AnswerDriver`, which judges the engineer's recorded values. Drivers that read a brand's config
export (SonicWall, Sophos, Fortinet, Cisco) are added in phase 9 by registering them here;
nothing else changes.

Outcomes per field: `pass`, `fail` or `not_checked` (the driver cannot judge it, so the verifier
does). The check fails when any critical or major field fails. Minor failures are deviations the
verifier sees, but they do not send the task back on their own.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

BLOCKING = ("critical", "major")

_ON = {"enabled", "enable", "on", "yes", "true", "configured", "active", "done", "present", "set"}
_OFF = {"disabled", "disable", "off", "no", "false", "not configured", "inactive", "absent", "none"}
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class FieldResult:
    key: str
    label: str
    expected: str
    actual: str | None
    severity: str
    outcome: str  # pass | fail | not_checked
    reason: str
    source: str = "answer"  # answer: the value the engineer typed; export: read from a file


@dataclass(frozen=True)
class CheckResult:
    driver: str
    passed: bool
    fields: list[FieldResult] = field(default_factory=list)

    @property
    def deviations(self) -> list[FieldResult]:
        return [f for f in self.fields if f.outcome == "fail"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "passed": self.passed,
            "fields": [f.__dict__ for f in self.fields],
            "deviations": len(self.deviations),
            "not_checked": sum(1 for f in self.fields if f.outcome == "not_checked"),
        }


@dataclass(frozen=True)
class ExportFile:
    """A configuration export the engineer uploaded as evidence."""

    name: str
    data: bytes


@dataclass(frozen=True)
class ExportFacts:
    """What a configuration export says, as flat settings. `brand` is None when no brand parser
    recognised the file but its key and value lines could still be read."""

    brand: str | None
    shape: str  # exp | text | json
    facts: dict[str, str] = field(default_factory=dict)


class ExportReader(Protocol):
    def __call__(self, name: str, data: bytes) -> ExportFacts | None: ...


# Filled by the verification module at start-up, which owns the brand parsers.
EXPORT_READERS: list[ExportReader] = []


def read_export(name: str, data: bytes) -> ExportFacts | None:
    """The first reader that understands the file, or None."""
    for reader in EXPORT_READERS:
        got = reader(name, data)
        if got is not None:
            return got
    return None


class ConfigCheckDriver(Protocol):
    name: str

    async def check(
        self,
        baseline: list[dict[str, Any]],
        actuals: dict[str, Any],
        exports: Sequence[ExportFile] = (),
    ) -> CheckResult: ...


def _num(s: str) -> float | None:
    m = _NUM.search(s.replace(",", ""))
    return float(m.group()) if m else None


def judge(expected: str, actual: str) -> tuple[str, str]:
    """Compare one recorded value with its target. Returns (outcome, reason)."""
    e, a = expected.strip().lower(), actual.strip().lower()
    if not a:
        return "fail", "No value was recorded."
    # "Enabled", "Disabled", "Configured" style targets
    if e in _ON or e in _OFF:
        want_on = e in _ON
        if a in _ON or a in _OFF:
            ok = (a in _ON) == want_on
            return ("pass", "Matches.") if ok else ("fail", f"Expected {expected}, found {actual}.")
        return "not_checked", "The value is not a clear yes or no."
    # "At least 8 GB", "At least 8 out of 10", "Above 30 percent", "At most 5"
    m = re.match(r"(at least|minimum|above|more than|at most|maximum|below|less than)\s+(.*)", e)
    if m:
        target, got = _num(m.group(2)), _num(a)
        if target is None:
            return "not_checked", "The target has no number."
        if got is None:
            return "fail", f"Expected a number ({expected}), found {actual}."
        op = m.group(1)
        ok = {
            "at least": got >= target,
            "minimum": got >= target,
            "above": got > target,
            "more than": got > target,
            "at most": got <= target,
            "maximum": got <= target,
            "below": got < target,
            "less than": got < target,
        }[op]
        return (
            ("pass", f"{got:g} meets {expected}.")
            if ok
            else ("fail", f"{got:g} does not meet {expected}.")
        )
    if e.startswith("no ") and a in _OFF | {"0", "none", "no"}:
        return "pass", "None found, as required."
    if e == a:
        return "pass", "Matches exactly."
    return "not_checked", "This target needs a person to judge it."


class AnswerDriver:
    """v1: judges the values the engineer recorded on site."""

    name = "answers.v1"

    @staticmethod
    def judge_field(f: dict[str, Any], actuals: dict[str, Any]) -> FieldResult:
        raw = actuals.get(f["key"])
        actual = None if raw is None else str(raw.get("value") if isinstance(raw, dict) else raw)
        outcome, reason = judge(f["expected"], actual or "")
        return FieldResult(
            key=f["key"],
            label=f.get("label", f["key"]),
            expected=f["expected"],
            actual=actual,
            severity=f.get("severity", "minor"),
            outcome=outcome,
            reason=reason,
        )

    def check_answers(self, baseline: list[dict[str, Any]], actuals: dict[str, Any]) -> CheckResult:
        out = [self.judge_field(f, actuals) for f in baseline]
        return CheckResult(self.name, passes(out), out)

    async def check(
        self,
        baseline: list[dict[str, Any]],
        actuals: dict[str, Any],
        exports: Sequence[ExportFile] = (),
    ) -> CheckResult:
        return self.check_answers(baseline, actuals)


def passes(fields: Sequence[FieldResult]) -> bool:
    """A check passes unless a critical or major setting failed."""
    return not any(r.outcome == "fail" and r.severity in BLOCKING for r in fields)


DRIVERS: dict[str, ConfigCheckDriver] = {}
DEFAULT_DRIVER: ConfigCheckDriver = AnswerDriver()


def driver_for(device_type: str | None) -> ConfigCheckDriver:
    """The registered driver for a device type, or the answer driver."""
    return DRIVERS.get(device_type or "", DEFAULT_DRIVER)
