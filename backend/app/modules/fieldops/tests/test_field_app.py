"""The field app on a phone (Phase 12A): location at check-in, stamped photos, what an uploaded
export contains, the export before the work against the export after, the single-use upload
link, the phone's sync state for the Director and the engineers' workload."""

from __future__ import annotations

import base64
import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update

from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.core.timeutil import utcnow
from app.modules.fieldops.models import FieldUploadLink, RunEvidence
from app.modules.fieldops.tests.test_field_flow import _code, _png, _post, field_ready
from app.modules.identity.permissions import Role
from app.modules.verification.seed import seed_verification
from tests.helpers import make_user

API = "/api/v1"
FIELD = f"{API}/field"


def _exp(mfa: str, admin_pass: str = "s3cret-one") -> bytes:
    raw = (
        f"firmwareVersion=SonicOS 7.1.2-7019&adminTwoFactorAuth={mfa}&ipsGlobalEnable=on"
        f"&adminPassword={admin_pass}&syslogEnable=on&"
    )
    return base64.b64encode(raw.encode())


async def _firewall_run(client: Any) -> tuple[Any, Any, dict[str, Any]]:
    """A firewall task handed to the engineer who is also a technical lead, accepted."""
    async with get_sessionmaker()() as s:
        await seed_verification(s)
        await s.commit()
    p, eng, runs = await field_ready(client)
    run = next(r for r in runs if r["device_type"] == "firewall" and not r["depends_on"])
    rid = run["id"]
    r = await _post(client, p.pm, f"{rid}/reassign", {"assignee_id": str(eng.id), "reason": "Near"})
    assert r.status_code == 200, r.text
    assert (await _post(client, eng, f"{rid}/accept")).status_code == 200
    return p, eng, run


async def _add(
    client: Any,
    user: Any,
    run: dict[str, Any],
    i: int,
    *,
    located: bool = True,
    export: bytes | None = None,
    stamped: bool = False,
    note: str | None = None,
) -> Any:
    req = run["evidence_reqs"][i]
    data: dict[str, str] = {"requirement_index": str(i), "client_id": str(uuid.uuid4())}
    if located:
        data.update(lat="19.07", lng="72.87", accuracy_m="9")
    elif note:
        data["location_note"] = note
    files: dict[str, Any] = {}
    if req["type"] in ("photo", "screenshot"):
        files["file"] = ("e.png", _png(), "image/png")
        if stamped:
            files["stamped"] = ("e-stamped.png", _png(), "image/png")
    elif req["type"] == "config_export":
        files["file"] = ("TZ270.exp", export or _exp("on"), "text/plain")
    else:
        data["text_value"] = "Backup on the NAS share, taken with the customer"
    return await client.post(
        f"{FIELD}/runs/{run['id']}/evidence", data=data, files=files or None, headers=user.headers
    )


async def _check_in(client: Any, eng: Any, run: dict[str, Any]) -> None:
    rid = run["id"]
    assert (await _add(client, eng, run, 0, stamped=True)).status_code == 201
    await client.post(f"{FIELD}/runs/{rid}/codes/check_in", headers=eng.headers)
    r = await _post(
        client,
        eng,
        f"{rid}/check-in",
        {"code": await _code(rid, "otp_check_in"), "lat": 19.07, "lng": 72.87},
    )
    assert r.json()["run"]["state"] == "checked_in", r.text


async def test_location_is_required_at_check_in_and_best_effort_after(client: Any) -> None:
    _p, eng, run = await _firewall_run(client)
    rid = run["id"]

    # the arrival photo needs a location
    r = await _add(client, eng, run, 0, located=False, note="Permission denied")
    assert r.status_code == 422 and r.json()["code"] == "location_required"
    r = await _add(client, eng, run, 0, stamped=True)
    assert r.status_code == 201, r.text
    photo = r.json()
    assert photo["lat"] == 19.07 and photo["location_note"] is None
    assert photo["stamped_file_id"] and photo["stamped_file_id"] != photo["file_id"]
    assert photo["created_at"]  # the server's own time is kept next to the phone's

    # check-in itself needs a location
    await client.post(f"{FIELD}/runs/{rid}/codes/check_in", headers=eng.headers)
    code = await _code(rid, "otp_check_in")
    r = await _post(client, eng, f"{rid}/check-in", {"code": code})
    assert r.status_code == 422 and r.json()["code"] == "location_required"
    r = await _post(client, eng, f"{rid}/check-in", {"code": code, "lat": 19.07, "lng": 72.87})
    assert r.json()["run"]["state"] == "checked_in", r.text

    # later evidence without a location is kept, with the reason
    note = next(i for i, x in enumerate(run["evidence_reqs"]) if x["type"] == "note")
    r = await _add(client, eng, run, note, located=False, note="No GPS fix in the server room")
    assert r.status_code == 201 and r.json()["location_note"] == "No GPS fix in the server room"
    snap = next(
        i
        for i, x in enumerate(run["evidence_reqs"])
        if x["type"] == "config_export" and x["stage"] == "prechecks"
    )
    r = await _add(client, eng, run, snap, located=False)
    assert r.status_code == 201 and r.json()["location_note"] == "Location not available"


async def test_snapshot_parse_summary_and_the_before_and_after_diff(client: Any) -> None:
    _p, eng, run = await _firewall_run(client)
    rid = run["id"]
    reqs = run["evidence_reqs"]
    snap = next(
        i for i, x in enumerate(reqs) if x["type"] == "config_export" and x["stage"] == "prechecks"
    )
    assert reqs[snap].get("snapshot") is True
    after = next(
        (i for i, x in enumerate(reqs) if x["type"] == "config_export" and x["stage"] == "work"),
        None,
    )
    assert after is not None, "a firewall task asks for an export after the work"

    diff = (await client.get(f"{FIELD}/runs/{rid}/config-diff", headers=eng.headers)).json()
    assert diff["available"] is False and "before" in diff["reason"]

    await _check_in(client, eng, run)
    # the export before the work: MFA off. Its parse result is shown at once.
    r = await _add(client, eng, run, snap, export=_exp("off", "old-pass"))
    assert r.status_code == 201, r.text
    parse = r.json()["parse"]
    assert parse["readable"] and parse["brand"] == "sonicwall" and parse["settings_read"] >= 5
    assert parse["targets_total"] == len(run["baseline"]) and parse["targets_from_file"] >= 1
    assert "sonicwall" in parse["message"].lower()

    for i, x in enumerate(reqs):
        if x["stage"] == "prechecks" and i != snap:
            assert (await _add(client, eng, run, i)).status_code == 201
    assert (await _post(client, eng, f"{rid}/prechecks-done")).json()["run"]["state"] == (
        "prechecks_done"
    )
    for i in range(len(run["steps"])):
        await _post(client, eng, f"{rid}/steps/{i}")
    values = {f["key"]: "enabled" for f in run["baseline"]}
    for f in run["baseline"]:
        if f["expected"].lower().startswith(("at least", "above")):
            values[f["key"]] = "99"
    await _post(client, eng, f"{rid}/values", {"values": values})
    assert (await _post(client, eng, f"{rid}/configured")).json()["run"]["state"] == "configured"

    # the export after the work: MFA on, a new password, logging gone
    newer = base64.b64encode(
        b"firmwareVersion=SonicOS 7.1.2-7019&adminTwoFactorAuth=on&ipsGlobalEnable=on"
        b"&adminPassword=new-pass&radiusServer=10.0.0.5&"
    )
    assert (await _add(client, eng, run, after, export=newer)).status_code == 201
    diff = (await client.get(f"{FIELD}/runs/{rid}/config-diff", headers=eng.headers)).json()
    assert diff["available"] and diff["method"] == "settings" and diff["brand"] == "sonicwall"
    by_key = {c["key"]: c for c in diff["changes"]}
    assert by_key["adminTwoFactorAuth"] == {
        "key": "adminTwoFactorAuth",
        "before": "off",
        "after": "on",
        "change": "changed",
    }
    assert by_key["radiusServer"]["change"] == "added"
    assert by_key["syslogEnable"]["change"] == "removed"
    # secrets never appear, before or after
    assert by_key["adminPassword"]["before"] == "(hidden)"
    assert "old-pass" not in str(diff) and "new-pass" not in str(diff)
    assert diff["unchanged"] >= 2

    # only the export after the work is checked: the old one had MFA off and would fail it
    for i, x in enumerate(reqs):
        if x["stage"] == "work" and i != after and x.get("required", True):
            assert (await _add(client, eng, run, i)).status_code == 201
    r = await _post(client, eng, f"{rid}/submit-evidence")
    assert r.json()["run"]["state"] == "engine_check", r.json()["checks"]


async def test_lines_are_compared_when_exports_are_not_settings(client: Any) -> None:
    _p, eng, run = await _firewall_run(client)
    rid = run["id"]
    reqs = run["evidence_reqs"]
    snap = next(
        i for i, x in enumerate(reqs) if x["type"] == "config_export" and x["stage"] == "prechecks"
    )
    after = next(
        i for i, x in enumerate(reqs) if x["type"] == "config_export" and x["stage"] == "work"
    )
    await _check_in(client, eng, run)
    old = b"# exported\ninterface X0\n ip 10.0.0.1\nsnmp community public-read\n"
    await _add(client, eng, run, snap, export=old)
    async with get_sessionmaker()() as s:  # straight to the work stage; the walk is tested above
        from app.modules.fieldops.models import TaskRun

        await s.execute(
            update(TaskRun).where(TaskRun.id == uuid.UUID(rid)).values(state="configured")
        )
        await s.commit()
    new = b"# exported\ninterface X0\n ip 10.0.0.2\nsnmp community new-secret\n"
    assert (await _add(client, eng, run, after, export=new)).status_code == 201
    diff = (await client.get(f"{FIELD}/runs/{rid}/config-diff", headers=eng.headers)).json()
    assert diff["available"] and diff["method"] == "lines"
    shown = [c["before"] or c["after"] for c in diff["changes"]]
    assert " ip 10.0.0.1" in shown and " ip 10.0.0.2" in shown
    assert "(hidden)" in shown and "new-secret" not in str(diff) and "public-read" not in str(diff)


async def test_the_upload_link_works_once_then_expires(client: Any) -> None:
    _p, eng, run = await _firewall_run(client)
    rid = run["id"]
    reqs = run["evidence_reqs"]
    snap = next(
        i for i, x in enumerate(reqs) if x["type"] == "config_export" and x["stage"] == "prechecks"
    )
    photo = 0

    # only for configuration exports, only by the engineer the task belongs to
    r = await client.post(
        f"{FIELD}/runs/{rid}/upload-links", json={"requirement_index": photo}, headers=eng.headers
    )
    assert r.status_code == 422 and r.json()["code"] == "not_an_export"
    await get_redis().flushall()
    other = await make_user(client, Role.FIELD_ENGINEER)
    r = await client.post(
        f"{FIELD}/runs/{rid}/upload-links", json={"requirement_index": snap}, headers=other.headers
    )
    assert r.status_code == 404

    await _check_in(client, eng, run)
    r = await client.post(
        f"{FIELD}/runs/{rid}/upload-links", json={"requirement_index": snap}, headers=eng.headers
    )
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["valid_minutes"] == 15 and first["qr_svg"].startswith("<")
    assert re.fullmatch(r"/upload/[A-Za-z0-9_-]{30,}", first["path"])
    token = first["path"].rsplit("/", 1)[1]
    async with get_sessionmaker()() as s:  # only a hash of the token is stored
        stored = list(await s.scalars(select(FieldUploadLink.token_hash)))
    assert token not in stored and len(stored) == 1

    # a second link cancels the first
    r = await client.post(
        f"{FIELD}/runs/{rid}/upload-links", json={"requirement_index": snap}, headers=eng.headers
    )
    second = r.json()["path"].rsplit("/", 1)[1]
    pub = f"{API}/public/field-upload"
    assert (await client.get(f"{pub}/{token}")).json()["code"] == "link_invalid"

    # anyone with the link sees the task and what to upload, without signing in
    info = await client.get(f"{pub}/{second}")
    assert info.status_code == 200, info.text
    body = info.json()
    assert body["task_ref"] == run["task_ref"] and "rollback" in body["label"]
    assert "price" not in str(body).lower() and "@" not in str(body)

    # a refused file does not use the link up
    bad = await client.post(
        f"{pub}/{second}",
        files={"file": ("x.exe", b"MZ\x90\x00binary", "application/x-msdownload")},
    )
    assert bad.status_code in (415, 422), bad.text
    ok = await client.post(
        f"{pub}/{second}", files={"file": ("TZ270.exp", _exp("off"), "text/plain")}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["received"] and ok.json()["parse"]["brand"] == "sonicwall"
    again = await client.post(
        f"{pub}/{second}", files={"file": ("TZ270.exp", _exp("off"), "text/plain")}
    )
    assert again.status_code == 409 and again.json()["code"] == "link_used"

    # the evidence belongs to the engineer, marked as sent through a link, and is in the history
    detail = (await client.get(f"{FIELD}/runs/{rid}", headers=eng.headers)).json()
    ev = next(e for e in detail["evidence"] if e["requirement_index"] == snap)
    assert ev["via"] == "link" and ev["uploaded_by"] == str(eng.id)
    actions = [e["action"] for e in detail["events"]]
    assert "upload_link_made" in actions and actions.count("evidence_added") >= 2

    # an expired link is refused
    r = await client.post(
        f"{FIELD}/runs/{rid}/upload-links", json={"requirement_index": snap}, headers=eng.headers
    )
    late = r.json()["path"].rsplit("/", 1)[1]
    async with get_sessionmaker()() as s:
        await s.execute(
            update(FieldUploadLink)
            .where(FieldUploadLink.used_at.is_(None), FieldUploadLink.revoked_at.is_(None))
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()
    assert (await client.get(f"{pub}/{late}")).json()["code"] == "link_expired"
    assert (await client.get(f"{pub}/short")).json()["code"] == "link_invalid"


async def test_the_director_sees_each_phone_sync_state(client: Any) -> None:
    p, eng, _run = await _firewall_run(client)
    rows = (await client.get(f"{FIELD}/engineers", headers=p.c.director.headers)).json()
    me = next(r for r in rows if r["user_id"] == str(eng.id))
    assert me["state"] == "never" and me["open_tasks"] >= 1

    now = utcnow()
    r = await client.post(
        f"{FIELD}/device-status",
        json={
            "pending": 3,
            "failed": 0,
            "oldest_pending_at": (now - timedelta(minutes=40)).isoformat(),
            "last_sync_at": (now - timedelta(minutes=50)).isoformat(),
            "app_version": "2026.10.8",
            "platform": "Android",
        },
        headers=eng.headers,
    )
    assert r.status_code == 204, r.text
    me = next(
        r
        for r in (await client.get(f"{FIELD}/engineers", headers=p.pm.headers)).json()
        if r["user_id"] == str(eng.id)
    )
    assert me["state"] == "waiting" and me["pending"] == 3 and "online" in me["summary"]
    assert "3 item(s) waiting" in me["summary"]

    # no word for a while: the phone is shown offline with its work waiting
    from app.modules.fieldops.models import FieldDeviceStatus

    async with get_sessionmaker()() as s:
        await s.execute(update(FieldDeviceStatus).values(reported_at=now - timedelta(hours=2)))
        await s.commit()
    me = next(
        r
        for r in (await client.get(f"{FIELD}/engineers", headers=p.pm.headers)).json()
        if r["user_id"] == str(eng.id)
    )
    assert me["state"] == "waiting" and me["summary"].startswith("offline")

    await client.post(
        f"{FIELD}/device-status", json={"pending": 0, "failed": 2}, headers=eng.headers
    )
    rows = (await client.get(f"{FIELD}/engineers", headers=p.pm.headers)).json()
    assert rows[0]["user_id"] == str(eng.id) and rows[0]["state"] == "refused"

    # engineers report, they do not read the others' state (this one is only an engineer)
    plain = p.eng[0]
    assert (await client.get(f"{FIELD}/engineers", headers=plain.headers)).status_code == 403
    assert (
        await client.post(
            f"{FIELD}/device-status", json={"pending": 0, "failed": 0}, headers=p.pm.headers
        )
    ).status_code == 403


async def test_workload_per_engineer(client: Any) -> None:
    p, eng, _run = await _firewall_run(client)
    rows = (await client.get(f"{FIELD}/workload", headers=p.pm.headers)).json()
    me = next(r for r in rows if r["user_id"] == str(eng.id))
    assert me["open_tasks"] >= 1 and len(me["days"]) == 14
    assert sum(d["tasks"] for d in me["days"]) <= me["open_tasks"]
    assert (await client.get(f"{FIELD}/workload", headers=eng.headers)).status_code == 403


async def test_evidence_location_is_stored_on_the_row(client: Any) -> None:
    _p, eng, run = await _firewall_run(client)
    r = await _add(client, eng, run, 0)
    async with get_sessionmaker()() as s:
        ev = await s.get(RunEvidence, uuid.UUID(r.json()["id"]))
    assert ev is not None and ev.lat == 19.07 and ev.accuracy_m == 9 and ev.via == "app"
