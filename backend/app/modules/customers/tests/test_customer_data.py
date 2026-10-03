"""Sites, contacts, projects, members, gate configuration and customer acknowledgement."""

from __future__ import annotations

import re
from typing import Any

from app.modules.customers.tests.test_gates import _audit_artifact, _lead
from app.modules.identity.permissions import Role
from tests.helpers import idem, make_customer, make_user, make_workspace

API = "/api/v1"


async def test_sites_crud_with_soft_delete(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    c = await make_customer(client, sm.headers)
    base = f"{API}/customers/{c['id']}/sites"
    site = {
        "name": "Pune plant",
        "address_line1": "Plot 4, MIDC",
        "city": "Pune",
        "state": "Maharashtra",
        "pincode": "411019",
    }
    r = await client.post(base, json=site, headers=sm.headers)
    assert r.status_code == 201, r.text
    s = r.json()
    bad = await client.post(base, json={**site, "pincode": "abc"}, headers=sm.headers)
    assert bad.status_code == 422
    r = await client.patch(
        f"{base}/{s['id']}", json={"city": "Pimpri", "version": s["version"]}, headers=sm.headers
    )
    assert r.status_code == 200 and r.json()["city"] == "Pimpri"
    stale = await client.patch(
        f"{base}/{s['id']}", json={"city": "Old", "version": s["version"]}, headers=sm.headers
    )
    assert stale.status_code == 409
    assert (await client.delete(f"{base}/{s['id']}", headers=sm.headers)).status_code == 204
    assert (await client.get(base, headers=sm.headers)).json() == []
    assert (await client.post(f"{base}/{s['id']}/restore", headers=sm.headers)).status_code == 200
    assert len((await client.get(base, headers=sm.headers)).json()) == 1


async def test_contacts_crud_and_validation(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    c = await make_customer(client, sm.headers)
    base = f"{API}/customers/{c['id']}/contacts"
    r = await client.post(
        base,
        json={
            "full_name": "Amit Shah",
            "email": "amit@shakti.example",
            "phone": "+91 98200 12345",
            "can_sign_off": True,
        },
        headers=sm.headers,
    )
    assert r.status_code == 201, r.text
    contact = r.json()
    for bad in (
        {"full_name": "A"},
        {"full_name": "Ok Name", "email": "not-an-email"},
        {"full_name": "Ok Name", "phone": "x"},
    ):
        assert (await client.post(base, json=bad, headers=sm.headers)).status_code == 422
    r = await client.patch(
        f"{base}/{contact['id']}",
        json={"designation": "Accounts head", "version": contact["version"]},
        headers=sm.headers,
    )
    assert r.status_code == 200 and r.json()["designation"] == "Accounts head"
    assert (await client.delete(f"{base}/{contact['id']}", headers=sm.headers)).status_code == 204
    assert (
        await client.post(f"{base}/{contact['id']}/restore", headers=sm.headers)
    ).status_code == 200
    # Another customer's children are not reachable through this customer's URL.
    other = await make_customer(client, sm.headers, legal_name="Other Works Pvt Ltd")
    r = await client.patch(
        f"{API}/customers/{other['id']}/contacts/{contact['id']}",
        json={"designation": "x", "version": 1},
        headers=sm.headers,
    )
    assert r.status_code == 404


async def test_project_update_members_and_status(client: Any) -> None:
    ws = await make_workspace(client)
    p = ws.project
    r = await client.patch(
        f"{API}/projects/{p['id']}",
        json={"name": "IT infra hardening phase 1", "status": "on_hold", "version": p["version"]},
        headers=ws.sales.headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "on_hold"
    # An on-hold project cannot move through gates.
    r = await client.post(
        f"{API}/projects/{p['id']}/stages/audit_intake/submit",
        json={},
        headers={**ws.auditor.headers, **idem()},
    )
    assert r.status_code == 409 and r.json()["code"] == "project_not_active"
    members = (
        await client.get(f"{API}/projects/{p['id']}/members", headers=ws.head.headers)
    ).json()
    assert {m["project_role"] for m in members} >= {"audit_engineer", "solution_architect"}
    r = await client.delete(
        f"{API}/projects/{p['id']}/members/{ws.auditor.id}", headers=ws.head.headers
    )
    assert r.status_code == 204
    assert (
        await client.get(f"{API}/projects/{p['id']}", headers=ws.auditor.headers)
    ).status_code == 404
    # Sales managers cannot manage members.
    r = await client.put(
        f"{API}/projects/{p['id']}/members",
        json={"user_id": str(ws.auditor.id), "project_role": "audit_engineer"},
        headers=ws.sales.headers,
    )
    assert r.status_code == 403


async def test_gate_config_is_admin_only_and_validated(client: Any) -> None:
    admin = await make_user(client, Role.ADMIN)
    sm = await make_user(client, Role.SALES_MANAGER)
    cfgs = (await client.get(f"{API}/gates", headers=sm.headers)).json()
    assert cfgs[0]["stage"] == "audit_intake" and len(cfgs) == 8
    audit = cfgs[0]
    body = {
        "approver_roles": ["technical_lead"],
        "requires_artifact": True,
        "requires_customer_ack": False,
        "version": audit["version"],
    }
    assert (
        await client.put(f"{API}/gates/audit_intake", json=body, headers=sm.headers)
    ).status_code == 403
    r = await client.put(f"{API}/gates/audit_intake", json=body, headers=admin.headers)
    assert r.status_code == 200 and r.json()["approver_roles"] == ["technical_lead"]
    bad = await client.put(
        f"{API}/gates/audit_intake",
        json={**body, "approver_roles": ["customer_rep"], "version": r.json()["version"]},
        headers=admin.headers,
    )
    assert bad.status_code == 422


async def test_customer_acknowledgement_unblocks_the_gate(client: Any) -> None:
    ws = await make_workspace(client)
    admin = await make_user(client, Role.ADMIN)
    lead = await _lead(client, ws)
    cfg = (await client.get(f"{API}/gates", headers=admin.headers)).json()[0]
    r = await client.put(
        f"{API}/gates/audit_intake",
        json={
            "approver_roles": ["technical_lead"],
            "requires_artifact": True,
            "requires_customer_ack": True,
            "version": cfg["version"],
        },
        headers=admin.headers,
    )
    assert r.status_code == 200, r.text
    contact = (
        await client.post(
            f"{API}/customers/{ws.customer['id']}/contacts",
            json={"full_name": "Amit Shah", "email": "amit@shakti.example", "can_sign_off": True},
            headers=ws.sales.headers,
        )
    ).json()
    art = await _audit_artifact(client, ws)
    sub = (
        await client.post(
            f"{API}/projects/{ws.project_id}/stages/audit_intake/submit",
            json={"artifact_id": art},
            headers={**ws.auditor.headers, **idem()},
        )
    ).json()
    approve = f"{API}/projects/{ws.project_id}/submissions/{sub['id']}/approve"
    r = await client.post(approve, json={}, headers={**lead.headers, **idem()})
    assert r.status_code == 409 and r.json()["code"] == "customer_ack_missing"

    r = await client.post(
        f"{API}/projects/{ws.project_id}/submissions/{sub['id']}/customer-ack",
        json={"contact_id": contact["id"]},
        headers=ws.sales.headers,
    )
    assert r.status_code == 201, r.text
    token = re.search(r"([A-Za-z0-9_\-]{20,})$", r.json()["url"]).group(1)  # type: ignore[union-attr]
    view = await client.get(f"{API}/public/acks/{token}")
    assert view.status_code == 200 and view.json()["stage_label"]
    # Wrong confirmations are refused, the right one is single use.
    assert (
        await client.post(f"{API}/public/acks/{token}", json={"full_name": "X", "accept": True})
    ).status_code == 422
    assert (
        await client.post(
            f"{API}/public/acks/{token}", json={"full_name": "Amit Shah", "accept": False}
        )
    ).status_code == 422
    ok = await client.post(
        f"{API}/public/acks/{token}", json={"full_name": "Amit Shah", "accept": True}
    )
    assert ok.status_code == 204, ok.text
    again = await client.post(
        f"{API}/public/acks/{token}", json={"full_name": "Amit Shah", "accept": True}
    )
    assert again.status_code == 204  # repeating a used link is harmless, not a second approval
    assert (await client.get(f"{API}/public/acks/not-a-real-token-at-all-0000")).status_code == 404

    r = await client.post(approve, json={}, headers={**lead.headers, **idem()})
    assert r.status_code == 200, r.text
