from __future__ import annotations

from typing import Any

from app.modules.identity.permissions import Role
from tests.helpers import make_user


async def test_health_and_ready(client: Any) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "x-request-id" in r.headers
    r = await client.get("/readyz")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"


async def test_login_and_me(client: Any) -> None:
    u = await make_user(client, Role.SALES_MANAGER)
    r = await client.get("/api/v1/auth/me", headers=u.headers)
    assert r.status_code == 200, r.text
    assert "price:read" in r.json()["permissions"]


async def test_director_login_needs_mfa(client: Any) -> None:
    u = await make_user(client, Role.DIRECTOR)
    r = await client.get("/api/v1/auth/me", headers=u.headers)
    assert r.status_code == 200, r.text
