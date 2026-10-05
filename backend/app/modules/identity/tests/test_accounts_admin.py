"""What an admin or the Director does on the Accounts page, through the API: create with several
roles, edit details and roles, reset a password or an authenticator, sign someone out,
deactivate, erase. Also signing in with a recovery code when the phone is lost."""

from __future__ import annotations

from typing import Any

import pyotp

from app.core.redis import get_redis
from app.modules.identity.permissions import Role
from tests.helpers import PASSWORD, login, make_user

API = "/api/v1"
NEW_PASSWORD = "Lantern-Harbour-Quay-58"


async def _signin(client: Any, email: str, password: str) -> Any:
    await get_redis().flushall()  # the per-address limiter would trip in a tight loop
    return await client.post(f"{API}/auth/login", json={"email": email, "password": password})


async def test_create_with_two_roles_then_edit_details_and_roles(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    r = await client.post(
        f"{API}/users",
        headers=admin.headers,
        json={
            "email": "kavita.rao@itcraft-test.in",
            "full_name": "Kavita Rao",
            "initials": "KR",
            "designation": "Project manager",
            "password": NEW_PASSWORD,
            "roles": ["project_manager", "field_engineer"],
        },
    )
    assert r.status_code == 201, r.text
    u = (await client.get(f"{API}/users/{r.json()['id']}", headers=admin.headers)).json()
    assert sorted(u["roles"]) == ["field_engineer", "project_manager"]

    r = await client.patch(
        f"{API}/users/{u['id']}",
        headers=admin.headers,
        json={"version": u["version"], "phone": "+91 98200 41733", "designation": "Senior PM"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["designation"] == "Senior PM"
    # someone else saved first: the old version is refused, nothing is overwritten
    stale = await client.patch(
        f"{API}/users/{u['id']}",
        headers=admin.headers,
        json={"version": u["version"], "phone": None},
    )
    assert stale.status_code == 409

    v = r.json()["version"]
    r = await client.put(
        f"{API}/users/{u['id']}/roles",
        headers=admin.headers,
        json={"version": v, "roles": ["project_manager", "technical_lead"]},
    )
    assert r.status_code == 200, r.text
    assert sorted(r.json()["roles"]) == ["project_manager", "technical_lead"]
    listed = (await client.get(f"{API}/users?size=200", headers=admin.headers)).json()["items"]
    assert any(x["email"] == "kavita.rao@itcraft-test.in" for x in listed)


async def test_admin_cannot_remove_own_admin_role_or_deactivate_self(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    me = (await client.get(f"{API}/users/{admin.id}", headers=admin.headers)).json()
    r = await client.put(
        f"{API}/users/{admin.id}/roles",
        headers=admin.headers,
        json={"version": me["version"], "roles": ["sales_manager"]},
    )
    assert r.status_code == 422 and "own admin role" in r.json()["detail"]
    r = await client.patch(
        f"{API}/users/{admin.id}",
        headers=admin.headers,
        json={"version": me["version"], "is_active": False},
    )
    assert r.status_code == 422


async def test_director_manages_accounts_like_the_admin(client: Any) -> None:
    """ADR 0026: the Director creates accounts and assigns any role, Admin included."""
    director = await make_user(client, Role.DIRECTOR)
    r = await client.post(
        f"{API}/users",
        headers=director.headers,
        json={
            "email": "meera.joshi@itcraft-test.in",
            "full_name": "Meera Joshi",
            "initials": "MJ",
            "password": NEW_PASSWORD,
            "roles": ["sales_manager"],
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    r = await client.put(
        f"{API}/users/{created['id']}/roles",
        headers=director.headers,
        json={"version": created["version"], "roles": ["admin", "sales_head"]},
    )
    assert r.status_code == 200, r.text
    assert sorted(r.json()["roles"]) == ["admin", "sales_head"]
    # Nobody removes their own Director role, so the accounts never lose their last manager.
    me = (await client.get(f"{API}/users/{director.id}", headers=director.headers)).json()
    r = await client.put(
        f"{API}/users/{director.id}/roles",
        headers=director.headers,
        json={"version": me["version"], "roles": ["sales_head"]},
    )
    assert r.status_code == 422 and "own director role" in r.json()["detail"]


async def test_only_admin_and_director_create_accounts(client: Any) -> None:
    for role in (Role.SALES_HEAD, Role.PROJECT_MANAGER, Role.TECHNICAL_LEAD):
        someone = await make_user(client, role)
        r = await client.post(
            f"{API}/users",
            headers=someone.headers,
            json={
                "email": f"nobody.{role.value}@itcraft-test.in",
                "full_name": "Not Allowed",
                "initials": "NA",
                "password": NEW_PASSWORD,
                "roles": ["admin"],
            },
        )
        assert r.status_code == 403, (role, r.text)


async def test_reset_password_ends_sessions_and_the_old_password(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    u = await make_user(client, Role.SALES_MANAGER)
    r = await client.post(
        f"{API}/users/{u.id}/reset-password",
        headers=admin.headers,
        json={"new_password": NEW_PASSWORD},
    )
    assert r.status_code == 204, r.text
    assert (await client.get(f"{API}/auth/me", headers=u.headers)).status_code == 401
    assert (await _signin(client, u.email, PASSWORD)).status_code == 401
    assert (await _signin(client, u.email, NEW_PASSWORD)).status_code == 200


async def test_reset_authenticator_means_setting_it_up_again(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    director = await make_user(client, Role.DIRECTOR)
    r = await client.post(f"{API}/users/{director.id}/reset-mfa", headers=admin.headers)
    assert r.status_code == 200 and r.json()["mfa_enabled"] is False
    body = (await _signin(client, director.email, PASSWORD)).json()
    assert body["status"] == "mfa_enrolment_required"
    # nobody resets their own: another admin must
    own = await client.post(f"{API}/users/{admin.id}/reset-mfa", headers=admin.headers)
    assert own.status_code == 403


async def test_sign_out_everywhere_and_session_list(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    u = await make_user(client, Role.FIELD_ENGINEER)
    sessions = await client.get(f"{API}/users/{u.id}/sessions", headers=admin.headers)
    assert sessions.status_code == 200 and len(sessions.json()) >= 1
    r = await client.post(f"{API}/users/{u.id}/sessions/revoke-all", headers=admin.headers)
    assert r.status_code == 204
    assert (await client.get(f"{API}/auth/me", headers=u.headers)).status_code == 401


async def test_recovery_code_signs_in_once(client: Any) -> None:
    """The lost-phone path: a saved recovery code works once, then never again."""
    admin = await make_user(client, Role.ADMIN)
    director = await make_user(client, Role.DIRECTOR)
    await client.post(f"{API}/users/{director.id}/reset-mfa", headers=admin.headers)
    body = (await _signin(client, director.email, PASSWORD)).json()
    start = await client.post(
        f"{API}/auth/mfa/enrol/start", json={"enrol_token": body["challenge_token"]}
    )
    secret = start.json()["secret"]
    confirm = await client.post(
        f"{API}/auth/mfa/enrol/confirm",
        json={"enrol_token": body["challenge_token"], "code": pyotp.TOTP(secret).now()},
    )
    assert confirm.status_code == 200, confirm.text
    code = confirm.json()["recovery_codes"][0]

    for expected in (200, 401):
        challenge = (await _signin(client, director.email, PASSWORD)).json()["challenge_token"]
        r = await client.post(
            f"{API}/auth/mfa/verify",
            json={"challenge_token": challenge, "recovery_code": code.lower()},
        )
        assert r.status_code == expected, r.text
    # sending both a code and a recovery code is refused
    challenge = (await _signin(client, director.email, PASSWORD)).json()["challenge_token"]
    both = await client.post(
        f"{API}/auth/mfa/verify",
        json={"challenge_token": challenge, "code": "123456", "recovery_code": code},
    )
    assert both.status_code == 422


async def test_erase_personal_data(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    u = await make_user(client, Role.SALES_MANAGER, name="Rohan Mehta")
    r = await client.post(f"{API}/users/{u.id}/erase", headers=admin.headers)
    assert r.status_code == 204, r.text
    after = await client.get(f"{API}/users/{u.id}", headers=admin.headers)
    assert after.status_code in (200, 404)
    if after.status_code == 200:
        assert after.json()["full_name"] == "Erased user" and after.json()["is_active"] is False
    assert (await _signin(client, u.email, PASSWORD)).status_code == 401
    assert (
        await client.post(f"{API}/users/{admin.id}/erase", headers=admin.headers)
    ).status_code == 422


async def test_changing_own_password_needs_the_current_one(client: Any) -> None:
    u = await make_user(client, Role.AUDIT_ENGINEER)
    wrong = await client.post(
        f"{API}/auth/password",
        headers=u.headers,
        json={"current_password": "not-my-password-1", "new_password": NEW_PASSWORD},
    )
    assert wrong.status_code in (400, 401, 422)
    ok = await client.post(
        f"{API}/auth/password",
        headers=u.headers,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert ok.status_code in (200, 204), ok.text
    await get_redis().flushall()
    assert await login(client, u.email, password=NEW_PASSWORD)
