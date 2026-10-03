"""AuditSnapshot: the internal, source-independent shape of a PrismSuite audit.

Every parser (Word report V1, V2, ..., a future PrismSuite JSON export) produces this model.
Downstream modules (infra, gaps, BOQ) read only this, so adding a new input format never
touches them. Numbers are Decimal to avoid float drift in scores. Unknown values are None,
and the read report says why.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Score(_M):
    """A score out of `out_of` (100 unless stated). `raw` keeps the report text for review."""

    value: Decimal | None = None
    out_of: Decimal = Decimal(100)
    label: str | None = None  # e.g. "NEEDS ATTENTION", "At Risk"
    ideal_range: str | None = None
    raw: str | None = None


class Header(_M):
    customer_name: str | None = None
    customer_location: str | None = None
    report_reference: str | None = None
    audit_date: date | None = None
    auditor: str | None = None
    auditor_source: str | None = None  # "report" or "document_properties"
    prepared_by: str | None = None


class HeadlineScores(_M):
    system_health: Score = Field(default_factory=Score)
    it_structure_health: Score = Field(default_factory=Score)
    performance: Score = Field(default_factory=Score)
    high_availability: Score = Field(default_factory=Score)
    security: Score = Field(default_factory=Score)


class ComponentScores(_M):
    """Per-component scores keyed by component name, e.g. {"firewall": Score(40)}."""

    health: dict[str, Score] = Field(default_factory=dict)
    high_availability: dict[str, Score] = Field(default_factory=dict)
    performance: dict[str, Score] = Field(default_factory=dict)
    security: dict[str, Score] = Field(default_factory=dict)


class AssetSummary(_M):
    laptops: int | None = None
    desktops: int | None = None
    servers: int | None = None
    firewalls: int | None = None
    backup_devices: int | None = None
    switches: int | None = None
    routers: int | None = None
    access_points: int | None = None
    endpoints_total: int | None = None
    storage_total_tb: Decimal | None = None
    storage_used_tb: Decimal | None = None
    storage_free_tb: Decimal | None = None


class DeviceCategory(StrEnum):
    SERVER = "server"
    FIREWALL = "firewall"
    ROUTER = "router"
    NAS = "nas"
    SWITCH = "switch"
    ACCESS_POINT = "access_point"


class Device(_M):
    category: DeviceCategory
    brand_model: str
    brand: str | None = None
    model: str | None = None
    device_type: str | None = None
    age: str | None = None
    configuration: str | None = None
    managed: bool | None = None  # switches: managed vs unmanaged
    ports: int | None = None
    firmware: str | None = None
    storage_used_percent: Decimal | None = None
    details: dict[str, str | None] = Field(
        default_factory=dict
    )  # parameter -> value from detail tables


class Endpoint(_M):
    user_name: str | None = None
    system_name: str
    system_type: str | None = None  # Laptop / Desktop
    processor: str | None = None
    motherboard: str | None = None
    ram_gb: Decimal | None = None
    drives: str | None = None
    os: str | None = None
    purchase_date: str | None = None
    software: list[str] = Field(default_factory=list)
    antivirus: list[str] = Field(default_factory=list)
    comments: str | None = None


class SystemRecommendation(_M):
    """One row of 'In-Depth Recommendations Per System'. `system_key` is the report's own id."""

    system_key: str
    ram: str | None = None
    ram_upgrade_needed: bool | None = None
    storage: str | None = None
    storage_upgrade_needed: bool | None = None
    os: str | None = None
    os_upgrade_needed: bool | None = None
    office: str | None = None
    office_upgrade_needed: bool | None = None


class CountItem(_M):
    name: str
    count: int | None = None
    category: str | None = None


class SecurityComponent(_M):
    scope: str  # "server" or "endpoint"
    technology: str
    product: str | None = None
    detected: bool
    quantity: int | None = None


class RamUpgrade(_M):
    description: str
    current_gb: Decimal | None = None
    required_gb: Decimal | None = None
    count: int


class LicenceUpgrade(_M):
    current: str
    upgrade_to: str | None = None
    count: int


class OsUpgrade(_M):
    current: str
    upgrade_to: str | None = None
    count: int


class AvReplacement(_M):
    current_av: str
    upgrade_to: str | None = None
    count: int


class ConflictingAv(_M):
    system: str
    products: list[str]
    action: str | None = None


class UpgradeNeeds(_M):
    ram: list[RamUpgrade] = Field(default_factory=list)
    licence: list[LicenceUpgrade] = Field(default_factory=list)
    os: list[OsUpgrade] = Field(default_factory=list)
    endpoint_protection: list[AvReplacement] = Field(default_factory=list)
    conflicting_av: list[ConflictingAv] = Field(default_factory=list)

    @property
    def ram_upgrade_count(self) -> int:
        return sum(r.count for r in self.ram)

    @property
    def licence_upgrade_count(self) -> int:
        return sum(r.count for r in self.licence)

    @property
    def conflicting_av_count(self) -> int:
        return len(self.conflicting_av)


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Vulnerability(_M):
    priority: int | None = None
    cve_id: str | None = None
    title: str
    description: str | None = None
    severity: Severity | None = None
    cvss: Decimal | None = None
    recommendation: str | None = None


class Vulnerabilities(_M):
    total: int | None = None
    listed: list[Vulnerability] = Field(default_factory=list)


class Recommendation(_M):
    area: str
    recommendation: str
    description: str | None = None


class AuditSnapshot(_M):
    schema_version: str = SCHEMA_VERSION
    header: Header = Field(default_factory=Header)
    scores: HeadlineScores = Field(default_factory=HeadlineScores)
    component_scores: ComponentScores = Field(default_factory=ComponentScores)
    server_hardening_score: Score | None = None
    assets: AssetSummary = Field(default_factory=AssetSummary)
    devices: list[Device] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    system_recommendations: list[SystemRecommendation] = Field(default_factory=list)
    os_distribution: list[CountItem] = Field(default_factory=list)
    installed_software: list[CountItem] = Field(default_factory=list)
    security_components: list[SecurityComponent] = Field(default_factory=list)
    upgrades: UpgradeNeeds = Field(default_factory=UpgradeNeeds)
    vulnerabilities: Vulnerabilities = Field(default_factory=Vulnerabilities)
    recommendations: list[Recommendation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def devices_of(self, category: DeviceCategory) -> list[Device]:
        return [d for d in self.devices if d.category == category]


class FieldStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"  # section or table not found
    UNREADABLE = "unreadable"  # found, but the value could not be parsed
    CONFLICT = "conflict"  # the report states different values in different places
    CORRECTED = "corrected"  # a reviewer set the value


class FieldReport(_M):
    path: str  # JSON pointer into the snapshot, e.g. /scores/security/value
    status: FieldStatus
    message: str | None = None
    source: str | None = None  # where in the report, e.g. "table 'IT Security Risk Assessment'"
    required: bool = False
    raw: str | None = None


class ReadReport(_M):
    parser: str
    fields: list[FieldReport] = Field(default_factory=list)
    unknown_sections: list[str] = Field(default_factory=list)
    unknown_tables: list[str] = Field(default_factory=list)

    @property
    def blocking(self) -> list[FieldReport]:
        return [
            f
            for f in self.fields
            if f.required and f.status in (FieldStatus.MISSING, FieldStatus.UNREADABLE)
        ]

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for f in self.fields:
            counts[f.status.value] = counts.get(f.status.value, 0) + 1
        return {"counts": counts, "blocking": len(self.blocking)}
