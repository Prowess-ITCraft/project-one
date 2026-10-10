"""From an approved audit to a locked gap register, and the rule change approval flow."""

from __future__ import annotations

from typing import Any

from app.core.db import get_sessionmaker
from app.modules.identity.permissions import Role
from tests.helpers import (
    BRIEF,
    Workspace,
    approve_baseline,
    drain_outbox,
    idem,
    make_user,
    make_workspace,
    seed_reference_data,
)

API = "/api/v1"


async def _ready(client: Any) -> Workspace:
    await seed_reference_data()
    ws = await make_workspace(client)
    await approve_baseline(client, ws)
    return ws


async def _brief(client: Any, ws: Workspace, **over: Any) -> dict[str, Any]:
    r = await client.put(
        f"{API}/projects/{ws.project_id}/brief", json={**BRIEF, **over}, headers=ws.sales.headers
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_intake_brief_validates_and_is_versioned(client: Any) -> None:
    ws = await make_workspace(client)
    assert (
        await client.get(f"{API}/projects/{ws.project_id}/brief", headers=ws.sales.headers)
    ).json() is None
    b = await _brief(client, ws)
    assert b["company_size"] == "small" and b["budget_ceiling"] == "600000.00" and b["version"] == 1
    bad = await client.put(
        f"{API}/projects/{ws.project_id}/brief",
        json={**BRIEF, "company_size": "huge"},
        headers=ws.sales.headers,
    )
    assert bad.status_code == 422
    stale = await client.put(
        f"{API}/projects/{ws.project_id}/brief",
        json={**BRIEF, "version": 9},
        headers=ws.sales.headers,
    )
    assert stale.status_code == 409
    ok = await client.put(
        f"{API}/projects/{ws.project_id}/brief",
        json={**BRIEF, "budget_tier": "premium", "version": 1},
        headers=ws.sales.headers,
    )
    assert ok.status_code == 200 and ok.json()["version"] == 2
    # Field engineers and outsiders cannot write it.
    fe = await make_user(client, Role.FIELD_ENGINEER)
    assert (
        await client.put(f"{API}/projects/{ws.project_id}/brief", json=BRIEF, headers=fe.headers)
    ).status_code == 403


async def test_current_and_ideal_state_then_gaps_lock_the_stage_outputs(client: Any) -> None:
    ws = await _ready(client)
    # The ideal state needs the intake questionnaire.
    cur = (
        await client.post(
            f"{API}/projects/{ws.project_id}/infra/current", headers=ws.architect.headers
        )
    ).json()
    assert cur["kind"] == "current" and cur["status"] == "draft" and cur["number"] == 1
    lenses = cur["data"]["lenses"]
    assert lenses["security"]["score"] == 58.7 and lenses["resilience"]["score"] == 50.0
    assert (
        cur["data"]["components"]["endpoints"]["count"] == 27
        and "nas.encryption" in cur["data"]["unknown_facts"]
    )
    early = await client.post(
        f"{API}/projects/{ws.project_id}/infra/ideal", headers=ws.architect.headers
    )
    assert early.status_code == 409 and early.json()["code"] == "current_not_locked"
    await client.post(
        f"{API}/projects/{ws.project_id}/infra/{cur['id']}/lock",
        headers={**ws.architect.headers, **idem()},
    )
    no_brief = await client.post(
        f"{API}/projects/{ws.project_id}/infra/ideal", headers=ws.architect.headers
    )
    assert no_brief.status_code == 422 and no_brief.json()["code"] == "brief_required"
    await _brief(client, ws)
    ideal = (
        await client.post(
            f"{API}/projects/{ws.project_id}/infra/ideal", headers=ws.architect.headers
        )
    ).json()
    assert ideal["data"]["tier"] == {"company_size": "small", "budget_tier": "standard"}
    s = ideal["data"]["summary"]
    assert (
        s["not_met"] >= 10
        and s["unknown"] >= 4
        and s["rules"] == s["met"] + s["not_met"] + s["unknown"]
    )
    assert any(t["code"] == "RES-DR" and t["status"] == "not_met" for t in ideal["data"]["targets"])
    await client.post(
        f"{API}/projects/{ws.project_id}/infra/{ideal['id']}/lock",
        headers={**ws.architect.headers, **idem()},
    )
    again = await client.post(
        f"{API}/projects/{ws.project_id}/infra/{ideal['id']}/lock",
        headers={**ws.architect.headers, **idem()},
    )
    assert again.status_code == 409
    await drain_outbox()
    arts = (
        await client.get(f"{API}/projects/{ws.project_id}/artifacts", headers=ws.architect.headers)
    ).json()
    assert {a["artifact_type"] for a in arts} == {
        "prismsuite_audit",
        "infra_current",
        "infra_ideal",
    }


async def test_gap_register_edit_verify_and_lock(client: Any) -> None:
    ws = await _ready(client)
    await _brief(client, ws)
    cur = (
        await client.post(
            f"{API}/projects/{ws.project_id}/infra/current", headers=ws.architect.headers
        )
    ).json()
    await client.post(
        f"{API}/projects/{ws.project_id}/infra/{cur['id']}/lock",
        headers={**ws.architect.headers, **idem()},
    )
    reg = (
        await client.post(f"{API}/projects/{ws.project_id}/gaps", headers=ws.architect.headers)
    ).json()
    assert reg["status"] == "draft" and reg["number"] == 1
    by_type = {g["gap_type"]: g for g in reg["gaps"]}
    assert (
        by_type["conflicting_av"]["code"].startswith("GAP-")
        and by_type["conflicting_av"]["qty_hint"] == 6
    )
    assert (
        by_type["conflicting_av"]["priority"] == "high"
        and by_type["backup_at_risk"]["priority"] == "high"
    )
    assert by_type["nas_not_hardened"]["status"] == "verify" and by_type["nas_not_hardened"][
        "title"
    ].startswith("Verify on site")
    rid = reg["id"]
    # Verify items block the lock until a person decides.
    blocked = await client.post(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/lock",
        headers={**ws.architect.headers, **idem()},
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "verify_open"

    # Edits need a reason and respect the version.
    g = by_type["underspec_hardware"]
    r = await client.patch(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/items/{g['id']}",
        json={
            "priority": "high",
            "qty_hint": 4,
            "reason": "Customer added a fourth laptop on site.",
            "version": g["version"],
        },
        headers=ws.architect.headers,
    )
    assert r.status_code == 200 and r.json()["priority"] == "high" and r.json()["qty_hint"] == 4
    stale = await client.patch(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/items/{g['id']}",
        json={"priority": "consider", "reason": "Testing the lock.", "version": g["version"]},
        headers=ws.architect.headers,
    )
    assert stale.status_code == 409
    no_reason = await client.patch(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/items/{g['id']}",
        json={"priority": "consider", "version": 2},
        headers=ws.architect.headers,
    )
    assert no_reason.status_code == 422

    # Turn one verify item into a real gap and dismiss the others with reasons.
    for t, g2 in by_type.items():
        if g2["status"] != "verify":
            continue
        body = {
            "status": "open" if t == "nas_not_hardened" else "dismissed",
            "reason": "Checked with the customer on site.",
            "version": g2["version"],
        }
        assert (
            await client.patch(
                f"{API}/projects/{ws.project_id}/gaps/{rid}/items/{g2['id']}",
                json=body,
                headers=ws.architect.headers,
            )
        ).status_code == 200

    # A manual gap, as the director's expertise may add one.
    man = await client.post(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/items",
        json={
            "title": "Guest Wi-Fi shares the office network",
            "component": "access_point",
            "lens": "security",
            "gap_type": "guest_wifi_open",
            "priority": "consider",
            "reason": "Seen during the walkthrough.",
        },
        headers=ws.architect.headers,
    )
    assert man.status_code == 201 and man.json()["source"] == "manual"

    # A disputed gap blocks the lock until it is settled.
    disp = by_type["server_xdr"]
    await client.patch(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/items/{disp['id']}",
        json={
            "status": "disputed",
            "reason": "Customer disputes this.",
            "version": disp["version"],
        },
        headers=ws.architect.headers,
    )
    assert (
        await client.post(
            f"{API}/projects/{ws.project_id}/gaps/{rid}/lock",
            headers={**ws.architect.headers, **idem()},
        )
    ).json()["code"] == "gap_disputed"
    cur_disp = (
        await client.get(
            f"{API}/projects/{ws.project_id}/gaps",
            params={"register_id": rid},
            headers=ws.architect.headers,
        )
    ).json()
    d = next(x for x in cur_disp["gaps"] if x["gap_type"] == "server_xdr")
    await client.patch(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/items/{d['id']}",
        json={
            "status": "dismissed",
            "reason": "Agreed to drop after review.",
            "version": d["version"],
        },
        headers=ws.architect.headers,
    )

    locked = await client.post(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/lock",
        headers={**ws.architect.headers, **idem()},
    )
    assert locked.status_code == 200 and locked.json()["status"] == "locked"
    # Locked means locked, in the service and in the database.
    e = await client.patch(
        f"{API}/projects/{ws.project_id}/gaps/{rid}/items/{g['id']}",
        json={"priority": "consider", "reason": "Too late to change.", "version": 3},
        headers=ws.architect.headers,
    )
    assert e.status_code == 409 and e.json()["code"] == "register_locked"
    import pytest
    from sqlalchemy import text

    async with get_sessionmaker()() as s:
        with pytest.raises(Exception):
            await s.execute(text("UPDATE gaps SET priority = 'consider'"))
            await s.commit()
    await drain_outbox()
    arts = (
        await client.get(f"{API}/projects/{ws.project_id}/artifacts", headers=ws.architect.headers)
    ).json()
    assert "gap_register" in {a["artifact_type"] for a in arts}


async def test_rule_changes_need_the_director(client: Any) -> None:
    await seed_reference_data()
    admin = await make_user(client, Role.ADMIN)
    director = await make_user(client, Role.DIRECTOR)
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    rules = (await client.get(f"{API}/infra/rules", headers=sa.headers)).json()
    dr = next(r for r in rules if r["code"] == "RES-DR")
    # Only admins propose; only the director decides.
    assert (
        await client.post(
            f"{API}/infra/rules/changes",
            json={"rule_id": dr["id"], "kind": "deactivate", "reason": "x"},
            headers=sa.headers,
        )
    ).status_code == 403
    bad = await client.post(
        f"{API}/infra/rules/changes",
        json={
            "rule_id": dr["id"],
            "kind": "update",
            "proposed": {"when": {"fact": "nope", "op": "eq", "value": 1}},
            "reason": "Testing validation.",
        },
        headers=admin.headers,
    )
    assert bad.status_code == 422 and bad.json()["code"] == "rule_invalid"
    ok = await client.post(
        f"{API}/infra/rules/changes",
        json={
            "rule_id": dr["id"],
            "kind": "update",
            "proposed": {"priority": "high"},
            "reason": "Customers lose more from no DR than we assumed.",
        },
        headers=admin.headers,
    )
    assert ok.status_code == 201, ok.text
    cid = ok.json()["id"]
    assert (await client.get(f"{API}/infra/rules/{dr['id']}", headers=sa.headers)).json()[
        "priority"
    ] == "consider"  # not yet
    dup = await client.post(
        f"{API}/infra/rules/changes",
        json={"rule_id": dr["id"], "kind": "deactivate", "reason": "Another change."},
        headers=admin.headers,
    )
    assert dup.status_code == 409
    assert (
        await client.post(
            f"{API}/infra/rules/changes/{cid}/decision",
            json={"approve": True},
            headers=admin.headers,
        )
    ).status_code == 403
    reject_no_note = await client.post(
        f"{API}/infra/rules/changes/{cid}/decision",
        json={"approve": False},
        headers=director.headers,
    )
    assert reject_no_note.status_code == 422
    done = await client.post(
        f"{API}/infra/rules/changes/{cid}/decision",
        json={"approve": True},
        headers=director.headers,
    )
    assert done.status_code == 200 and done.json()["status"] == "approved"
    after = (await client.get(f"{API}/infra/rules/{dr['id']}", headers=sa.headers)).json()
    assert after["priority"] == "high" and after["rule_version"] == 2
    new = await client.post(
        f"{API}/infra/rules/changes",
        json={
            "kind": "create",
            "proposed": {
                "code": "sec-wifi",
                "title": "Guest Wi-Fi is separate",
                "component": "access_point",
                "lens": "security",
                "gap_type": "guest_wifi_open",
                "priority": "consider",
                "when": {"fact": "access_point.count", "op": "gt", "value": 0},
                "recommendation": "Separate guest Wi-Fi.",
                "target": "Guest Wi-Fi on its own network.",
            },
            "reason": "New rule from the whiteboard.",
        },
        headers=admin.headers,
    )
    assert new.status_code == 201, new.text
    assert (
        await client.post(
            f"{API}/infra/rules/changes/{new.json()['id']}/decision",
            json={"approve": True},
            headers=director.headers,
        )
    ).status_code == 200
    assert any(
        r["code"] == "SEC-WIFI"
        for r in (await client.get(f"{API}/infra/rules", headers=sa.headers)).json()
    )


async def test_return_to_an_earlier_stage_needs_a_reason_and_keeps_history(client: Any) -> None:
    ws = await make_workspace(client)
    lead = await make_user(client, Role.TECHNICAL_LEAD)
    await client.put(
        f"{API}/projects/{ws.project_id}/members",
        json={"user_id": str(lead.id), "project_role": "technical_lead"},
        headers=ws.head.headers,
    )
    # Audit intake is the first stage: nothing is earlier.
    r = await client.post(
        f"{API}/projects/{ws.project_id}/return-to/audit_intake",
        json={"reason": "Nothing to return to."},
        headers=lead.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "not_earlier"
    assert (
        await client.post(
            f"{API}/projects/{ws.project_id}/return-to/audit_intake",
            json={"reason": "x"},
            headers=lead.headers,
        )
    ).status_code == 422
    assert (
        await client.post(
            f"{API}/projects/{ws.project_id}/return-to/audit_intake",
            json={"reason": "Sales cannot do this."},
            headers=ws.sales.headers,
        )
    ).status_code == 403
