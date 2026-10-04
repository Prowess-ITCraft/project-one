"""Which routes are open without signing in, and whether docs/API_ROUTES.md is current."""

from pathlib import Path

from app.cli import api_routes_markdown
from app.main import app

# The only calls a person can make before signing in: signing in itself, and the links in
# emails and on certificates that customers open without an account.
OPEN = {
    "POST /api/v1/auth/login",
    "POST /api/v1/auth/token",
    "POST /api/v1/auth/mfa/verify",
    "POST /api/v1/auth/refresh",
    "GET /api/v1/public/acks/{token}",
    "POST /api/v1/public/acks/{token}",
    "GET /api/v1/public/certificates/{number}",
    "GET /api/v1/public/files/{file_id}",
    "GET /api/v1/public/waivers/{token}",
    "POST /api/v1/public/waivers/{token}",
}


def test_only_sign_in_and_public_links_are_open() -> None:
    schema = app.openapi()
    open_ops = {
        f"{method.upper()} {path}"
        for path, ops in schema["paths"].items()
        for method, op in ops.items()
        if method in ("get", "post", "put", "patch", "delete") and not op.get("security")
    }
    assert open_ops == OPEN


def test_route_list_is_current() -> None:
    doc = Path(__file__).resolve().parents[2] / "docs" / "API_ROUTES.md"
    assert doc.read_text(encoding="utf-8") == api_routes_markdown(app.openapi()), (
        "Routes changed: run `python -m app.cli api-routes` from backend/"
    )
