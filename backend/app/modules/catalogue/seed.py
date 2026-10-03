"""Seed data for the catalogue: categories, vendors, and the items from the two ITCraft sample
BOQs (Shobhaglobs quotation dated 26 September 2026).

Prices come from that quotation, so each one carries the quote's own 5 day validity. They
will show up on the price book work list soon after seeding, which is the intended signal:
a human must confirm or refresh them before a BOQ can be approved. Items from the summary
BOQ that the quotation did not price (server, NAS, ODR, DLP, firewall reconfiguration) are
seeded without a price on purpose.

Run with `python -m app.cli seed`. Idempotent: existing rows are left untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_log.contracts import AuditContext, record
from app.modules.catalogue.models import (
    PRICE_ACTIVE,
    CatalogueItem,
    Category,
    PriceEntry,
    Vendor,
)

CATEGORIES: list[tuple[str, str, str, int]] = [
    ("sanitization", "System sanitization", "service", 10),
    ("endpoint_security", "Endpoint security (EPS / XDR)", "product", 20),
    ("managed_switch", "Managed switch", "product", 30),
    ("firewall", "Firewall", "product", 40),
    ("server", "Server", "product", 50),
    ("nas", "NAS and storage", "product", 60),
    ("backup_dr", "Backup and disaster recovery", "product", 70),
    ("dlp", "Data loss prevention", "product", 80),
    ("memory_upgrade", "Memory upgrade", "product", 90),
    ("office_licence", "Office licence", "product", 100),
    ("os_licence", "Operating system licence", "product", 110),
    ("access_point", "Access point", "product", 120),
    ("setup_service", "Setup and configuration service", "service", 200),
    ("support_service", "Support and management service", "service", 210),
    ("hardening_service", "Hardening service", "service", 220),
]

VENDORS: list[tuple[str, bool]] = [
    ("Acronis", True),
    ("Cisco", True),
    ("Sophos", True),
    ("Fortinet", True),
    ("Synology", False),
    ("Phoenix", False),
    ("ITCraft", True),
]

QUOTE_DATE = date(2026, 9, 26)
QUOTE_VALID_DAYS = 5
SOURCE = "Seed: ITCraft quotation 2627-030, 26 Sep 2026. Cost unknown, set to selling. Confirm."


@dataclass(frozen=True)
class SeedItem:
    code: str
    kind: str
    category: str
    name: str
    vendor: str | None = None
    uom: str = "nos"
    selling: str | None = None
    description: str | None = None
    inclusions: tuple[str, ...] = ()
    attributes: dict[str, object] = field(default_factory=dict)


ITEMS: list[SeedItem] = [
    SeedItem(
        "SVC-SANITIZE",
        "service",
        "sanitization",
        "System sanitization to quarantine and mitigate risks from malicious applications, "
        "malware or unwanted dormant programs",
        "ITCraft",
        "system",
        "500.00",
    ),
    SeedItem(
        "LIC-ACRONIS-XDR",
        "product",
        "endpoint_security",
        "Acronis XDR - Extended Detection and Response, per annum",
        "Acronis",
        "licence",
        "1562.00",
        "Workloads: Servers, VMs, Workstations, Hosting Servers",
    ),
    SeedItem(
        "SVC-EPS-SETUP",
        "service",
        "setup_service",
        "EPS implementation, security set up configuration and one year administration and "
        "management",
        "ITCraft",
        "nos",
        "12000.00",
        inclusions=(
            "Weekly EPS portal verification",
            "Monthly report generation, assessment and submission",
            "All mail communication with the vendor and query handling",
            "Regular relevant firmware updates, verification and patching",
            "All security breach calls handling and management",
            "Every new user's device addition and configuration",
            "Every outgoing user's system scanning, verification and allocation",
            "All EPS support calls",
        ),
    ),
    SeedItem(
        "HW-SW-CISCO-C1300-24T",
        "product",
        "managed_switch",
        "Cisco Catalyst C1300-24T-4G Giga Managed Switch",
        "Cisco",
        "nos",
        "33972.00",
        attributes={"ports": 24, "uplinks": 4, "managed": True},
    ),
    SeedItem(
        "SVC-SWITCH-SETUP",
        "service",
        "setup_service",
        "One time setup, installation and configuration charges inclusive of one year onsite "
        "or remote support for the switch",
        "ITCraft",
        "nos",
        "6000.00",
    ),
    SeedItem(
        "HW-FW-SOPHOS-XGS108",
        "product",
        "firewall",
        "Sophos XGS-108 Firewall with 3 years Xtreme Protection",
        "Sophos",
        "nos",
        "66812.00",
        "Up to 40-50 concurrent users",
        (
            "6 fixed Ethernet GbE copper interfaces",
            "Firewall throughput 12,500 Mbps",
            "VPN throughput 8,250 Mbps",
            "Firewall hardware appliance",
            "Gateway antivirus",
            "Gateway anti-spam",
            "Intrusion prevention system",
            "Web URL filter",
            "Application filtering",
            "VPN, BM and load balancing and failover",
            "Active-Active, Active-Passive, clustering",
        ),
        {
            "concurrent_users_max": 50,
            "firewall_throughput_mbps": 12500,
            "vpn_throughput_mbps": 8250,
        },
    ),
    SeedItem(
        "HW-FW-FORTI-FG40F",
        "product",
        "firewall",
        "FortiGate FG40F UTM with 3 year subscription",
        "Fortinet",
        "nos",
        "109653.00",
        "For 50-60 concurrent users",
        (
            "4 fixed Ethernet GbE copper interfaces plus 1 FortiLink port",
            "Firewall throughput 7.5 Mbps",
            "VPN throughput 490 Mbps",
            "NGFW throughput 800 Mbps",
            "Firewall hardware appliance",
            "Gateway antivirus",
            "Gateway anti-spam",
            "Intrusion prevention system",
            "Web URL filter",
            "Application filtering",
            "VPN, BM and load balancing and failover",
            "Active-Active, Active-Passive, clustering",
        ),
        {"concurrent_users_max": 60, "vpn_throughput_mbps": 490, "ngfw_throughput_mbps": 800},
    ),
    SeedItem(
        "SVC-FW-SETUP",
        "service",
        "setup_service",
        "Firewall one time setup, installation and configuration charges",
        "ITCraft",
        "nos",
        "12000.00",
        inclusions=(
            "Network firewall configuration",
            "SSL VPN configuration for remote users",
            "Multiple ISP configuration and load balancing",
            "Defining content filtering policies",
            "Unwanted sites blocking",
            "Defining and punching policies for network security",
            "Public email domain blocking",
            "Internet bandwidth allocation for all users",
        ),
    ),
    SeedItem(
        "SVC-FW-SUPPORT",
        "service",
        "support_service",
        "One year support charges for VPN firewall",
        "ITCraft",
        "nos",
        "15000.00",
        inclusions=(
            "Add, delete and validate accounts",
            "Redefining controls for existing users",
            "Regular monitoring for failures, assessment and support",
            "Firmware patching for the firewall",
            "SSL VPN accounts management",
            "Monthly cumulative VPN firewall reporting",
            "Regular verification and validation of accounts",
            "Onsite or remote management: breakdown calls",
        ),
    ),
    # From the summary BOQ only: listed, not priced in the quotation.
    SeedItem("SVC-FW-RECONFIG", "service", "setup_service", "Firewall reconfiguration", "ITCraft"),
    SeedItem("HW-SRV-ADDC", "product", "server", "Server for AD/DC"),
    SeedItem("HW-NAS", "product", "nas", "NAS"),
    SeedItem("SW-PHOENIX-ODR", "product", "backup_dr", "Phoenix ODR", "Phoenix"),
    SeedItem("SW-DLP", "product", "dlp", "DLP"),
    SeedItem(
        "SVC-SRV-HARDEN", "service", "hardening_service", "Server hardening", "ITCraft", "server"
    ),
    SeedItem("HW-RAM-UPG-8GB", "product", "memory_upgrade", "Memory upgrade, 8 GB module", None),
    SeedItem(
        "LIC-OFFICE-2024",
        "product",
        "office_licence",
        "Microsoft Office licence, current version",
        None,
        "licence",
    ),
    SeedItem(
        "LIC-WIN-11-PRO",
        "product",
        "os_licence",
        "Windows 11 Professional licence",
        None,
        "licence",
    ),
]


async def seed_catalogue(session: AsyncSession) -> dict[str, int]:
    """Insert whatever is missing. Returns counts of rows created."""
    created = {"categories": 0, "vendors": 0, "items": 0, "prices": 0}

    for code, label, kind, order in CATEGORIES:
        if await session.get(Category, code) is None:
            session.add(Category(code=code, label=label, kind=kind, sort_order=order))
            created["categories"] += 1
    await session.flush()

    vendors: dict[str, Vendor] = {}
    for name, india in VENDORS:
        v = await session.scalar(
            select(Vendor).where(Vendor.name == name, Vendor.deleted_at.is_(None))
        )
        if v is None:
            v = Vendor(name=name, india_support=india, preferred=name == "ITCraft")
            session.add(v)
            created["vendors"] += 1
        vendors[name] = v
    await session.flush()

    valid_until = QUOTE_DATE + timedelta(days=QUOTE_VALID_DAYS)
    for s in ITEMS:
        item = await session.scalar(select(CatalogueItem).where(CatalogueItem.code == s.code))
        if item is None:
            item = CatalogueItem(
                code=s.code,
                kind=s.kind,
                category=s.category,
                vendor_id=vendors[s.vendor].id if s.vendor else None,
                name=s.name,
                description=s.description,
                inclusions=list(s.inclusions),
                uom=s.uom,
                gst_rate=Decimal(18),
                attributes=dict(s.attributes),
            )
            session.add(item)
            await session.flush()
            created["items"] += 1
        if s.selling is not None:
            has_price = await session.scalar(
                select(PriceEntry.id).where(PriceEntry.item_id == item.id).limit(1)
            )
            if has_price is None:
                selling = Decimal(s.selling)
                session.add(
                    PriceEntry(
                        item_id=item.id,
                        supplier="ITCraft quotation",
                        cost=selling,  # the sample quotation shows selling prices only
                        selling=selling,
                        quoted_on=QUOTE_DATE,
                        valid_until=valid_until,
                        source_note=SOURCE,
                        status=PRICE_ACTIVE,
                    )
                )
                created["prices"] += 1
    await session.flush()
    if any(created.values()):
        await record(
            session,
            AuditContext.system("seed"),
            action="seed_catalogue",
            entity_type="catalogue",
            entity_id="seed",
            after=dict(created),
            only_changes=False,
        )
    await session.commit()
    return created
