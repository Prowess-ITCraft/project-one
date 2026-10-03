"""Verification end to end (phase 9): a firewall task checked against its SonicWall export,
deviations opened and closed by the checks, the verifier's rules, the policy and the dashboard."""

from __future__ import annotations

import base64
import uuid
from typing import Any

from app.core import outbox
from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.modules.fieldops.tests.test_field_flow import _code, _post, field_ready
from app.modules.identity.permissions import Role
from app.modules.verification.seed import seed_verification
from tests.helpers import make_user

API = "/api/v1"
FIELD = f"{API}/field"
VER = f"{API}/verification"


def sonicwall_exp(mfa: str, admin: str = "fw-admin") -> bytes:
    raw = f"firmwareVersion=SonicOS 7.1.2-7019&adminTwoFactorAuth={mfa}&ipsGlobalEnable=on&adminName={admin}&syslogEnable=on&"
    return base64.b64encode(raw.encode())


async def _ev(client: Any, user: Any, run: dict[str, Any], i: int, mfa: str = "on") -> None:
    req = run["evidence_reqs"][i]
    data = {"requirement_index": str(i), "client_id": str(uuid.uuid4())}
    files = None
    if req["type"] in ("photo", "screenshot"):
        from app.modules.fieldops.tests.test_field_flow import _png

        files = {"file": ("e.png", _png(), "image/png")}
    elif req["type"] == "config_export":
        files = {"file": ("TZ270.exp", sonicwall_exp(mfa), "text/plain")}
    elif req["type"] == "serial":
        data["text_value"] = "SW-SN-1"
    else:
        data["text_value"] = "Checked with the customer's IT contact"
    r = await client.post(
        f"{FIELD}/runs/{run['id']}/evidence", data=data, files=files, headers=user.headers
    )
    assert r.status_code == 201, r.text


async def walk_to_configured(client: Any, p: Any, eng: Any, run: dict[str, Any], mfa: str) -> None:
    rid = run["id"]
    await _post(
        client, p.pm, f"{rid}/reassign", {"assignee_id": str(eng.id), "reason": "Verification test"}
    )
    await _post(client, eng, f"{rid}/accept")
    await client.post(f"{FIELD}/runs/{rid}/codes/check_in", headers=eng.headers)
    await _ev(client, eng, run, 0)
    r = await _post(client, eng, f"{rid}/check-in", {"code": await _code(rid, "otp_check_in")})
    assert r.json()["run"]["state"] == "checked_in", r.text
    for i in (1, 2):
        await _ev(client, eng, run, i)
    await _post(client, eng, f"{rid}/prechecks-done")
    for i in range(len(run["steps"])):
        await _post(client, eng, f"{rid}/steps/{i}")
    # the engineer types what they see; the export is what counts where a mapping exists
    values = {f["key"]: "enabled" for f in run["baseline"]}
    r = await _post(client, eng, f"{rid}/values", {"values": values})
    assert r.status_code == 200, r.text
    assert (await _post(client, eng, f"{rid}/configured")).json()["run"]["state"] == "configured"
    for i in range(3, len(run["evidence_reqs"])):
        await _ev(client, eng, run, i, mfa)


async def test_exports_drive_the_check_and_the_deviation_register(client: Any) -> None:
    async with get_sessionmaker()() as s:
        await seed_verification(s)
    p, both, runs = await field_ready(client)
    run = next(r for r in runs if r["device_type"] == "firewall" and not r["depends_on"])
    rid = run["id"]
    await walk_to_configured(client, p, both, run, mfa="off")

    # unconfirmed mapping: the export says MFA is off, but a guessed key never sends work back
    r = await _post(client, both, f"{rid}/submit-evidence")
    body = r.json()
    check = body["checks"][-1]
    mfa = next(f for f in check["result"]["fields"] if f["key"] == "admin_mfa")
    assert mfa["outcome"] == "not_checked" and "not confirmed" in mfa["reason"]
    assert check["driver"] == "sonicwall.exports.v1"
    assert body["run"]["state"] == "engine_check"

    # an admin confirms the mapping; the same export now fails the check and sends it back
    await get_redis().flushall()
    admin = await make_user(client, Role.ADMIN)
    maps = (
        await client.get(f"{VER}/mappings", params={"brand": "sonicwall"}, headers=admin.headers)
    ).json()
    m = next(x for x in maps if x["field_key"] == "admin_mfa")
    r = await client.patch(
        f"{VER}/mappings/{m['id']}",
        json={"version": m["version"], "verified": True},
        headers=admin.headers,
    )
    assert r.status_code == 200 and r.json()["verified"] is True
    # back to configured through the verifier, then check again
    await client.post(f"{FIELD}/runs/{rid}/codes/handover", headers=both.headers)
    await _post(client, both, f"{rid}/hand-over", {"code": await _code(rid, "otp_handover")})
    await _post(
        client,
        p.lead,
        f"{rid}/decision",
        {"decision": "reject", "reason": "Recheck MFA from the export"},
    )
    r = await _post(client, both, f"{rid}/submit-evidence")
    assert r.json()["run"]["state"] == "configured" and r.json()["checks"][-1]["passed"] is False
    await outbox.dispatch_batch(get_sessionmaker())

    devs = (await client.get(f"{VER}/projects/{p.pid}/deviations", headers=p.lead.headers)).json()
    open_mfa = next(d for d in devs if d["field_key"] == "admin_mfa")
    assert (open_mfa["status"], open_mfa["severity"], open_mfa["actual"]) == (
        "open",
        "critical",
        "off",
    )

    # a critical deviation cannot be accepted, whoever asks
    r = await client.post(
        f"{VER}/deviations/{open_mfa['id']}/accept",
        json={"note": "Customer is fine"},
        headers=p.lead.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "not_acceptable"

    # a verifier records a minor issue; the engineer who did the work cannot add or accept one
    r = await client.post(
        f"{VER}/deviations",
        json={
            "run_id": rid,
            "label": "Rack label missing",
            "severity": "minor",
            "note": "Label the firewall in the rack",
        },
        headers=both.headers,
    )
    assert r.status_code == 403 and r.json()["code"] == "segregation_of_duties"
    r = await client.post(
        f"{VER}/deviations",
        json={
            "run_id": rid,
            "label": "Rack label missing",
            "severity": "minor",
            "note": "Label the firewall in the rack",
        },
        headers=p.lead.headers,
    )
    assert r.status_code == 201, r.text
    minor = r.json()
    r = await client.post(
        f"{VER}/deviations/{minor['id']}/accept",
        json={"note": "Customer labels it themselves"},
        headers=p.lead.headers,
    )
    assert r.json()["status"] == "accepted"

    # fixed on the device: a new export passes and the register closes the deviation by itself
    run_now = (await client.get(f"{FIELD}/runs/{rid}", headers=both.headers)).json()["run"]
    export_index = next(
        i for i, e in enumerate(run_now["evidence_reqs"]) if e["type"] == "config_export"
    )
    await _ev(client, both, run_now, export_index, mfa="on")
    r = await _post(client, both, f"{rid}/submit-evidence")
    assert r.json()["checks"][-1]["passed"] is True
    await outbox.dispatch_batch(get_sessionmaker())
    devs = (await client.get(f"{VER}/projects/{p.pid}/deviations", headers=p.lead.headers)).json()
    closed = next(d for d in devs if d["id"] == open_mfa["id"])
    assert (
        closed["status"] == "resolved" and "Passed on configuration check" in closed["resolution"]
    )

    # the Director's dashboard sees the project, its field state and no open critical issue
    await get_redis().flushall()
    director = await make_user(client, Role.DIRECTOR)
    dash = (await client.get(f"{API}/dashboard", headers=director.headers)).json()
    proj = next(x for x in dash["projects"] if x["id"] == p.pid)
    assert proj["field"]["total"] == len(runs) and proj["open_deviations"]["critical"] == 0
    assert dash["totals"]["projects"] >= 1 and dash["totals"]["checkins_today"] >= 1


async def test_policy_and_the_export_inspector(client: Any) -> None:
    async with get_sessionmaker()() as s:
        await seed_verification(s)
    director = await make_user(client, Role.DIRECTOR)
    await get_redis().flushall()
    lead = await make_user(client, Role.TECHNICAL_LEAD)
    assert (await client.get(f"{VER}/policy", headers=lead.headers)).json()[
        "certificate_blocking"
    ] == ["critical"]
    bad = await client.put(
        f"{VER}/policy", json={"certificate_blocking": ["major"]}, headers=director.headers
    )
    assert bad.status_code == 422 and bad.json()["code"] == "critical_required"
    ok = await client.put(
        f"{VER}/policy",
        json={"certificate_blocking": ["critical", "major"]},
        headers=director.headers,
    )
    assert ok.status_code == 200 and ok.json()["certificate_blocking"] == ["critical", "major"]
    assert (
        await client.put(
            f"{VER}/policy", json={"certificate_blocking": ["critical"]}, headers=lead.headers
        )
    ).status_code == 403

    r = await client.post(
        f"{VER}/inspect",
        files={"file": ("TZ270.exp", sonicwall_exp("on", admin="admin"), "text/plain")},
        headers=lead.headers,
    )
    body = r.json()
    assert (
        body["brand"] == "sonicwall"
        and body["shape"] == "exp"
        and body["keys"]["adminName"] == "admin"
    )
    hit = next(x for x in body["matches"] if x["field_key"] == "default_admin")
    assert hit["matched_key"] == "adminName" and hit["verified"] is False
