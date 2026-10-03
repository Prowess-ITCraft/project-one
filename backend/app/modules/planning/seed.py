"""Starter task library and target-configuration templates.

Durations are planning estimates in minutes and are editable by the Director and technical lead.
The library is keyed by the BOQ template line key (for example `sanitize`, `fw-setup`), so a BOQ
line maps to a task without guessing. Lines with no template get a generic delivery task.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.planning.models import ConfigTemplate, TaskTemplate

PHOTO = {"type": "photo", "label": "Photo of the device with its label", "required": True}
SERIAL = {"type": "serial", "label": "Serial number", "required": True}
SHOT = {"type": "screenshot", "label": "Screenshot of the finished setting", "required": True}
EXPORT = {"type": "config_export", "label": "Configuration export", "required": True}

TASKS: list[dict[str, Any]] = [
    {
        "key": "sanitize",
        "title": "Sanitize system: remove extra antivirus agents",
        "minutes_fixed": 0,
        "minutes_per_unit": 45,
        "split_per_unit": True,
        "device_type": "endpoint",
        "depends_on_kinds": [],
        "steps": [
            "Back up anything the user cannot lose",
            "List the installed security agents",
            "Uninstall every agent except the one to keep",
            "Restart and confirm the system is stable",
        ],
        "evidence": [
            {"type": "screenshot", "label": "Installed programs before", "required": True},
            {"type": "screenshot", "label": "Installed programs after", "required": True},
        ],
    },
    {
        "key": "xdr",
        "title": "Activate the XDR licences",
        "minutes_fixed": 60,
        "minutes_per_unit": 0,
        "split_per_unit": False,
        "device_type": None,
        "depends_on_kinds": [],
        "steps": [
            "Create the tenant",
            "Apply the licences",
            "Confirm the console shows the licences",
        ],
        "evidence": [SHOT],
    },
    {
        "key": "eps-service",
        "title": "Set up the endpoint protection service and deploy agents",
        "minutes_fixed": 120,
        "minutes_per_unit": 15,
        "split_per_unit": False,
        "device_type": "endpoint",
        "depends_on_kinds": ["sanitize", "xdr"],
        "steps": [
            "Configure policies in the console",
            "Deploy the agent to each endpoint",
            "Confirm every endpoint reports healthy",
        ],
        "evidence": [
            {
                "type": "screenshot",
                "label": "Console showing all endpoints protected",
                "required": True,
            }
        ],
    },
    {
        "key": "xdr-server",
        "title": "Deploy XDR on the server",
        "minutes_fixed": 90,
        "minutes_per_unit": 30,
        "split_per_unit": False,
        "device_type": "server",
        "depends_on_kinds": ["harden", "xdr"],
        "steps": [
            "Install the agent",
            "Apply the server policy",
            "Confirm the server reports healthy",
        ],
        "evidence": [SHOT],
    },
    {
        "key": "switch",
        "title": "Install the managed switch",
        "minutes_fixed": 90,
        "minutes_per_unit": 45,
        "split_per_unit": False,
        "requires_downtime": True,
        "device_type": "switch",
        "depends_on_kinds": [],
        "steps": [
            "Rack and power the switch",
            "Move the cables one by one",
            "Confirm links are up",
        ],
        "evidence": [PHOTO, SERIAL],
    },
    {
        "key": "switch-setup",
        "title": "Configure the managed switch: VLANs, management and firmware",
        "minutes_fixed": 120,
        "minutes_per_unit": 30,
        "split_per_unit": False,
        "device_type": "switch",
        "depends_on_kinds": ["switch"],
        "steps": [
            "Update the firmware",
            "Create the VLANs",
            "Lock down management access",
            "Save the configuration",
        ],
        "evidence": [EXPORT, SHOT],
    },
    {
        "key": "fw-reconfig",
        "title": "Reconfigure the existing firewall",
        "minutes_fixed": 180,
        "minutes_per_unit": 0,
        "split_per_unit": False,
        "requires_downtime": True,
        "device_type": "firewall",
        "depends_on_kinds": [],
        "steps": [
            "Export the current configuration",
            "Apply the new policies",
            "Test internet and VPN access",
        ],
        "evidence": [EXPORT, SHOT],
    },
    {
        "key": "fw-device",
        "title": "Install the new firewall",
        "minutes_fixed": 120,
        "minutes_per_unit": 0,
        "split_per_unit": False,
        "requires_downtime": True,
        "device_type": "firewall",
        "depends_on_kinds": [],
        "steps": [
            "Rack and power the firewall",
            "Connect the WAN and LAN",
            "Confirm it is reachable",
        ],
        "evidence": [PHOTO, SERIAL],
    },
    {
        "key": "fw-setup",
        "title": "Configure the firewall: policies, MFA, IPS and firmware",
        "minutes_fixed": 240,
        "minutes_per_unit": 0,
        "split_per_unit": False,
        "requires_downtime": True,
        "device_type": "firewall",
        "depends_on_kinds": ["fw-device"],
        "steps": [
            "Update the firmware",
            "Apply the policy set and bandwidth allocation",
            "Turn on IPS and MFA for administrators",
            "Test internet, VPN and key applications",
        ],
        "evidence": [EXPORT, SHOT],
    },
    {
        "key": "fw-support",
        "title": "Hand over firewall support and monitoring",
        "minutes_fixed": 45,
        "minutes_per_unit": 0,
        "split_per_unit": False,
        "device_type": None,
        "depends_on_kinds": ["fw-setup", "fw-reconfig"],
        "steps": [
            "Register the device for support",
            "Confirm the customer has the support contacts",
        ],
        "evidence": [SHOT],
    },
    {
        "key": "nas",
        "title": "Install the NAS and set up backup",
        "minutes_fixed": 180,
        "minutes_per_unit": 60,
        "split_per_unit": False,
        "device_type": "nas",
        "depends_on_kinds": [],
        "steps": [
            "Install and power the NAS",
            "Create the volume with the agreed RAID",
            "Schedule the backup jobs",
        ],
        "evidence": [PHOTO, SERIAL, EXPORT],
    },
    {
        "key": "odr",
        "title": "Set up disaster recovery: off-site copy and a restore test",
        "minutes_fixed": 240,
        "minutes_per_unit": 0,
        "split_per_unit": False,
        "device_type": "nas",
        "depends_on_kinds": ["nas"],
        "steps": [
            "Configure the off-site copy",
            "Run a test restore",
            "Record how long the restore took",
        ],
        "evidence": [{"type": "screenshot", "label": "Successful test restore", "required": True}],
    },
    {
        "key": "harden",
        "title": "Harden the server against the audit findings",
        "minutes_fixed": 240,
        "minutes_per_unit": 60,
        "split_per_unit": False,
        "requires_downtime": True,
        "device_type": "server",
        "depends_on_kinds": [],
        "steps": [
            "Apply the security baseline",
            "Install pending patches",
            "Disable unused services",
            "Re-run the hardening check",
        ],
        "evidence": [
            EXPORT,
            {"type": "screenshot", "label": "Hardening score after", "required": True},
        ],
    },
    {
        "key": "ram",
        "title": "Upgrade memory",
        "minutes_fixed": 0,
        "minutes_per_unit": 30,
        "split_per_unit": True,
        "device_type": "endpoint",
        "depends_on_kinds": [],
        "steps": [
            "Shut down and open the system",
            "Fit the memory",
            "Confirm the new size in the operating system",
        ],
        "evidence": [
            PHOTO,
            {"type": "screenshot", "label": "System page showing the new memory", "required": True},
        ],
    },
    {
        "key": "office",
        "title": "Upgrade Office",
        "minutes_fixed": 0,
        "minutes_per_unit": 40,
        "split_per_unit": True,
        "device_type": "endpoint",
        "depends_on_kinds": [],
        "steps": [
            "Remove the old version",
            "Install and activate the new version",
            "Open a document to confirm",
        ],
        "evidence": [
            {"type": "screenshot", "label": "Office account and version page", "required": True}
        ],
    },
    {
        "key": "os",
        "title": "Upgrade the operating system",
        "minutes_fixed": 0,
        "minutes_per_unit": 120,
        "split_per_unit": True,
        "requires_downtime": True,
        "device_type": "endpoint",
        "depends_on_kinds": [],
        "steps": ["Back up user data", "Run the upgrade", "Check applications and drivers"],
        "evidence": [
            {"type": "screenshot", "label": "About page showing the new version", "required": True}
        ],
    },
    {
        "key": "addc",
        "title": "Build the domain controller",
        "minutes_fixed": 360,
        "minutes_per_unit": 0,
        "split_per_unit": False,
        "requires_downtime": True,
        "device_type": "server",
        "depends_on_kinds": ["os"],
        "steps": [
            "Install the server role",
            "Promote to a domain controller",
            "Check replication and DNS",
        ],
        "evidence": [EXPORT, SHOT],
    },
    {
        "key": "dlp",
        "title": "Deploy data loss prevention",
        "minutes_fixed": 180,
        "minutes_per_unit": 10,
        "split_per_unit": False,
        "device_type": None,
        "depends_on_kinds": ["eps-service"],
        "steps": [
            "Create the policies",
            "Deploy to a pilot group",
            "Review alerts and widen the rollout",
        ],
        "evidence": [SHOT],
    },
]

GENERIC = {
    "key": "generic",
    "title": "Deliver",
    "minutes_fixed": 120,
    "minutes_per_unit": 0,
    "split_per_unit": False,
    "device_type": None,
    "depends_on_kinds": [],
    "steps": [
        "Carry out the work described in the BOQ line",
        "Confirm the result with the customer contact",
    ],
    "evidence": [SHOT],
}


def _f(key: str, label: str, expected: str, severity: str, how: str) -> dict[str, str]:
    return {"key": key, "label": label, "expected": expected, "severity": severity, "check": how}


CONFIGS: list[dict[str, Any]] = [
    {
        "device_type": "firewall",
        "title": "Firewall",
        "fields": [
            _f("firmware", "Firmware", "Latest stable release", "major", "config_export"),
            _f("admin_mfa", "Administrator MFA", "Enabled", "critical", "screenshot"),
            _f("ips", "Intrusion prevention", "Enabled", "critical", "screenshot"),
            _f(
                "default_admin",
                "Default admin account",
                "Renamed or disabled",
                "critical",
                "config_export",
            ),
            _f(
                "bandwidth_policy",
                "Bandwidth allocation",
                "Policy applied per department",
                "minor",
                "config_export",
            ),
            _f(
                "ha",
                "High availability",
                "Configured when a second unit is supplied",
                "major",
                "screenshot",
            ),
            _f("logging", "Logging", "Enabled and retained", "minor", "config_export"),
        ],
    },
    {
        "device_type": "switch",
        "title": "Managed switch",
        "fields": [
            _f(
                "managed",
                "Management",
                "Managed, reachable on the management VLAN",
                "critical",
                "screenshot",
            ),
            _f("vlans", "VLAN separation", "One VLAN per department", "major", "config_export"),
            _f("firmware", "Firmware", "Latest stable release", "major", "config_export"),
            _f(
                "mgmt_access",
                "Management access",
                "SSH or HTTPS only, default password changed",
                "critical",
                "config_export",
            ),
            _f("unused_ports", "Unused ports", "Disabled", "minor", "config_export"),
        ],
    },
    {
        "device_type": "nas",
        "title": "NAS and backup",
        "fields": [
            _f("raid", "RAID level", "As agreed (RAID 5 or better)", "critical", "screenshot"),
            _f("encryption", "Encryption at rest", "Enabled", "major", "screenshot"),
            _f(
                "backup_job",
                "Backup job",
                "Scheduled and last run succeeded",
                "critical",
                "screenshot",
            ),
            _f("offsite", "Off-site copy", "Configured", "major", "screenshot"),
            _f("firmware", "Firmware", "Latest stable release", "minor", "screenshot"),
            _f("capacity", "Free space", "Above 30 percent", "minor", "screenshot"),
        ],
    },
    {
        "device_type": "server",
        "title": "Server",
        "fields": [
            _f("hardening", "Hardening score", "At least 8 out of 10", "critical", "screenshot"),
            _f("patches", "Patch level", "No critical patch pending", "major", "screenshot"),
            _f(
                "rdp",
                "Remote desktop",
                "Restricted with network level authentication",
                "major",
                "config_export",
            ),
            _f(
                "agent",
                "Endpoint protection agent",
                "Installed and healthy",
                "critical",
                "screenshot",
            ),
            _f("backup_agent", "Backup", "Included in the backup job", "major", "screenshot"),
        ],
    },
    {
        "device_type": "endpoint",
        "title": "Endpoint",
        "fields": [
            _f(
                "av_count",
                "Security agents",
                "Exactly one, the approved agent",
                "critical",
                "screenshot",
            ),
            _f("ram", "Memory", "At least 8 GB", "minor", "screenshot"),
            _f("office", "Office version", "A supported version", "minor", "screenshot"),
            _f("os", "Operating system", "A supported version", "major", "screenshot"),
        ],
    },
]


async def seed_planning(session: AsyncSession) -> dict[str, int]:
    added = {"task_templates": 0, "config_templates": 0}
    have = set(await session.scalars(select(TaskTemplate.key)))
    for t in [*TASKS, GENERIC]:
        if t["key"] in have:
            continue
        session.add(TaskTemplate(**{"requires_downtime": False, **t}))
        added["task_templates"] += 1
    have_c = set(await session.scalars(select(ConfigTemplate.device_type)))
    for c in CONFIGS:
        if c["device_type"] in have_c:
            continue
        session.add(ConfigTemplate(**c))
        added["config_templates"] += 1
    await session.commit()
    return added
