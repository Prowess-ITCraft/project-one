# ADR 0016: One shared WeasyPrint renderer

Status: accepted
Date: 2026-10-03

## Context

We want WeasyPrint as the only PDF generator, behind one shared rendering service. A check of
the code on 3 October found WeasyPrint was the only generator in use (no ReportLab, wkhtmltopdf or
headless Chrome), but it was called directly from `boq/render.py`, with the default URL fetcher
(which can reach the network), system fonts by name and no checksum.

## Decision

- `core/documents.py` owns PDF rendering: a Jinja2 environment with autoescape per template
  folder, `render_pdf(html)` with a restricted URL fetcher that allows only `data:` URLs and
  files under the bundled assets folder, a shared print stylesheet with `@font-face` pointing at
  the DejaVu fonts installed in the image, and a `RenderedDocument` result carrying bytes,
  sha256 and page count.
- Modules keep their own templates (`boq/html`, `planning/html`, `fieldops/html`) and call the
  shared renderer. They never import WeasyPrint.
- Large documents render in the Celery worker; quotations, plans and checklists render inline
  within the request timeout.

## Consequences

- No document can fetch a remote URL or a file outside the assets folder.
- A grep for `weasyprint` outside `core/documents.py` is a CI failure (added to the import rules).
