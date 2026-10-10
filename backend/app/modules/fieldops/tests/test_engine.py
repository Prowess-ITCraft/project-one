"""The configuration check (ADR 0015). Pure tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.modules.fieldops import engine
from app.modules.fieldops.service import evidence_plan


@pytest.mark.parametrize(
    ("expected", "actual", "outcome"),
    [
        ("Enabled", "enabled", "pass"),
        ("Enabled", "Yes", "pass"),
        ("Enabled", "off", "fail"),
        ("Disabled", "disabled", "pass"),
        ("Disabled", "On", "fail"),
        ("Configured", "done", "pass"),
        ("Enabled", "partly", "not_checked"),
        ("At least 8 GB", "16 GB", "pass"),
        ("At least 8 GB", "4 GB", "fail"),
        ("At least 8 out of 10", "8.4", "pass"),
        ("At least 8 out of 10", "3.83", "fail"),
        ("Above 30 percent", "30", "fail"),
        ("Above 30 percent", "45 %", "pass"),
        ("At most 5", "2", "pass"),
        ("At least 8 GB", "lots", "fail"),
        ("No critical patch pending", "none", "pass"),
        ("Latest stable release", "7.0.1-5050", "not_checked"),
        ("One VLAN per department", "one vlan per department", "pass"),
        ("Enabled", "", "fail"),
    ],
)
def test_one_value_against_its_target(expected: str, actual: str, outcome: str) -> None:
    assert engine.judge(expected, actual)[0] == outcome


BASELINE = [
    {
        "key": "admin_mfa",
        "label": "Administrator MFA",
        "expected": "Enabled",
        "severity": "critical",
    },
    {
        "key": "firmware",
        "label": "Firmware",
        "expected": "Latest stable release",
        "severity": "major",
    },
    {"key": "logging", "label": "Logging", "expected": "Enabled", "severity": "minor"},
]


def test_a_failed_critical_setting_fails_the_check() -> None:
    r = engine.AnswerDriver().check_answers(
        BASELINE, {"admin_mfa": {"value": "disabled"}, "firmware": "7.0", "logging": "on"}
    )
    assert r.passed is False and [f.key for f in r.deviations] == ["admin_mfa"]
    d = r.as_dict()
    assert d["deviations"] == 1 and d["not_checked"] == 1 and d["driver"] == "answers.v1"


def test_minor_failures_and_unjudged_values_go_to_the_verifier() -> None:
    r = engine.AnswerDriver().check_answers(
        BASELINE, {"admin_mfa": "enabled", "firmware": "7.0", "logging": "off"}
    )
    assert r.passed is True
    assert {f.key: f.outcome for f in r.fields} == {
        "admin_mfa": "pass",
        "firmware": "not_checked",
        "logging": "fail",
    }


def test_a_missing_value_fails() -> None:
    assert engine.AnswerDriver().check_answers(BASELINE[:1], {}).passed is False


def test_drivers_are_chosen_by_device_type() -> None:
    class Strict:
        name = "strict.test"

        async def check(
            self,
            baseline: list[dict[str, Any]],
            actuals: dict[str, Any],
            exports: Sequence[engine.ExportFile] = (),
        ) -> engine.CheckResult:
            return engine.CheckResult(self.name, False)

    # another module (verification) may already have registered a firewall driver
    saved = engine.DRIVERS.pop("firewall", None)
    try:
        assert engine.driver_for("firewall").name == "answers.v1"
        engine.DRIVERS["firewall"] = Strict()
        assert engine.driver_for("firewall").name == "strict.test"
        assert engine.driver_for(None).name == "answers.v1"
    finally:
        engine.DRIVERS.pop("firewall", None)
        if saved is not None:
            engine.DRIVERS["firewall"] = saved


def test_every_run_needs_arrival_and_prechecks_evidence() -> None:
    reqs = evidence_plan(
        [{"type": "config_export", "label": "Export", "required": True}], "firewall"
    )
    assert [(r["stage"], r["type"]) for r in reqs] == [
        ("check_in", "photo"),
        ("prechecks", "config_export"),  # a firewall: the export before any change
        ("prechecks", "note"),
        ("work", "config_export"),
    ]
    assert reqs[1]["snapshot"] is True and "rollback" in reqs[1]["label"]
    assert evidence_plan([], "server")[1]["type"] == "screenshot"  # a server: show the backup
    assert evidence_plan([], None)[1]["type"] == "note"  # an endpoint: say who backed up


def test_brand_drivers_register_through_the_contract() -> None:
    from app.modules.fieldops.contracts import AnswerDriver, register_driver

    register_driver("switch", AnswerDriver())
    try:
        assert engine.driver_for("switch").name == "answers.v1" and "switch" in engine.DRIVERS
    finally:
        engine.DRIVERS.pop("switch")
