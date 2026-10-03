"""Every protected route against every role. Deny by default.

The matrix is built from the routers themselves, so a new endpoint is covered the moment it is
added: it must either declare `require(...)` permissions (and is then checked for every role)
or be listed in PUBLIC below on purpose.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from fastapi.routing import APIRoute

from app.core.config import get_settings
from app.core.redis import get_redis
from app.modules import registry
from app.modules.identity.permissions import ROLE_PERMISSIONS, P, Role
from tests.helpers import TestUser, make_customer, make_user

# (method, path) pairs that are intentionally reachable without the matrix: sign-in flow,
# token-holder endpoints and the public acknowledgement links (protected by signed tokens).
PUBLIC_PREFIXES = ("/auth/", "/public/")
# Reachable by any signed-in user, nothing more.
SELF_SERVICE_PREFIXES = ("/account/", "/auth/me", "/auth/logout", "/auth/sessions")


def _collect(dep: Any, acc: set[P]) -> None:
    for d in dep.dependencies:
        perms = getattr(d.call, "__required_permissions__", None)
        if perms:
            acc |= set(perms)
        _collect(d, acc)


def _uses_principal(dep: Any) -> bool:
    from app.modules.identity.deps import get_principal

    return any(d.call is get_principal or _uses_principal(d) for d in dep.dependencies)


def all_routes() -> list[tuple[str, str, frozenset[P], bool]]:
    """(method, full path, required permissions, needs a signed-in user)"""
    prefix = get_settings().api_prefix
    out: list[tuple[str, str, frozenset[P], bool]] = []
    for router in registry.routers():
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            perms: set[P] = set()
            _collect(route.dependant, perms)
            for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
                out.append(
                    (
                        method,
                        prefix + route.path,
                        frozenset(perms),
                        _uses_principal(route.dependant),
                    )
                )
    return out


ROUTES = all_routes()


def _fill(path: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        return str(uuid.uuid4()) if name.endswith("id") else "x"

    return re.sub(r"\{([^}:]+)(?::[^}]*)?\}", repl, path)


def test_every_route_is_classified() -> None:
    """No route may be both unprotected and outside the public allow-list."""
    prefix = get_settings().api_prefix
    unknown = [
        f"{m} {p}"
        for m, p, perms, needs_user in ROUTES
        if not perms
        and not needs_user
        and not any(p.startswith(prefix + pre) for pre in PUBLIC_PREFIXES)
    ]
    assert unknown == [], f"routes with no authentication and not on the public list: {unknown}"


def test_routes_were_found() -> None:
    assert len(ROUTES) > 60
    assert sum(1 for *_, perms, _u in ROUTES if perms) > 40


async def test_unauthenticated_requests_are_refused(client: Any) -> None:
    prefix = get_settings().api_prefix
    bad: list[str] = []
    for method, path, perms, needs_user in ROUTES:
        if not (perms or needs_user):
            continue
        r = await client.request(method, _fill(path), json={} if method != "GET" else None)
        if r.status_code != 401:
            bad.append(f"{method} {path} -> {r.status_code}")
    assert bad == [], bad
    assert prefix


async def _users(client: Any) -> dict[Role, TestUser]:
    """One user per role. The IP rate limiter is reset between sign-ins (same test client IP)."""
    users: dict[Role, TestUser] = {}
    admin_headers: dict[str, str] | None = None
    customer_id: uuid.UUID | None = None
    for role in Role:
        await get_redis().flushall()
        if role is Role.CUSTOMER_REP:
            sm = await make_user(client, Role.SALES_MANAGER)
            await get_redis().flushall()
            admin_headers = sm.headers
            customer_id = uuid.UUID((await make_customer(client, admin_headers))["id"])
            users[role] = await make_user(client, role, customer_id=customer_id)
        else:
            users[role] = await make_user(client, role)
    await get_redis().flushall()
    return users


@pytest.mark.parametrize("seed", [0])
async def test_role_by_route_matrix(client: Any, seed: int) -> None:
    users = await _users(client)
    prefix = get_settings().api_prefix
    failures: list[str] = []
    checked = 0
    for method, path, perms, needs_user in ROUTES:
        if not perms:
            continue
        if path.startswith(prefix + "/public/"):
            continue
        url = _fill(path)
        for role, user in users.items():
            await get_redis().flushall()
            allowed = perms <= ROLE_PERMISSIONS[role]
            headers = {**user.headers, "Idempotency-Key": uuid.uuid4().hex}
            r = await client.request(
                method, url, headers=headers, json={} if method != "GET" else None
            )
            checked += 1
            forbidden = r.status_code == 403
            if allowed and forbidden:
                failures.append(f"{role.value} should reach {method} {path}, got 403 {r.text[:80]}")
            if not allowed and not forbidden:
                failures.append(
                    f"{role.value} must be refused {method} {path} (needs "
                    f"{sorted(p.value for p in perms)}), got {r.status_code}"
                )
    assert failures == [], "\n".join(failures)
    assert checked > 400


async def test_customer_rep_reaches_only_their_own_customer(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    mine = await make_customer(client, sm.headers)
    other = await make_customer(client, sm.headers, legal_name="Other Industries Pvt Ltd")
    await get_redis().flushall()
    rep = await make_user(client, Role.CUSTOMER_REP, customer_id=uuid.UUID(mine["id"]))
    base = f"{get_settings().api_prefix}/customers"
    assert (await client.get(f"{base}/{mine['id']}", headers=rep.headers)).status_code == 200
    assert (await client.get(f"{base}/{other['id']}", headers=rep.headers)).status_code == 404
    listed = (await client.get(base, headers=rep.headers)).json()
    assert [c["id"] for c in listed["items"]] == [mine["id"]]
