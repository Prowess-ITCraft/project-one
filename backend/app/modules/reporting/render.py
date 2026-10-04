"""The completion report and the certificate as HTML and PDF, through the shared renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.documents import RenderedDocument, qr_data_url, render_pdf, template_env
from app.modules.boq.contracts import get_company_profile

_env = template_env(Path(__file__).parent / "html")
SCOPE_ON_CERTIFICATE = 10  # more than this runs into the QR code; the report lists the rest


async def report_context(session: AsyncSession, content: dict[str, Any]) -> dict[str, Any]:
    return {"company": await get_company_profile(session), "c": content}


def render_report_html(ctx: dict[str, Any]) -> str:
    return _env.get_template("report.html").render(**ctx)


def render_report_pdf(ctx: dict[str, Any]) -> RenderedDocument:
    return render_pdf(render_report_html(ctx))


async def certificate_context(
    session: AsyncSession, payload: dict[str, Any], digest: str, verify_url: str, stamp: str | None
) -> dict[str, Any]:
    scope = payload["scope"]
    return {
        "company": await get_company_profile(session),
        "p": payload,
        "scope_shown": scope[:SCOPE_ON_CERTIFICATE],
        "scope_more": max(0, len(scope) - SCOPE_ON_CERTIFICATE),
        "fingerprint": digest[:16],
        "verify_url": verify_url,
        "qr": qr_data_url(verify_url),
        "stamp": stamp,
    }


def render_certificate_html(ctx: dict[str, Any]) -> str:
    return _env.get_template("certificate.html").render(**ctx)


def render_certificate_pdf(ctx: dict[str, Any]) -> RenderedDocument:
    return render_pdf(render_certificate_html(ctx))
