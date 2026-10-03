"""The starting ideal-infra rule library, from the whiteboard and the product flow draft.

Each rule says: when this is true about the audit, there is a gap; here is the priority, the
affected assets, the recommendation and the target state. A rule marked `verify` turns an
unknown fact into an item to check on site. Changes after seeding go through the Director.

Run with `python -m app.cli seed`. Idempotent: existing codes are left alone.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_log.contracts import AuditContext, record
from app.modules.infra.models import InfraRule


def _t(fact: str, op: str, value: Any = None) -> dict[str, Any]:
    return {"fact": fact, "op": op, **({"value": value} if value is not None else {})}


RULES: list[dict[str, Any]] = [
    {
        "code": "SEC-AV-CONFLICT",
        "title": "Systems run more than one antivirus agent",
        "component": "endpoint",
        "lens": "security",
        "gap_type": "conflicting_av",
        "priority": "high",
        "when": _t("endpoint.multi_av_count", "gt", 0),
        "affected_list": "endpoint.multi_av_systems",
        "qty_fact": "endpoint.multi_av_count",
        "recommendation": "Remove the extra agents and migrate each system to a single managed EPS agent.",
        "target": "One endpoint security agent per system, managed from one console.",
    },
    {
        "code": "SEC-EPS-COVERAGE",
        "title": "No unified endpoint protection on every system",
        "component": "endpoint",
        "lens": "security",
        "gap_type": "no_unified_eps",
        "priority": "high",
        "when": {
            "any": [
                _t("endpoint.eps_coverage", "lt", 1),
                _t("endpoint.xdr_detected", "eq", False),
                _t("endpoint.multi_av_count", "gt", 0),
            ]
        },
        "qty_fact": "endpoint.count",
        "recommendation": "Deploy EPS with XDR on every endpoint with one administration console and monthly reporting.",
        "target": "EPS and XDR on every endpoint, one console, weekly verification.",
    },
    {
        "code": "SEC-EPS-SERVER",
        "title": "Servers have no extended detection and response",
        "component": "server",
        "lens": "security",
        "gap_type": "server_xdr",
        "priority": "consider",
        "when": _t("server.xdr_detected", "eq", False),
        "qty_fact": "server.count",
        "recommendation": "Extend EPS with XDR to every server.",
        "target": "EPS and XDR on every server.",
    },
    {
        "code": "NET-SW-UNMANAGED",
        "title": "Unmanaged switch: no department level separation",
        "component": "switch",
        "lens": "productivity",
        "gap_type": "unmanaged_switch",
        "priority": "high",
        "when": _t("switch.unmanaged_count", "gt", 0),
        "affected_list": "switch.unmanaged",
        "qty_fact": "switch.unmanaged_count",
        "recommendation": "Replace with a managed switch and separate departments with VLANs.",
        "target": "Managed switches with department level VLAN separation.",
    },
    {
        "code": "SEC-FW-CONFIG",
        "title": "Firewall is under-configured",
        "component": "firewall",
        "lens": "security",
        "gap_type": "firewall_underconfigured",
        "priority": "high",
        "when": {
            "any": [
                _t("firewall.security_score", "lt", 50),
                _t("firewall.security_services_full", "eq", False),
                _t("firewall.mfa_on_vpn", "eq", False),
            ]
        },
        "qty_fact": "firewall.count",
        "recommendation": "Reconfigure the firewall (all security services, MFA on VPN, current firmware) or replace it if it cannot meet the target.",
        "target": "All security services on (antivirus, IPS, web filter), MFA on VPN, current firmware.",
    },
    {
        "code": "RES-FW-HA",
        "title": "Firewall has no high availability",
        "component": "firewall",
        "lens": "resilience",
        "gap_type": "firewall_no_ha",
        "priority": "consider",
        "when": _t("firewall.ha_configured", "eq", False),
        "qty_fact": "firewall.count",
        "company_sizes": ["medium", "large"],
        "recommendation": "Add a second firewall in a high availability pair, or document a tested failover.",
        "target": "High availability pair or a documented failover for the firewall.",
    },
    {
        "code": "RES-NAS-BACKUP",
        "title": "NAS is full or has no backup schedule",
        "component": "nas",
        "lens": "resilience",
        "gap_type": "backup_at_risk",
        "priority": "consider",
        "priority_overrides": [{"when": _t("nas.used_percent", "gte", 95), "priority": "high"}],
        "when": {
            "any": [_t("nas.used_percent", "gte", 85), _t("nas.backup_schedule", "eq", False)]
        },
        "qty_fact": "nas.count",
        "recommendation": "Add capacity and configure backups with a schedule, retention, snapshots and a tested restore.",
        "target": "NAS under 80 percent used, with backup schedule, retention, snapshots and a tested restore.",
    },
    {
        "code": "SEC-NAS-HARDEN",
        "title": "NAS data is not protected",
        "component": "nas",
        "lens": "security",
        "gap_type": "nas_not_hardened",
        "priority": "consider",
        "when": {"any": [_t("nas.encryption", "eq", False), _t("nas.antivirus", "eq", False)]},
        "verify_if_unknown": True,
        "recommendation": "Enable volume encryption, antivirus or malware scanning and current firmware on the NAS.",
        "target": "NAS with encryption, antivirus and current firmware.",
    },
    {
        "code": "RES-DR",
        "title": "No disaster recovery",
        "component": "general",
        "lens": "resilience",
        "gap_type": "no_disaster_recovery",
        "priority": "consider",
        "when": {
            "any": [_t("dr.recommended", "eq", True), _t("score.high_availability", "lt", 60)]
        },
        "recommendation": "Add an on-demand disaster recovery solution with a written and tested recovery plan.",
        "target": "Disaster recovery with a tested recovery plan.",
    },
    {
        "code": "SEC-SRV-HARDEN",
        "title": "Server is not hardened",
        "component": "server",
        "lens": "security",
        "gap_type": "server_not_hardened",
        "priority": "high",
        "when": _t("server.hardening_score", "lt", 5),
        "qty_fact": "server.count",
        "recommendation": "Apply a hardening baseline: security updates, Secure Boot, account and port review.",
        "target": "Server hardened to a benchmark of at least 7 out of 10.",
    },
    {
        "code": "PROD-RAM-LOW",
        "title": "Systems below the memory the software needs",
        "component": "endpoint",
        "lens": "productivity",
        "gap_type": "underspec_hardware",
        "priority": "consider",
        "when": _t("endpoint.ram_low_count", "gt", 0),
        "affected_list": "endpoint.ram_low_systems",
        "qty_fact": "endpoint.ram_low_count",
        "recommendation": "Upgrade memory on the listed systems.",
        "target": "Every system meets the memory its software needs.",
    },
    {
        "code": "PROD-OFFICE-OLD",
        "title": "Outdated Office licence",
        "component": "endpoint",
        "lens": "productivity",
        "gap_type": "outdated_licence",
        "priority": "consider",
        "when": _t("endpoint.office_old_count", "gt", 0),
        "affected_list": "endpoint.office_old_systems",
        "qty_fact": "endpoint.office_old_count",
        "recommendation": "Upgrade the listed systems to a supported Office licence.",
        "target": "Supported Office licence on every system.",
    },
    {
        "code": "SEC-OS-EOL",
        "title": "Systems on an unsupported operating system",
        "component": "endpoint",
        "lens": "security",
        "gap_type": "os_end_of_support",
        "priority": "high",
        "when": _t("endpoint.os_eol_count", "gt", 0),
        "affected_list": "endpoint.os_eol_systems",
        "qty_fact": "endpoint.os_eol_count",
        "recommendation": "Move the listed systems to a supported operating system, or replace the hardware if it cannot run one.",
        "target": "Every system on a supported operating system.",
    },
    {
        "code": "SEC-DLP",
        "title": "No data loss prevention",
        "component": "server",
        "lens": "security",
        "gap_type": "no_dlp",
        "priority": "consider",
        "when": _t("server.dlp_detected", "eq", False),
        "company_sizes": ["medium", "large"],
        "budget_tiers": ["standard", "premium"],
        "recommendation": "Add data loss prevention to control copying of business data.",
        "target": "DLP on servers and endpoints.",
    },
    {
        "code": "RES-AD-SECOND",
        "title": "Single domain controller",
        "component": "server",
        "lens": "resilience",
        "gap_type": "no_second_dc",
        "priority": "consider",
        "when": {"all": [_t("server.ad_present", "eq", True), _t("server.count", "lte", 1)]},
        "company_sizes": ["small", "medium", "large"],
        "recommendation": "Add a second server for AD and DC so logins survive the loss of one server.",
        "target": "Two domain controllers, with RAID protected drives and redundant power.",
    },
    {
        "code": "RES-SRV-REDUNDANCY",
        "title": "Confirm server drive and power redundancy",
        "component": "server",
        "lens": "resilience",
        "gap_type": "server_redundancy",
        "priority": "consider",
        "when": _t("server.raid_configured", "eq", False),
        "verify_if_unknown": True,
        "recommendation": "Confirm RAID level, redundant power supply and memory channel layout on site; add what is missing.",
        "target": "RAID protected drives, redundant power supply, dual channel memory.",
    },
    {
        "code": "PROD-FW-BANDWIDTH",
        "title": "Confirm bandwidth allocation",
        "component": "firewall",
        "lens": "productivity",
        "gap_type": "bandwidth_policy",
        "priority": "consider",
        "when": _t("firewall.bandwidth_allocation", "eq", False),
        "verify_if_unknown": True,
        "recommendation": "Confirm whether bandwidth is allocated per department or user, and configure it if not.",
        "target": "Bandwidth allocation per department and user.",
    },
    {
        "code": "PROD-NET-SEPARATION",
        "title": "Confirm department level network separation",
        "component": "switch",
        "lens": "productivity",
        "gap_type": "network_separation",
        "priority": "consider",
        "when": _t("switch.vlan_separation", "eq", False),
        "verify_if_unknown": True,
        "recommendation": "Confirm VLAN layout on site; separate departments if they share one network.",
        "target": "Department level VLAN separation.",
    },
]

SIZES = ["micro", "small", "medium", "large"]
BUDGETS = ["essential", "standard", "premium"]


async def seed_rules(session: AsyncSession) -> int:
    n = 0
    for r in RULES:
        if await session.scalar(select(InfraRule.id).where(InfraRule.code == r["code"])):
            continue
        session.add(
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
            )
        )
        n += 1
    if n:
        await session.flush()
        await record(
            session,
            AuditContext.system("seed"),
            action="seed_rules",
            entity_type="infra_rules",
            entity_id="seed",
            after={"created": n},
            only_changes=False,
        )
    await session.commit()
    return n
