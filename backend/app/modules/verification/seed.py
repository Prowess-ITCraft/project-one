"""Starting key mappings for SonicWall exports and the default severity policy. Idempotent.

The candidate keys below are NOT confirmed against a real SonicWall export yet (there is none in
the samples). They are stored unverified, so a failure read through them goes to the verifier
instead of sending work back. Confirm them with `/verification/inspect` on the first real export,
then mark them verified.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.verification.models import BrandFieldMap, VerificationSetting

UNCONFIRMED = "Candidate keys; confirm against a real SonicWall export, then mark verified."

SONICWALL: list[dict[str, Any]] = [
    {
        "field_key": "firmware",
        "keys": ["firmwareVersion", "firmware_version", "sonicos_version", "firmware"],
        "rule": {"op": "record"},
    },
    {
        "field_key": "admin_mfa",
        "keys": [
            "adminTwoFactorAuth",
            "admin_two_factor",
            "administration.two_factor.enable",
            "admin_mfa",
        ],
        "rule": {"op": "truthy"},
    },
    {
        "field_key": "ips",
        "keys": [
            "ipsGlobalEnable",
            "ips_enable",
            "security_services.intrusion_prevention.enable",
            "ips",
        ],
        "rule": {"op": "truthy"},
    },
    {
        "field_key": "default_admin",
        "keys": ["adminName", "admin_name", "administration.admin_name"],
        "rule": {"op": "ne", "value": "admin"},
    },
    {
        "field_key": "logging",
        "keys": ["syslogEnable", "syslog_enable", "log.syslog.enable"],
        "rule": {"op": "truthy"},
    },
]

DEFAULT_POLICY: dict[str, Any] = {
    # Open deviations of these severities stop the completion certificate (PRD stage 8).
    "certificate_blocking": ["critical"],
    # Deviations of these severities may not be accepted by a verifier; fix or waive them.
    "not_acceptable": ["critical"],
    "note": "Default policy. Rules beyond critical, major and minor are still to come (ADR 0019).",
}


async def seed_verification(session: AsyncSession) -> dict[str, int]:
    made = {"maps": 0, "policy": 0}
    for m in SONICWALL:
        exists = await session.scalar(
            select(BrandFieldMap.id).where(
                BrandFieldMap.brand == "sonicwall", BrandFieldMap.field_key == m["field_key"]
            )
        )
        if exists:
            continue
        session.add(
            BrandFieldMap(
                brand="sonicwall",
                device_type="firewall",
                field_key=m["field_key"],
                keys=m["keys"],
                rule=m["rule"],
                verified=False,
                note=UNCONFIRMED,
            )
        )
        made["maps"] += 1
    if await session.get(VerificationSetting, "severity_policy") is None:
        session.add(VerificationSetting(key="severity_policy", value=DEFAULT_POLICY))
        made["policy"] = 1
    await session.commit()
    return made
