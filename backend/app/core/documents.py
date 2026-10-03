"""The one PDF renderer (ADR 0016). Every PDF the system makes goes through `render_pdf`.

Pipeline: a module renders its Jinja2 template (made with `template_env`) to HTML, then
`render_pdf` lays it out with WeasyPrint and returns the bytes with a checksum and a page count.

Safety:
- templates autoescape everything, so no user text becomes markup;
- the URL fetcher refuses the network: only `data:` URLs and files inside the bundled font and
  asset folders can be read;
- fonts come from the image (DejaVu, which has the rupee sign), loaded with `@font-face`, so the
  output never depends on what the host happens to have installed.

WeasyPrint needs Pango and HarfBuzz from the image. Where they are missing (a Windows laptop),
`render_pdf` answers 503 `pdf_unavailable` and HTML and Excel exports keep working.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape

from app.core.errors import ServiceUnavailable

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
ASSET_DIR = Path(__file__).parent / "document_assets"
SHARED_TEMPLATES = Path(__file__).parent / "document_templates"
ALLOWED_ROOTS = (FONT_DIR, ASSET_DIR)

# Shared print rules for every document: A4, margins, page numbers, rows never split, the table
# header repeated on each page, and the bundled fonts. Templates include it with
# `{{ base_css | safe }}` inside their <style>.
BASE_CSS = f"""
@font-face {{ font-family: "P1 Sans"; src: url("file://{FONT_DIR.as_posix()}/DejaVuSans.ttf"); }}
@font-face {{ font-family: "P1 Sans"; font-weight: 700;
  src: url("file://{FONT_DIR.as_posix()}/DejaVuSans-Bold.ttf"); }}
@page {{ size: A4; margin: 16mm 14mm 18mm 14mm;
  @bottom-center {{ content: "Page " counter(page) " of " counter(pages);
    font-family: "P1 Sans", "DejaVu Sans", sans-serif; font-size: 8pt; color: #666; }} }}
* {{ box-sizing: border-box; }}
body {{ font-family: "P1 Sans", "DejaVu Sans", sans-serif; font-size: 9pt; color: #111;
  line-height: 1.35; }}
table {{ width: 100%; border-collapse: collapse; }}
thead {{ display: table-header-group; }}
tr {{ page-break-inside: avoid; }}
.wordmark {{ font-weight: 700; letter-spacing: 0.6pt; line-height: 1; }}
.letterhead {{ display: flex; justify-content: space-between; align-items: flex-start;
  border-bottom: 1.5pt solid #2C629F; padding-bottom: 8pt; }}
.letterhead .mark, .mini-head .mark {{ display: flex; align-items: center; gap: 10pt; }}
.letterhead .logo {{ height: 54pt; width: auto; }}
.letterhead .tag {{ font-size: 8pt; color: #444; margin-top: 4pt; }}
.letterhead .co {{ text-align: right; font-size: 8pt; color: #333; }}
.mini-head {{ display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1pt solid #2C629F; padding-bottom: 6pt; margin-bottom: 12pt; }}
.mini-head .logo {{ height: 30pt; width: auto; }}
.mini-head .right {{ font-size: 8pt; color: #555; text-align: right; }}
""".strip()


@dataclass(frozen=True)
class RenderedDocument:
    pdf: bytes
    sha256: str
    pages: int


def template_env(folder: Path) -> Environment:
    """A Jinja2 environment for one module's document templates, with autoescape on."""
    env = Environment(
        loader=ChoiceLoader(
            [FileSystemLoader(str(folder)), FileSystemLoader(str(SHARED_TEMPLATES))]
        ),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["base_css"] = BASE_CSS
    env.globals["asset"] = asset_url
    return env


def asset_url(name: str) -> str:
    """A `file:` URL for a bundled document asset (logo, stamp). Only names inside the assets
    folder resolve; anything else gives an empty string and the image is simply left out."""
    path = (ASSET_DIR / name).resolve()
    if not path.is_relative_to(ASSET_DIR.resolve()) or not path.is_file():
        return ""
    return path.as_uri()


def qr_data_url(text: str) -> str:
    """A QR code as an SVG data URL, drawn here so no document or page fetches anything."""
    import base64

    import qrcode
    import qrcode.image.svg

    svg = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2).to_string()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


def is_allowed_url(url: str) -> bool:
    """`data:` URLs, and `file:` URLs inside the bundled font and asset folders. Nothing else."""
    parsed = urlparse(url)
    if parsed.scheme == "data":
        return True
    if parsed.scheme != "file":
        return False
    path = Path(unquote(parsed.path)).resolve()
    return any(path.is_relative_to(root.resolve()) for root in ALLOWED_ROOTS)


def pdf_available() -> bool:
    """True where WeasyPrint and its system libraries load (the API container)."""
    try:
        _weasy()
    except ServiceUnavailable:
        return False
    return True


def _weasy() -> tuple[Any, Any]:
    try:
        from weasyprint import HTML
        from weasyprint.urls import URLFetcher
    except (ImportError, OSError) as exc:
        raise ServiceUnavailable(
            "PDF rendering is not available on this server. Use the Excel export, or run the API "
            "in its container.",
            code="pdf_unavailable",
        ) from exc
    return HTML, URLFetcher


def render_pdf(html: str) -> RenderedDocument:
    html_cls, fetcher_cls = _weasy()

    class LocalOnlyFetcher(fetcher_cls):  # type: ignore[misc, valid-type]
        def fetch(self, url: str, headers: Any = None) -> Any:
            if not is_allowed_url(url):
                raise ValueError(f"Documents may not load {url[:80]}")
            return super().fetch(url, headers)

    fetcher = LocalOnlyFetcher(allowed_protocols=("data", "file"), allow_redirects=False)
    doc = html_cls(string=html, url_fetcher=fetcher).render()
    pdf = bytes(doc.write_pdf())
    return RenderedDocument(pdf, hashlib.sha256(pdf).hexdigest(), len(doc.pages))
