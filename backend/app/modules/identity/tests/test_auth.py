"""Sign-in, lockout, token rotation, MFA, sessions and password rules."""

from __future__ import annotations

import time
from typing import Any

import pyotp

from app.core.redis import get_redis
from app.modules.identity.permissions import Role
from tests.helpers import PASSWORD, login, make_user

API = "/api/v1"


async def _login_raw(client: Any, email: str, password: str) -> Any:
    await get_redis().flushall()  # the per-IP limiter would otherwise trip in a tight test loop
    return await client.post(f"{API}/auth/login", json={"email": email, "password": password})


async def test_wrong_password_and_unknown_user_look_the_same(client: Any) -> None:
    u = await make_user(client, Role.SALES_MANAGER)
    a = await _login_raw(client, u.email, "wrong-password-1")
    b = await _login_raw(client, "nobody@example-itcraft.in", "wrong-password-1")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


async def test_lockout_after_repeated_failures_and_admin_unlock(client: Any) -> None:
    u = await make_user(client, Role.SALES_MANAGER)
    admin = await make_user(client, Role.ADMIN)
    for _ in range(5):
        assert (await _login_raw(client, u.email, "wrong-password-1")).status_code == 401
    # Even the right password is refused while locked.
    r = await _login_raw(client, u.email, PASSWORD)
    assert r.status_code == 423
    assert "Retry-After" in r.headers or r.json().get("code") == "locked"
    await get_redis().flushall()
    r = await client.post(f"{API}/users/{u.id}/unlock", headers=admin.headers)
    assert r.status_code == 200, r.text
    assert (await _login_raw(client, u.email, PASSWORD)).status_code == 200


async def test_refresh_token_rotates_and_reuse_kills_the_session(client: Any) -> None:
    u = await make_user(client, Role.SALES_MANAGER)
    await get_redis().flushall()
    tokens = (
        await client.post(f"{API}/auth/login", json={"email": u.email, "password": PASSWORD})
    ).json()
    first = tokens["refresh_token"]
    assert first
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["refresh_token"] != first
    # Two tabs refreshing at the same moment: the loser is told to retry, nothing is revoked.
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 401 and r.json()["code"] == "refresh_race"
    # Later, presenting the old token again is treated as theft: the whole session is revoked.
    from sqlalchemy import text

    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text("UPDATE refresh_tokens SET used_at = used_at - interval '5 minutes'"))
        await s.commit()
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 401 and r.json()["code"] == "refresh_invalid"
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401
    me = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {second['access_token']}"}
    )
    assert me.status_code == 401


async def test_director_must_enrol_mfa_before_getting_tokens(client: Any) -> None:
    from app.core.db import get_sessionmaker
    from app.modules.identity import service
    from app.modules.identity.schemas import UserCreateIn

    async with get_sessionmaker()() as s:
        await service.create_user(
            s,
            None,
            UserCreateIn(
                email="director@example-itcraft.in",
                full_name="Dee Rector",
                initials="DR",
                password=PASSWORD,
                roles=[Role.DIRECTOR],
            ),
        )
    r = await _login_raw(client, "director@example-itcraft.in", PASSWORD)
    body = r.json()
    assert body["status"] == "mfa_enrolment_required"
    assert "access_token" not in body
    token = body["challenge_token"]
    start = (await client.post(f"{API}/auth/mfa/enrol/start", json={"enrol_token": token})).json()
    code = pyotp.TOTP(start["secret"]).now()
    done = await client.post(
        f"{API}/auth/mfa/enrol/confirm", json={"enrol_token": token, "code": code}
    )
    assert done.status_code == 200, done.text
    assert len(done.json()["recovery_codes"]) >= 8
    assert done.json()["tokens"]["access_token"]


async def test_mfa_code_is_required_and_wrong_code_fails(client: Any) -> None:
    u = await make_user(client, Role.DIRECTOR)
    r = await _login_raw(client, u.email, PASSWORD)
    body = r.json()
    assert body["status"] == "mfa_required"
    bad = await client.post(
        f"{API}/auth/mfa/verify",
        json={"challenge_token": body["challenge_token"], "code": "000000"},
    )
    assert bad.status_code == 401
    # The code used at sign-in cannot be replayed; use the next time step.
    totp = pyotp.TOTP(u.totp_secret or "")
    replay = await client.post(
        f"{API}/auth/mfa/verify",
        json={"challenge_token": body["challenge_token"], "code": totp.now()},
    )
    assert replay.status_code == 401
    good = await client.post(
        f"{API}/auth/mfa/verify",
        json={"challenge_token": body["challenge_token"], "code": totp.at(int(time.time()) + 30)},
    )
    assert good.status_code == 200, good.text


async def test_sessions_list_and_revoke(client: Any) -> None:
    u = await make_user(client, Role.SALES_MANAGER)
    other = await login(client, u.email)
    mine = (await client.get(f"{API}/auth/sessions", headers=u.headers)).json()
    assert len(mine) == 2 and sum(1 for s in mine if s["current"]) == 1
    target = next(s for s in mine if not s["current"])
    r = await client.delete(f"{API}/auth/sessions/{target['id']}", headers=u.headers)
    assert r.status_code == 204
    # The revoked session's access token stops working at once.
    assert (await client.get(f"{API}/auth/me", headers=other)).status_code == 401
    assert (await client.get(f"{API}/auth/me", headers=u.headers)).status_code == 200


async def test_users_cannot_revoke_other_peoples_sessions(client: Any) -> None:
    a = await make_user(client, Role.SALES_MANAGER)
    b = await make_user(client, Role.SALES_MANAGER)
    sessions = (await client.get(f"{API}/auth/sessions", headers=b.headers)).json()
    r = await client.delete(f"{API}/auth/sessions/{sessions[0]['id']}", headers=a.headers)
    assert r.status_code in (403, 404)
    assert (await client.get(f"{API}/auth/me", headers=b.headers)).status_code == 200


async def test_password_rules(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    base = {
        "email": "weak@example-itcraft.in",
        "full_name": "Weak Pass",
        "initials": "WP",
        "roles": ["sales_manager"],
    }
    for pw in (
        "short1A!",
        "aaaaaaaaaaaaaaaa",
        "password1234",
        "weak@example-itcraft.in",
        "Weak Pass 12345",
    ):
        r = await client.post(f"{API}/users", json={**base, "password": pw}, headers=admin.headers)
        assert r.status_code == 422, (pw, r.text)
    r = await client.post(
        f"{API}/users", json={**base, "password": PASSWORD}, headers=admin.headers
    )
    assert r.status_code == 201, r.text
    dup = await client.post(
        f"{API}/users", json={**base, "password": PASSWORD}, headers=admin.headers
    )
    assert dup.status_code == 409


async def test_changing_password_ends_other_sessions(client: Any) -> None:
    u = await make_user(client, Role.SALES_MANAGER)
    other = await login(client, u.email)
    r = await client.post(
        f"{API}/auth/password",
        json={"current_password": PASSWORD, "new_password": "Another-Strong-Pass-77"},
        headers=u.headers,
    )
    assert r.status_code == 204, r.text
    assert (await client.get(f"{API}/auth/me", headers=other)).status_code == 401
    assert (await _login_raw(client, u.email, PASSWORD)).status_code == 401
    assert (await _login_raw(client, u.email, "Another-Strong-Pass-77")).status_code == 200


async def test_deactivated_user_cannot_sign_in_and_tokens_stop(client: Any) -> None:
    u = await make_user(client, Role.SALES_MANAGER)
    admin = await make_user(client, Role.ADMIN)
    version = (await client.get(f"{API}/users/{u.id}", headers=admin.headers)).json()["version"]
    r = await client.patch(
        f"{API}/users/{u.id}", json={"is_active": False, "version": version}, headers=admin.headers
    )
    assert r.status_code == 200, r.text
    assert (await client.get(f"{API}/auth/me", headers=u.headers)).status_code == 401
    assert (await _login_raw(client, u.email, PASSWORD)).status_code == 401


async def test_security_headers_and_problem_json(client: Any) -> None:
    r = await client.get(f"{API}/auth/me")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "traceback" not in r.text.lower()
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors" in r.headers.get("content-security-policy", "")
