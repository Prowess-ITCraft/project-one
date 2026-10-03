"""Turn an AuditSnapshot into flat, named facts that rules can test.

A fact is a value or `None`. `None` means the audit does not say (for example the NAS backup
schedule was left blank). Rules treat unknown differently from bad: unknown becomes an item to
verify on site, never a silent pass and never an invented gap.

Affected assets come as name lists, so a gap can say exactly which systems are involved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modules.prismsuite.contracts import AuditSnapshot, DeviceCategory

# Documentation of every fact rules may use. The rule editor validates against this list.
FACT_CATALOGUE: dict[str, str] = {
    "score.security": "PrismSuite security score, 0 to 100",
    "score.high_availability": "PrismSuite high availability score, 0 to 100",
    "score.system_health": "PrismSuite system health score, 0 to 100",
    "score.performance": "PrismSuite performance score, 0 to 100",
    "endpoint.count": "Number of endpoints in the audit",
    "endpoint.multi_av_count": "Systems running more than one antivirus agent",
    "endpoint.eps_count": "Endpoints with the EPS agent detected",
    "endpoint.eps_coverage": "EPS agents as a share of endpoints, 0 to 1",
    "endpoint.xdr_detected": "XDR detected on endpoints",
    "endpoint.ram_low_count": "Systems that need a RAM upgrade",
    "endpoint.office_old_count": "Systems on an outdated Office licence",
    "endpoint.os_eol_count": "Systems on an operating system past end of support",
    "server.count": "Number of servers",
    "server.eps_detected": "EPS detected on servers",
    "server.xdr_detected": "XDR detected on servers",
    "server.dlp_detected": "DLP detected on servers",
    "server.encryption_detected": "Encryption detected on servers",
    "server.hardening_score": "Server hardening benchmark, 0 to 10",
    "server.ha_configured": "Server high availability configured",
    "server.raid_configured": "RAID configured on the server drives",
    "server.ad_present": "An Active Directory domain controller exists",
    "firewall.count": "Number of firewalls",
    "firewall.health_score": "Firewall health score, 0 to 100",
    "firewall.security_score": "Firewall security score, 0 to 100",
    "firewall.ha_configured": "Firewall high availability configured",
    "firewall.ids_ips_enabled": "IDS and IPS enabled on the firewall",
    "firewall.security_services_full": "All firewall security services enabled",
    "firewall.mfa_on_vpn": "Multi-factor authentication on the VPN",
    "firewall.bandwidth_allocation": "Bandwidth allocation configured",
    "nas.count": "Number of NAS devices",
    "nas.used_percent": "NAS storage used, percent",
    "nas.backup_schedule": "A backup schedule is configured",
    "nas.encryption": "NAS data is encrypted",
    "nas.antivirus": "NAS antivirus or malware scan is enabled",
    "nas.snapshot_protection": "NAS snapshot protection is available",
    "nas.restore_drill": "A restore drill has been done",
    "switch.total": "Number of switches",
    "switch.unmanaged_count": "Unmanaged switches",
    "switch.vlan_separation": "Department level network separation in place",
    "router.count": "Number of routers",
    "access_point.count": "Number of access points",
    "dr.recommended": "The report recommends a disaster recovery solution",
    "vulnerability.total": "Vulnerabilities in the audit",
}

_NEG = re.compile(
    r"\b(not\s+(configured|enabled|indicated|available|applicable|done|set)|disabled|none|no|absent|missing)\b",
    re.I,
)
_POS = re.compile(r"^\s*(yes|enabled|configured|implemented|available|active|on|true)\b", re.I)


def yes_no(text: str | None) -> bool | None:
    """Read a report cell as a boolean. Blank or unclear text is unknown (None)."""
    if text is None or not text.strip():
        return None
    if _NEG.search(text):
        return False
    if _POS.search(text):
        return True
    return None


def _num(v: Decimal | int | float | None) -> float | None:
    return None if v is None else float(v)


@dataclass
class FactSheet:
    facts: dict[str, Any] = field(default_factory=dict)
    lists: dict[str, list[str]] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        return self.facts.get(key)


def _score(group: dict[str, Any], key: str) -> float | None:
    s = group.get(key)
    return _num(s.value) if s is not None else None


def _detail(snap: AuditSnapshot, cat: DeviceCategory, *keys: str) -> str | None:
    for d in snap.devices_of(cat):
        for k in keys:
            for name, val in d.details.items():
                if name.strip().lower() == k.lower() and val and val.strip():
                    return val
    return None


def build_facts(snap: AuditSnapshot) -> FactSheet:
    f: dict[str, Any] = {}
    lists: dict[str, list[str]] = {}

    sc = snap.scores
    f["score.security"] = _num(sc.security.value)
    f["score.high_availability"] = _num(sc.high_availability.value)
    f["score.system_health"] = _num(sc.system_health.value)
    f["score.performance"] = _num(sc.performance.value)

    # endpoints
    n_end = snap.assets.endpoints_total or len(snap.endpoints) or None
    f["endpoint.count"] = n_end
    f["endpoint.multi_av_count"] = len(snap.upgrades.conflicting_av)
    lists["endpoint.multi_av_systems"] = [c.system for c in snap.upgrades.conflicting_av]
    eps_end = next(
        (c for c in snap.security_components if c.scope == "endpoint" and c.technology == "EPS"),
        None,
    )
    f["endpoint.eps_count"] = (
        eps_end.quantity if eps_end and eps_end.detected else (0 if eps_end else None)
    )
    f["endpoint.eps_coverage"] = (
        round(f["endpoint.eps_count"] / n_end, 3)
        if n_end and f["endpoint.eps_count"] is not None
        else None
    )
    xdr_end = next(
        (c for c in snap.security_components if c.scope == "endpoint" and c.technology == "XDR"),
        None,
    )
    f["endpoint.xdr_detected"] = xdr_end.detected if xdr_end else None
    f["endpoint.ram_low_count"] = snap.upgrades.ram_upgrade_count
    lists["endpoint.ram_low_systems"] = [
        r.system_key for r in snap.system_recommendations if r.ram_upgrade_needed
    ]
    f["endpoint.office_old_count"] = snap.upgrades.licence_upgrade_count
    lists["endpoint.office_old_systems"] = [
        r.system_key for r in snap.system_recommendations if r.office_upgrade_needed
    ]
    eol = [
        e.system_name
        for e in snap.endpoints
        if e.os and re.search(r"windows\s*(7|8|10)\b", e.os, re.I)
    ]
    f["endpoint.os_eol_count"] = len(eol) if snap.endpoints else None
    lists["endpoint.os_eol_systems"] = eol

    # servers
    servers = snap.devices_of(DeviceCategory.SERVER)
    f["server.count"] = len(servers) or snap.assets.servers
    for key, tech in (("eps", "EPS"), ("xdr", "XDR"), ("dlp", "DLP"), ("encryption", "Encryption")):
        comp = next(
            (c for c in snap.security_components if c.scope == "server" and c.technology == tech),
            None,
        )
        f[f"server.{key}_detected"] = comp.detected if comp else None
    hs = snap.server_hardening_score
    f["server.hardening_score"] = (
        round(float(hs.value) / float(hs.out_of) * 10, 2)
        if hs and hs.value is not None and hs.out_of
        else None
    )
    f["server.ha_configured"] = yes_no(
        _detail(snap, DeviceCategory.SERVER, "High Availability (HA) for Server")
    )
    res_text = " ".join(
        filter(
            None,
            [
                _detail(snap, DeviceCategory.SERVER, "Server Resilience Component-wise"),
                servers[0].configuration if servers else None,
            ],
        )
    )
    f["server.raid_configured"] = True if re.search(r"\braid\b", res_text, re.I) else None
    cfg = servers[0].configuration if servers else ""
    f["server.ad_present"] = (
        True
        if cfg and re.search(r"domain controller|active directory", cfg, re.I)
        else (None if not servers else False)
    )

    # firewall
    fws = snap.devices_of(DeviceCategory.FIREWALL)
    f["firewall.count"] = len(fws) or snap.assets.firewalls
    f["firewall.health_score"] = _score(snap.component_scores.health, "firewall")
    f["firewall.security_score"] = _score(snap.component_scores.security, "firewall")
    f["firewall.ha_configured"] = yes_no(
        _detail(snap, DeviceCategory.FIREWALL, "High Availability")
    )
    ids = _detail(snap, DeviceCategory.FIREWALL, "IDS/IPS")
    f["firewall.ids_ips_enabled"] = yes_no(ids)
    svc = _detail(snap, DeviceCategory.FIREWALL, "Security Service (AV, Antispam, DDoS)")
    f["firewall.security_services_full"] = (
        False if svc and re.search(r"partial", svc, re.I) else yes_no(svc)
    )
    f["firewall.mfa_on_vpn"] = yes_no(_detail(snap, DeviceCategory.FIREWALL, "MFA on VPN"))
    bw = _detail(snap, DeviceCategory.FIREWALL, "Load Balancing and Bandwidth Allocation")
    f["firewall.bandwidth_allocation"] = (
        True
        if bw and re.search(r"allocation (is )?(configured|set)|limits? (set|configured)", bw, re.I)
        else None
    )

    # NAS
    nas = snap.devices_of(DeviceCategory.NAS)
    f["nas.count"] = len(nas) or None
    f["nas.used_percent"] = _num(nas[0].storage_used_percent) if nas else None
    f["nas.backup_schedule"] = yes_no(_detail(snap, DeviceCategory.NAS, "Backup Schedule"))
    f["nas.encryption"] = yes_no(_detail(snap, DeviceCategory.NAS, "Encryption"))
    f["nas.antivirus"] = yes_no(
        _detail(snap, DeviceCategory.NAS, "AV/Malware Scan Enabled?", "AV Status")
    )
    f["nas.snapshot_protection"] = yes_no(
        _detail(snap, DeviceCategory.NAS, "Snapshot Protection Available")
    )
    f["nas.restore_drill"] = yes_no(_detail(snap, DeviceCategory.NAS, "Last Restore Drill Done?"))

    # network
    switches = snap.devices_of(DeviceCategory.SWITCH)
    f["switch.total"] = len(switches) or snap.assets.switches
    unmanaged = [s.brand_model for s in switches if s.managed is False]
    f["switch.unmanaged_count"] = len(unmanaged) if switches else None
    lists["switch.unmanaged"] = unmanaged
    f["switch.vlan_separation"] = None  # a PrismSuite report does not state VLAN layout
    f["router.count"] = len(snap.devices_of(DeviceCategory.ROUTER)) or snap.assets.routers
    f["access_point.count"] = snap.assets.access_points

    f["dr.recommended"] = any(r.area.strip().upper() == "DR" for r in snap.recommendations)
    f["vulnerability.total"] = snap.vulnerabilities.total
    return FactSheet(facts=f, lists=lists)
