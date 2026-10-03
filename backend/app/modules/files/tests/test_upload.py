"""Upload pipeline: type sniffing, virus scan, EXIF policy, object-level access, downloads."""

from __future__ import annotations

import io
from typing import Any

import httpx
from PIL import Image

from app.modules.identity.permissions import Role
from tests.harness import EicarScanner
from tests.helpers import make_user, make_workspace, sample_report_path

API = "/api/v1/files"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (40, 30), "red")
    exif = Image.Exif()
    exif[0x0132] = "2026:09:30 10:00:00"
    exif[0x8825] = {1: "N", 2: (19.0, 7.0, 0.0), 3: "E", 4: (72.0, 52.0, 0.0)}
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


async def _post(client: Any, user: Any, name: str, data: bytes, mime: str, **form: str) -> Any:
    return await client.post(
        API, files={"file": (name, data, mime)}, data=form, headers=user.headers
    )


async def test_docx_upload_is_stored_and_downloadable(client: Any) -> None:
    ws = await make_workspace(client)
    r = await _post(
        client,
        ws.auditor,
        "audit.docx",
        sample_report_path().read_bytes(),
        DOCX_MIME,
        purpose="audit_report",
        project_id=ws.project_id,
    )
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["kind"] == "docx" and len(f["sha256"]) == 64
    d = await client.get(f"{API}/{f['id']}/download", headers=ws.auditor.headers)
    assert d.status_code == 200
    async with httpx.AsyncClient() as plain:  # the presigned URL needs no credentials
        got = await plain.get(d.json()["url"])
    assert got.status_code == 200 and got.content == sample_report_path().read_bytes()


async def test_extension_must_match_content(client: Any) -> None:
    ws = await make_workspace(client)
    fake = b"MZ\x90\x00" + b"\x00" * 200  # a Windows executable
    r = await _post(
        client,
        ws.auditor,
        "report.docx",
        fake,
        DOCX_MIME,
        purpose="audit_report",
        project_id=ws.project_id,
    )
    assert r.status_code == 415
    r = await _post(
        client,
        ws.auditor,
        "report.exe",
        sample_report_path().read_bytes(),
        DOCX_MIME,
        purpose="audit_report",
        project_id=ws.project_id,
    )
    assert r.status_code == 415


async def test_virus_is_rejected_and_not_stored(client: Any) -> None:
    ws = await make_workspace(client)
    r = await _post(
        client,
        ws.auditor,
        "notes.txt",
        EicarScanner.EICAR,
        "text/plain",
        purpose="config_export",
        project_id=ws.project_id,
    )
    assert r.status_code == 422 and r.json()["code"] == "file_infected"
    from sqlalchemy import func, select, text

    from app.core.db import get_sessionmaker
    from app.modules.files.models import RejectedUpload, StoredFile

    async with get_sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(StoredFile)) == 0
        assert await s.scalar(select(func.count()).select_from(RejectedUpload)) == 1
        audit = await s.scalar(
            text("SELECT count(*) FROM audit_log WHERE action = 'upload_rejected_malware'")
        )
        assert audit == 1


async def test_scanner_failure_means_no_upload(client: Any) -> None:
    from app.modules.files.scanner import set_scanner

    class Down:
        async def scan(self, data: bytes) -> Any:
            raise OSError("clamd unreachable")

    set_scanner(Down())
    ws = await make_workspace(client)
    r = await _post(
        client,
        ws.auditor,
        "audit.docx",
        sample_report_path().read_bytes(),
        DOCX_MIME,
        purpose="audit_report",
        project_id=ws.project_id,
    )
    assert r.status_code == 503  # fail closed
    set_scanner(None)


async def test_purpose_rules(client: Any) -> None:
    ws = await make_workspace(client)
    docx = sample_report_path().read_bytes()
    assert (
        await _post(client, ws.auditor, "a.docx", docx, DOCX_MIME, purpose="nonsense")
    ).status_code == 422
    # audit_report must belong to a project
    assert (
        await _post(client, ws.auditor, "a.docx", docx, DOCX_MIME, purpose="audit_report")
    ).json()["code"] == "project_required"
    # docx is not allowed for evidence photos
    r = await _post(
        client,
        ws.auditor,
        "a.docx",
        docx,
        DOCX_MIME,
        purpose="evidence_photo",
        project_id=ws.project_id,
    )
    assert r.status_code == 415


async def test_exif_is_stripped_except_for_evidence_photos(client: Any) -> None:
    ws = await make_workspace(client)
    photo = _jpeg_with_gps()
    r = await _post(client, ws.auditor, "p.jpg", photo, "image/jpeg", purpose="document")
    assert r.status_code == 201, r.text
    assert r.json()["exif_stripped"] is True and r.json()["meta"] == {}
    r = await _post(
        client,
        ws.auditor,
        "p.jpg",
        photo,
        "image/jpeg",
        purpose="evidence_photo",
        project_id=ws.project_id,
    )
    assert r.status_code == 201, r.text
    assert "gps" in r.json()["meta"] and r.json()["meta"]["taken_at"].startswith("2026:09:30")


async def test_size_limit(client: Any) -> None:
    ws = await make_workspace(client)
    big = b"PK\x03\x04" + b"0" * (26 * 1024 * 1024)
    r = await _post(
        client,
        ws.auditor,
        "big.docx",
        big,
        DOCX_MIME,
        purpose="audit_report",
        project_id=ws.project_id,
    )
    assert r.status_code == 413


async def test_object_level_access(client: Any) -> None:
    ws = await make_workspace(client)
    r = await _post(
        client,
        ws.auditor,
        "audit.docx",
        sample_report_path().read_bytes(),
        DOCX_MIME,
        purpose="audit_report",
        project_id=ws.project_id,
    )
    fid = r.json()["id"]
    outsider = await make_user(client, Role.AUDIT_ENGINEER)
    assert (await client.get(f"{API}/{fid}", headers=outsider.headers)).status_code in (403, 404)
    assert (await client.get(f"{API}/{fid}/download", headers=outsider.headers)).status_code in (
        403,
        404,
    )
    # A project member can read a colleague's file.
    assert (await client.get(f"{API}/{fid}", headers=ws.architect.headers)).status_code == 200
    # Uploading into a project you are not on is refused.
    r = await _post(
        client,
        outsider,
        "a.docx",
        sample_report_path().read_bytes(),
        DOCX_MIME,
        purpose="audit_report",
        project_id=ws.project_id,
    )
    assert r.status_code in (403, 404)
