"""The shared PDF renderer (ADR 0016): one generator, no network, bundled fonts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import documents

APP = Path(__file__).parents[1] / "app"


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("data:image/png;base64,iVBORw0KGgo=", True),
        (f"file://{documents.FONT_DIR.as_posix()}/DejaVuSans.ttf", True),
        (f"file://{documents.ASSET_DIR.as_posix()}/logo.png", True),
        ("https://example.com/logo.png", False),
        ("http://169.254.169.254/latest/meta-data/", False),
        ("file:///etc/passwd", False),
        (f"file://{documents.FONT_DIR.as_posix()}/../../../../etc/passwd", False),
        ("ftp://example.com/x", False),
    ],
)
def test_documents_only_load_bundled_files(url: str, allowed: bool) -> None:
    assert documents.is_allowed_url(url) is allowed


def test_weasyprint_is_used_only_by_the_shared_renderer() -> None:
    pattern = re.compile(r"^\s*(from|import)\s+weasyprint", re.M)
    users = sorted(
        str(p.relative_to(APP)).replace("\\", "/")
        for p in APP.rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    )
    assert users == ["core/documents.py"]


def test_no_other_pdf_generator_is_imported() -> None:
    pattern = re.compile(r"^\s*(from|import)\s+(reportlab|fpdf|pdfkit|xhtml2pdf|pyppeteer)", re.M)
    assert [
        p.name for p in APP.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))
    ] == []


def test_templates_share_the_print_rules_and_escape_input() -> None:
    env = documents.template_env(APP / "modules" / "boq" / "html")
    assert env.autoescape is not False
    assert "@font-face" in documents.BASE_CSS and "page-break-inside: avoid" in documents.BASE_CSS
    assert "table-header-group" in documents.BASE_CSS
