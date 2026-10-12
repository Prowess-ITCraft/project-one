"""The IITPL stamp: loaded once through the certificate settings service (by the settings page or
`cli load-stamp`), embedded in the certificate, and required before a certificate is issued.
Certificates made outside production carry a "SAMPLE, NOT VALID" mark."""

from __future__ import annotations

import base64
import io
from datetime import date
from typing import Any

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import func, select

from app.cli import load_stamp
from app.core.db import get_sessionmaker
from app.core.documents import pdf_available, render_pdf
from app.core.errors import UnsupportedMedia
from app.modules.audit_log.models import AuditEntry
from app.modules.identity.permissions import Role
from app.modules.reporting import render
from app.modules.reporting import service as reporting
from app.sample_documents import certificate_context, report_content, stamp_data_url
from tests.helpers import idem, make_user, make_workspace

REP = "/api/v1/reporting"
MARK = "SAMPLE, NOT VALID"


def _stamp(colour: tuple[int, int, int, int] = (40, 40, 160, 255)) -> bytes:
    """A seal and signature on a transparent background, like the real one (647 x 386)."""
    img = Image.new("RGBA", (647, 386), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((150, 40, 450, 340), outline=colour, width=8)
    d.line((60, 230, 600, 120), fill=colour, width=6)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


async def _stamp_uploads() -> int:
    async with get_sessionmaker()() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(AuditEntry)
            .where(AuditEntry.action == "upload_certificate_stamp")
        )
    return int(n or 0)


async def test_load_stamp_loads_once_keeps_transparency_and_is_audited(client: Any) -> None:
    director = await make_user(client, Role.DIRECTOR)
    data = _stamp()
    assert await load_stamp(data, "stamp_sign.png", director.email) is True
    assert await load_stamp(data, "stamp_sign.png", director.email) is False
    assert await _stamp_uploads() == 1

    settings = (await client.get(f"{REP}/settings", headers=director.headers)).json()
    assert settings["stamp_uploaded"] is True
    url = (await client.get(f"{REP}/settings/stamp", headers=director.headers)).json()["data_url"]
    assert url.startswith("data:image/png;base64,")
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as stored:
        assert stored.size == (647, 386) and stored.mode == "RGBA"
        assert stored.getchannel("A").getextrema() == (0, 255)

    # a different file is a new stamp
    assert await load_stamp(_stamp((160, 40, 40, 255)), "new.png", director.email) is True
    assert await _stamp_uploads() == 2


async def test_load_stamp_only_for_people_who_set_up_certificates(client: Any) -> None:
    pm = await make_user(client, Role.PROJECT_MANAGER)
    with pytest.raises(SystemExit, match="may not change the certificate settings"):
        await load_stamp(_stamp(), "stamp.png", pm.email)
    with pytest.raises(SystemExit, match="No active account"):
        await load_stamp(_stamp(), "stamp.png", "nobody@example-itcraft.in")
    async with get_sessionmaker()() as s:
        assert (await reporting.cert_settings(s))["stamp_file_id"] is None
    assert await _stamp_uploads() == 0


async def test_load_stamp_goes_through_the_upload_checks(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    with pytest.raises(UnsupportedMedia, match="content is PNG"):
        await load_stamp(_stamp(), "stamp.jpg", admin.email)
    r = await client.post(
        f"{REP}/settings/stamp",
        files={"file": ("stamp.png", b"\x89PNG\r\n\x1a\n" + b"\0" * (21 * 1024 * 1024))},
        headers=admin.headers,
    )
    assert r.status_code == 413, r.text
    assert await _stamp_uploads() == 0


async def test_no_certificate_without_the_stamp(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = await make_workspace(client)
    director = await make_user(client, Role.DIRECTOR)
    real = reporting.conditions

    async def all_but_the_stamp(*args: Any) -> list[dict[str, Any]]:
        return [c if c["key"] == "stamp" else {**c, "met": True} for c in await real(*args)]

    monkeypatch.setattr(reporting, "conditions", all_but_the_stamp)
    r = await client.post(
        f"{REP}/projects/{ws.project_id}/certificates",
        headers={**director.headers, **idem()},
    )
    assert r.status_code == 409 and r.json()["code"] == "not_ready", r.text
    assert r.json()["missing"] == ["The IITPL stamp is uploaded"]


def _sample_ctx(stamp: bytes | None) -> dict[str, Any]:
    start = date(2026, 10, 10)
    return certificate_context(report_content(start, "ITCraft/NN/2627/030"), start, stamp)


def test_the_certificate_embeds_the_stamp_and_marks_samples() -> None:
    html = render.render_certificate_html(_sample_ctx(_stamp()))
    assert '<img class="stamp" src="data:image/png;base64,' in html
    assert MARK in html
    assert MARK not in render.render_certificate_html({**_sample_ctx(_stamp()), "sample": False})
    assert '<img class="stamp"' not in render.render_certificate_html(_sample_ctx(None))
    with pytest.raises(ValueError, match="PNG or JPEG"):
        stamp_data_url(b"GIF89a not a stamp")


async def test_only_production_certificates_go_without_the_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def company(_session: Any) -> dict[str, Any]:
        return {}

    class Prod:
        is_prod = True

    no_session: Any = None
    monkeypatch.setattr(render, "get_company_profile", company)
    args: tuple[Any, ...] = (
        no_session,
        {"scope": []},
        "0" * 64,
        "https://p1.example/verify/1",
        None,
    )
    assert (await render.certificate_context(*args))["sample"] is True  # tests are not prod
    monkeypatch.setattr(render, "get_settings", lambda: Prod())
    assert (await render.certificate_context(*args))["sample"] is False


@pytest.mark.skipif(not pdf_available(), reason="WeasyPrint renders in the API container")
def test_the_certificate_pdf_holds_the_stamp_on_one_page() -> None:
    import pypdfium2 as pdfium  # type: ignore[import-untyped]

    doc = render_pdf(render.render_certificate_html(_sample_ctx(_stamp())))
    assert doc.pages == 1
    assert b"/SMask" in doc.pdf  # the stamp keeps its transparency
    page = pdfium.PdfDocument(doc.pdf)[0]
    images = [o for o in page.get_objects() if o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE]
    assert len(images) == 2  # the IITPL logo and the stamp
