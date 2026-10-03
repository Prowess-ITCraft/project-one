"""Starting master data for the BOQ engine: templates, company settings and recommendation
weights. Everything here is editable by Admin afterwards. Idempotent."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_log.contracts import AuditContext, record
from app.modules.boq.models import BoqTemplate, CompanySettings, RecoWeights
from app.modules.boq.recommend import DEFAULT_WEIGHTS
from app.modules.boq.templates import SEED

DEFAULT_TERMS = [
    "On the above prices, GST @ {gst}% applicable",
    "Above can be delivered within 1 to 2 weeks from the date of confirmed purchase order with advance",
    "Payments: 100% advance with confirmed Purchase Order",
    "Warranty will be consistent with the manufacturer's warranty policy",
    "Delivery charges extra at actuals for all out of Mumbai orders",
    "Order once processed cannot be cancelled",
    "In case of onsite installation, the engineer's travelling, accommodation and food arrangements are to be made by the customer",
    "Above prices are strictly valid for a period of {validity} days only from the date of this offer. Beyond the time specified, new prices will be applicable",
]

DEFAULT_COMPANY: dict[str, Any] = {
    "legal_name": "Prowess IT Craft Pvt Ltd",
    "brand": "ITCRAFT",
    # The wordmark as on the logo and itcraft.net.in: green IT, blue CRAFT.
    "brand_parts": [{"text": "IT", "color": "#4FCE5D"}, {"text": "CRAFT", "color": "#2C629F"}],
    "logo": "itcraft-logo-icon.svg",  # the shield; the wordmark is drawn in brand colours
    "tagline": "IT Products, IT Infra & Secured Business Continuity Solutions!!",
    "address_lines": ["28/D-1, Jai Shree Krishna Soc, MHADA", "Mulund East, Mumbai - 400 081"],
    "phones": ["8454 079 001", "8454 079 002"],
    "email": "nirav@iitpl.co.in",
    "gstin": "27AAPCP3476M1ZL",
    "quote_prefix": "ITCraft",
    "default_validity_days": 5,
    "gst_default": "18.00",
    "groups": ["High Priority", "To Consider"],
    "terms": DEFAULT_TERMS,
    "intro": "Please find below our offer for {scope} as per your requirements:",
    "signatory_name": "Nirav Nagda",
    "signatory_designation": "Biz Development Manager",
}


async def seed_boq(session: AsyncSession) -> dict[str, int]:
    made = {"templates": 0, "company": 0, "weights": 0}
    for t in SEED:
        if await session.scalar(
            select(BoqTemplate.id).where(BoqTemplate.gap_type == t["gap_type"])
        ):
            continue
        session.add(BoqTemplate(gap_type=t["gap_type"], title=t["title"], lines=t["lines"]))
        made["templates"] += 1
    if await session.get(CompanySettings, "company") is None:
        session.add(CompanySettings(key="company", data=DEFAULT_COMPANY))
        made["company"] = 1
    if await session.get(RecoWeights, "default") is None:
        session.add(RecoWeights(segment="default", weights=DEFAULT_WEIGHTS))
        made["weights"] = 1
    await session.flush()
    if any(made.values()):
        await record(
            session,
            AuditContext.system("seed"),
            action="seed_boq",
            entity_type="boq_master",
            entity_id="seed",
            after=dict(made),
            only_changes=False,
        )
    await session.commit()
    return made
