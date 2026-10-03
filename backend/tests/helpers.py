"""Test helpers: create users with roles and sign them in (including TOTP for MFA roles)."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from typing import Any

import pyotp

from app.modules.identity.permissions import Role

PASSWORD = "Correct-Horse-Battery-9"
_counter = itertools.count(1)


@dataclass
class TestUser:
    __test__ = False
    id: uuid.UUID
    email: str
    roles: list[Role]
    headers: dict[str, str]
    totp_secret: str | None = None


async def make_user(
    client: Any,
    *roles: Role,
    customer_id: uuid.UUID | None = None,
    name: str | None = None,
) -> TestUser:
    """Create a user straight through the service layer and sign in over HTTP."""
    from app.core import crypto
    from app.core.db import get_sessionmaker
    from app.modules.identity import service
    from app.modules.identity.permissions import MFA_REQUIRED_ROLES
    from app.modules.identity.schemas import UserCreateIn

    if Role.CUSTOMER_REP in roles:
        await _enable_customer_login()
    n = next(_counter)
    email = f"user{n}-{uuid.uuid4().hex[:6]}@example-itcraft.in"
    full_name = name or f"Test User{n}"
    secret: str | None = None
    async with get_sessionmaker()() as s:
        user = await service.create_user(
            s,
            None,
            UserCreateIn(
                email=email,
                full_name=full_name,
                initials="TU",
                password=PASSWORD,
                roles=list(roles),
                customer_id=customer_id,
            ),
        )
        if set(roles) & MFA_REQUIRED_ROLES:
            secret = pyotp.random_base32()
            user.mfa_secret_enc = crypto.encrypt_str(secret)
            user.mfa_enabled = True
            await s.commit()
        user_id = user.id
    headers = await login(client, email, secret)
    return TestUser(id=user_id, email=email, roles=list(roles), headers=headers, totp_secret=secret)


async def _enable_customer_login() -> None:
    from sqlalchemy.dialects.postgresql import insert

    from app.core import flags
    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            insert(flags.FeatureFlag)
            .values(key="customer_portal_login", enabled=True)
            .on_conflict_do_update(index_elements=["key"], set_={"enabled": True})
        )
        await s.commit()
    flags.clear_cache()


async def login(
    client: Any, email: str, totp_secret: str | None = None, password: str = PASSWORD
) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    if body["status"] == "mfa_required":
        assert totp_secret, "user needs MFA but no secret was given"
        r = await client.post(
            "/api/v1/auth/mfa/verify",
            json={
                "challenge_token": body["challenge_token"],
                "code": pyotp.TOTP(totp_secret).now(),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def make_customer(client: Any, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    body = {
        "legal_name": "Shakti Equipments Pvt Ltd",
        "address_line1": "Plot 12, Wagle Estate",
        "city": "Thane",
        "state": "Maharashtra",
        "pincode": "400605",
        **overrides,
    }
    r = await client.post("/api/v1/customers", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return dict(r.json())


async def make_project(client: Any, headers: dict[str, str], customer_id: str) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/projects",
        json={"customer_id": customer_id, "name": "IT infra hardening"},
        headers={**headers, **idem()},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


@dataclass
class Workspace:
    """A customer and project with a sales manager, sales head and the people who work on it."""

    customer: dict[str, Any]
    project: dict[str, Any]
    sales: TestUser
    head: TestUser
    auditor: TestUser
    architect: TestUser

    @property
    def project_id(self) -> str:
        return str(self.project["id"])


async def make_workspace(client: Any) -> Workspace:
    from app.modules.identity.permissions import Role

    sales = await make_user(client, Role.SALES_MANAGER)
    head = await make_user(client, Role.SALES_HEAD)
    auditor = await make_user(client, Role.AUDIT_ENGINEER)
    architect = await make_user(client, Role.SOLUTION_ARCHITECT)
    customer = await make_customer(client, sales.headers)
    project = await make_project(client, sales.headers, customer["id"])
    for user, role in ((auditor, Role.AUDIT_ENGINEER), (architect, Role.SOLUTION_ARCHITECT)):
        r = await client.put(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(user.id), "project_role": role.value},
            headers=head.headers,
        )
        assert r.status_code == 200, r.text
    return Workspace(customer, project, sales, head, auditor, architect)


def sample_report_path() -> Any:
    from pathlib import Path

    return next((Path(__file__).parents[2] / "samples").glob("*PrismSuite Audit Report.docx"))


async def upload_sample_report(client: Any, user: TestUser, project_id: str) -> dict[str, Any]:
    data = sample_report_path().read_bytes()
    r = await client.post(
        "/api/v1/files",
        files={
            "file": (
                "audit.docx",
                data,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"purpose": "audit_report", "project_id": project_id},
        headers=user.headers,
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def approve_baseline(client: Any, ws: Workspace) -> dict[str, Any]:
    """Upload, import, resolve the firewall conflict and approve the sample audit."""
    f = await upload_sample_report(client, ws.auditor, ws.project_id)
    base = "/api/v1/prismsuite/imports"
    imp = (
        await client.post(
            base,
            json={"project_id": ws.project_id, "file_id": f["id"]},
            headers={**ws.auditor.headers, **idem()},
        )
    ).json()
    r = await client.post(
        f"{base}/{imp['id']}/resolutions",
        json={
            "path": "/devices[firewall]/high_availability",
            "reason": "Confirmed on site.",
            "version": imp["version"],
        },
        headers=ws.auditor.headers,
    )
    r = await client.post(
        f"{base}/{imp['id']}/approve",
        json={"version": r.json()["version"]},
        headers={**ws.architect.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


async def seed_reference_data() -> None:
    """Catalogue items, prices and the ideal-infra rule library."""
    from app.core.db import get_sessionmaker
    from app.modules.catalogue.seed import seed_catalogue
    from app.modules.infra.seed import seed_rules

    async with get_sessionmaker()() as s:
        await seed_catalogue(s)
    async with get_sessionmaker()() as s:
        await seed_rules(s)


BRIEF = {
    "company_size": "small",
    "budget_tier": "standard",
    "users_now": 27,
    "users_12m": 35,
    "sites": 1,
    "preferred_brands": ["Sophos"],
    "excluded_brands": [],
    "budget_ceiling": "600000.00",
    "keep_assets": ["Cisco Business 350 switch"],
    "compliance": [],
}
