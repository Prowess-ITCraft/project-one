"""Facts, the condition language and the seeded rule library against the real Shakti audit."""

from __future__ import annotations

import pytest

from app.modules.customers.contracts import BriefRef
from app.modules.infra import dsl, facts
from app.modules.infra.facts import FactSheet, build_facts
from app.modules.infra.models import InfraRule
from app.modules.infra.seed import BUDGETS, RULES, SIZES
from app.modules.infra.service import evaluate_rules, validate_rule_payload
from app.modules.prismsuite.parsers import docx_v1
from tests.helpers import sample_report_path


@pytest.fixture(scope="module")
def sheet() -> FactSheet:
    return build_facts(
        docx_v1.PrismSuiteParserV1().parse(sample_report_path().read_bytes()).snapshot
    )


def _rules() -> list[InfraRule]:
    out = []
    for r in RULES:
        out.append(
            InfraRule(
                code=r["code"],
                title=r["title"],
                component=r["component"],
                lens=r["lens"],
                gap_type=r["gap_type"],
                priority=r["priority"],
                priority_overrides=r.get("priority_overrides", []),
                when=r["when"],
                verify_if_unknown=r.get("verify_if_unknown", False),
                affected_list=r.get("affected_list"),
                qty_fact=r.get("qty_fact"),
                recommendation=r["recommendation"],
                target=r["target"],
                company_sizes=r.get("company_sizes", SIZES),
                budget_tiers=r.get("budget_tiers", BUDGETS),
                rule_version=1,
                active=True,
            )
        )
    return out


def _brief(size: str = "small", budget: str = "standard") -> BriefRef:
    return BriefRef(size, budget, 27, 35, 1, (), (), None, {}, (), ())


# ------------------------------------------------------------------ facts


def test_facts_match_the_shakti_report(sheet: FactSheet) -> None:
    f = sheet.facts
    assert (
        f["endpoint.count"],
        f["endpoint.multi_av_count"],
        f["endpoint.ram_low_count"],
        f["endpoint.office_old_count"],
    ) == (27, 6, 3, 2)
    assert (
        f["nas.used_percent"] == 100.0
        and f["switch.unmanaged_count"] == 1
        and f["server.hardening_score"] == 3.83
    )
    assert f["firewall.ha_configured"] is False and f["firewall.mfa_on_vpn"] is False
    assert f["firewall.security_services_full"] is False  # "Partially Enabled"
    assert f["dr.recommended"] is True and f["score.security"] == 58.7


def test_blank_cells_are_unknown_not_bad(sheet: FactSheet) -> None:
    for k in (
        "nas.backup_schedule",
        "nas.encryption",
        "nas.antivirus",
        "nas.restore_drill",
        "server.raid_configured",
        "switch.vlan_separation",
    ):
        assert sheet.facts[k] is None, k


def test_yes_no_reading() -> None:
    assert facts.yes_no("Not configured; HA mode: None") is False
    assert facts.yes_no("Enabled") is True and facts.yes_no("Yes") is True
    assert (
        facts.yes_no("") is None
        and facts.yes_no(None) is None
        and facts.yes_no("See console") is None
    )
    assert facts.yes_no("Not indicated") is False and facts.yes_no("Disabled by default") is False


# ------------------------------------------------------------------ language


def test_three_valued_logic() -> None:
    s = FactSheet(facts={"a": 5, "b": None})
    t, unk = {"fact": "a", "op": "gt", "value": 1}, {"fact": "b", "op": "gt", "value": 1}
    assert dsl.evaluate(t, s) is True and dsl.evaluate(unk, s) is None
    assert dsl.evaluate({"all": [t, unk]}, s) is None
    assert dsl.evaluate({"all": [{"fact": "a", "op": "lt", "value": 1}, unk]}, s) is False
    assert dsl.evaluate({"any": [t, unk]}, s) is True
    assert dsl.evaluate({"any": [{"fact": "a", "op": "lt", "value": 1}, unk]}, s) is None
    assert dsl.evaluate({"not": unk}, s) is None and dsl.evaluate({"not": t}, s) is False
    assert (
        dsl.evaluate({"fact": "b", "op": "missing"}, s) is True
        and dsl.evaluate({"fact": "a", "op": "exists"}, s) is True
    )
    assert dsl.evaluate({"fact": "a", "op": "in", "value": [1, 5]}, s) is True


@pytest.mark.parametrize(
    "bad",
    [
        {},
        [],
        {"fact": "nope.nothing", "op": "eq", "value": 1},
        {"fact": "nas.used_percent", "op": "__import__", "value": 1},
        {"fact": "nas.used_percent", "op": "gt"},
        {"all": []},
        {"all": [{"fact": "nas.used_percent", "op": "gt", "value": 1}], "x": 1},
        {"fact": "nas.used_percent", "op": "gt", "value": 1, "code": "x"},
    ],
)
def test_invalid_conditions_are_rejected(bad: object) -> None:
    with pytest.raises(dsl.RuleError):
        dsl.validate(bad)


def test_conditions_cannot_be_huge() -> None:
    deep: dict[str, object] = {"fact": "nas.used_percent", "op": "gt", "value": 1}
    for _ in range(10):
        deep = {"not": deep}
    with pytest.raises(dsl.RuleError):
        dsl.validate(deep)
    with pytest.raises(dsl.RuleError):
        dsl.validate(
            {"all": [{"fact": "nas.used_percent", "op": "gt", "value": i} for i in range(60)]}
        )


def test_every_seeded_rule_is_valid() -> None:
    for r in RULES:
        validate_rule_payload({**r, "priority_overrides": r.get("priority_overrides", [])})


# ------------------------------------------------------------------ the rule library on Shakti


def test_shakti_produces_the_gaps_the_brief_expects(sheet: FactSheet) -> None:
    outcomes, _ = evaluate_rules(_rules(), sheet, _brief())
    gaps = {o.rule.gap_type: o for o in outcomes if o.status == "gap"}
    assert {
        "conflicting_av",
        "no_unified_eps",
        "unmanaged_switch",
        "firewall_underconfigured",
        "backup_at_risk",
        "no_disaster_recovery",
        "server_not_hardened",
        "underspec_hardware",
        "outdated_licence",
        "os_end_of_support",
        "no_second_dc",
        "server_xdr",
    } <= set(gaps)
    assert gaps["conflicting_av"].qty == 6 and len(gaps["conflicting_av"].affected) == 6
    assert gaps["underspec_hardware"].qty == 3 and gaps["outdated_licence"].qty == 2
    assert gaps["unmanaged_switch"].affected == ["D-Link DGS-1024C"]
    assert gaps["backup_at_risk"].priority == "high"  # 100 percent used raises it
    assert gaps["no_disaster_recovery"].priority == "consider" and gaps["no_unified_eps"].qty == 27
    # Not applicable to a small company: firewall HA and DLP.
    assert "firewall_no_ha" not in gaps and "no_dlp" not in gaps


def test_unknown_facts_become_verify_items_not_gaps(sheet: FactSheet) -> None:
    outcomes, _ = evaluate_rules(_rules(), sheet, _brief())
    verify = {o.rule.gap_type for o in outcomes if o.status == "verify"}
    assert verify == {
        "nas_not_hardened",
        "server_redundancy",
        "bandwidth_policy",
        "network_separation",
    }


def test_company_size_and_budget_tier_change_the_rules(sheet: FactSheet) -> None:
    big, _ = evaluate_rules(_rules(), sheet, _brief("medium", "standard"))
    types = {o.rule.gap_type for o in big if o.status == "gap"}
    assert {"firewall_no_ha", "no_dlp"} <= types
    lean, _ = evaluate_rules(_rules(), sheet, _brief("medium", "essential"))
    assert "no_dlp" not in {o.rule.gap_type for o in lean}  # DLP is standard and premium only


def test_a_fixed_audit_clears_its_gaps() -> None:
    clean = FactSheet(
        facts={
            "endpoint.multi_av_count": 0,
            "endpoint.eps_coverage": 1.0,
            "endpoint.xdr_detected": True,
            "switch.unmanaged_count": 0,
            "firewall.security_score": 90,
            "firewall.security_services_full": True,
            "firewall.mfa_on_vpn": True,
            "firewall.ha_configured": True,
            "nas.used_percent": 40,
            "nas.backup_schedule": True,
            "dr.recommended": False,
            "score.high_availability": 85,
            "server.hardening_score": 8,
            "server.xdr_detected": True,
            "server.ad_present": True,
            "server.count": 2,
            "endpoint.ram_low_count": 0,
            "endpoint.office_old_count": 0,
            "endpoint.os_eol_count": 0,
            "server.dlp_detected": True,
            "nas.encryption": True,
            "nas.antivirus": True,
            "server.raid_configured": True,
            "firewall.bandwidth_allocation": True,
            "switch.vlan_separation": True,
        }
    )
    outcomes, met = evaluate_rules(_rules(), clean, _brief("large", "premium"))
    assert outcomes == [] and len(met) == len(RULES)
