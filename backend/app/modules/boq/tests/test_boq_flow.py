"""The BOQ from a locked gap register to an accepted, purchase-order-backed version."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core import outbox
from app.core.db import get_sessionmaker
from app.core.timeutil import today_ist
from app.modules.boq.seed import seed_boq
from app.modules.identity.permissions import Role
from tests.helpers import (
    BRIEF,
    Workspace,
    approve_baseline,
    idem,
    make_user,
    make_workspace,
    seed_reference_data,
)

API = "/api/v1"
SAMPLES = Path(__file__).parents[5] / "samples"
PRICES = {
    "SVC-SANITIZE": "500.00",
    "LIC-ACRONIS-XDR": "1562.00",
    "SVC-EPS-SETUP": "12000.00",
    "HW-SW-CISCO-C1300-24T": "33972.00",
    "SVC-SWITCH-SETUP": "6000.00",
    "HW-FW-SOPHOS-XGS108": "66812.00",
    "HW-FW-FORTI-FG40F": "109653.00",
    "SVC-FW-SETUP": "12000.00",
    "SVC-FW-SUPPORT": "15000.00",
}


class Ctx:
    def __init__(self, ws: Workspace, head: Any, director: Any, lead: Any) -> None:
        self.ws, self.head, self.director, self.lead = ws, head, director, lead
        self.sm = ws.sales
        self.pid = ws.project_id


async def fresh_prices(client: Any, user: Any) -> None:
    today = today_ist()
    for code, selling in PRICES.items():
        item = (
            await client.get(f"{API}/catalogue/items", params={"q": code}, headers=user.headers)
        ).json()["items"][0]
        r = await client.post(
            f"{API}/catalogue/items/{item['id']}/prices",
            json={
                "supplier": "Distributor",
                "cost": selling,
                "selling": selling,
                "quoted_on": str(today),
                "valid_until": str(today + timedelta(days=10)),
                "source_note": "Test quote",
            },
            headers={**user.headers, **idem()},
        )
        assert r.status_code == 201, r.text


async def ready(client: Any, brief: dict[str, Any] | None = None) -> Ctx:
    await seed_reference_data()
    async with get_sessionmaker()() as s:
        await seed_boq(s)
    ws = await make_workspace(client)
    head = await make_user(client, Role.SALES_HEAD)
    director = await make_user(client, Role.DIRECTOR)
    lead = await make_user(client, Role.TECHNICAL_LEAD)
    for u, role in ((head, "sales_head"), (director, "director")):
        r = await client.put(
            f"{API}/projects/{ws.project_id}/members",
            json={"user_id": str(u.id), "project_role": role},
            headers=ws.head.headers,
        )
        assert r.status_code == 200, r.text
    await fresh_prices(client, ws.sales)
    await approve_baseline(client, ws)
    r = await client.put(
        f"{API}/projects/{ws.project_id}/brief",
        json={**BRIEF, **(brief or {})},
        headers=ws.sales.headers,
    )
    assert r.status_code == 200, r.text
    arch = ws.architect.headers
    cur = (await client.post(f"{API}/projects/{ws.project_id}/infra/current", headers=arch)).json()
    await client.post(
        f"{API}/projects/{ws.project_id}/infra/{cur['id']}/lock", headers={**arch, **idem()}
    )
    reg = (await client.post(f"{API}/projects/{ws.project_id}/gaps", headers=arch)).json()
    for g in reg["gaps"]:
        if g["status"] == "verify":
            await client.patch(
                f"{API}/projects/{ws.project_id}/gaps/{reg['id']}/items/{g['id']}",
                json={
                    "status": "dismissed",
                    "reason": "Checked with the customer on site.",
                    "version": g["version"],
                },
                headers=arch,
            )
    r = await client.post(
        f"{API}/projects/{ws.project_id}/gaps/{reg['id']}/lock", headers={**arch, **idem()}
    )
    assert r.status_code == 200, r.text
    async with get_sessionmaker()() as s:
        await s.execute(
            text("UPDATE projects SET current_stage = 'boq' WHERE id = :p"), {"p": ws.project_id}
        )
        await s.commit()
    return Ctx(ws, head, director, lead)


async def generate(client: Any, c: Ctx) -> dict[str, Any]:
    r = await client.post(f"{API}/projects/{c.pid}/boq/generate", json={}, headers=c.sm.headers)
    assert r.status_code == 201, r.text
    return dict(r.json())


def line(b: dict[str, Any], title: str) -> dict[str, Any]:
    return next(x for x in b["lines"] if x["title"].startswith(title))


async def edit(
    client: Any,
    user: Any,
    b: dict[str, Any],
    ops: list[dict[str, Any]],
    reason: str = "Edited in test",
) -> Any:
    return await client.post(
        f"{API}/boq/{b['id']}/edit",
        json={"draft_rev": b["draft_rev"], "reason": reason, "ops": ops},
        headers=user.headers,
    )


async def price_the_rest(client: Any, c: Ctx, b: dict[str, Any]) -> dict[str, Any]:
    """Enter prices by hand for every unpriced line: the price book cannot know them."""
    ops = [
        {
            "op": "update_line",
            "id": x["id"],
            "fields": {
                "unit_price": "1000.00",
                "cost": "800.00",
                "manual_price_reason": "Distributor quote, phone call",
            },
        }
        for x in b["lines"]
        if x["unit_price"] is None
    ]
    r = await edit(client, c.sm, b, ops, "Entered prices from today's distributor quotes")
    assert r.status_code == 200, r.text
    return dict(r.json())


# ------------------------------------------------------------------ generation


async def test_generate_turns_gaps_into_a_priced_draft(client: Any) -> None:
    c = await ready(client)
    early = await client.post(f"{API}/projects/{c.pid}/boq/generate", json={}, headers=c.sm.headers)
    assert early.status_code == 201
    b = early.json()
    assert b["status"] == "draft" and b["stage"] == "drafting" and b["quote_ref"] is None
    assert [g["title"] for g in b["groups"]] == ["High Priority", "To Consider"]
    san, xdr = line(b, "System sanitization"), line(b, "Acronis XDR")
    assert (
        san["qty"] == 27
        and san["unit_price"] == "500.00"
        and san["amount"] == "13500.00"
        and san["price_source"] == "price_book"
    )
    assert xdr["qty"] == 27 and xdr["amount"] == "42174.00" and san["source"]["gap_codes"]
    # Options: reconfiguration, Sophos and FortiGate are alternatives under one number.
    fw = [
        x for x in b["lines"] if x["option_group"] == "fw-device" or x["option_group"] == "firewall"
    ]
    assert (
        len(fw) == 3
        and {x["ref"][-1] for x in fw} == {"A", "B", "C"}
        and len({x["ref"][:-1] for x in fw}) == 1
    )
    sophos = line(b, "Sophos XGS-108")
    assert (
        sophos["source"]["kind"] == "recommended"
        and "customer prefers Sophos" in sophos["source"]["note"]
    )
    assert any(
        "Sophos" in r["item"]
        for r in b["generation_report"]["recommendations"]["GAP-005:fw-device"]["ranked"]
    )
    # Prices the price book cannot give are NOT invented.
    nas = line(b, "NAS")
    assert nas["unit_price"] is None and "no_price" in nas["flags"]
    assert b["totals"]["complete"] is False and b["blockers"]
    assert {u["item"] for u in b["generation_report"]["unpriced"]} >= {
        "NAS",
        "Phoenix ODR",
        "Server for AD/DC",
    }
    # Cost is visible here because the caller may read prices; the field engineer cannot reach the BOQ at all.
    fe = await make_user(client, Role.FIELD_ENGINEER)
    assert (await client.get(f"{API}/projects/{c.pid}/boq", headers=fe.headers)).status_code == 403


async def test_excluded_brands_and_stock_swaps_are_respected(client: Any) -> None:
    c = await ready(client, {"excluded_brands": ["Fortinet"], "preferred_brands": []})
    b = await generate(client, c)
    assert not any(
        "FortiGate" in x["title"] and x["source"]["kind"] == "recommended" for x in b["lines"]
    )
    rec = b["generation_report"]["recommendations"]["GAP-005:fw-device"]
    assert any("excludes Fortinet" in x["reason"] for x in rec["rejected"])


async def test_out_of_stock_items_are_swapped_for_the_alternative(client: Any) -> None:
    await seed_reference_data()
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    sophos = (
        await client.get(f"{API}/catalogue/items", params={"q": "HW-FW-SOPHOS"}, headers=sa.headers)
    ).json()["items"][0]
    forti = (
        await client.get(f"{API}/catalogue/items", params={"q": "HW-FW-FORTI"}, headers=sa.headers)
    ).json()["items"][0]
    r = await client.post(
        f"{API}/catalogue/items/{sophos['id']}/stock",
        json={
            "stock_status": "out_of_stock",
            "alternative_item_id": forti["id"],
            "version": sophos["version"],
        },
        headers=sa.headers,
    )
    assert r.status_code == 200
    c = await ready(client)
    b = await generate(client, c)
    swaps = b["generation_report"]["swaps"]
    assert any(s["from"].startswith("Sophos") and s["to"].startswith("FortiGate") for s in swaps)
    assert not any(x["title"].startswith("Sophos XGS-108") for x in b["lines"])


# ------------------------------------------------------------------ manual editing


async def test_every_kind_of_manual_edit(client: Any) -> None:
    c = await ready(client)
    b = await generate(client, c)
    hp = b["groups"][0]["id"]
    sec = b["sections"][0]["id"]
    # add section, add a manual line with a hand price, edit, move, delete, terms, settings
    r = await edit(
        client,
        c.sm,
        b,
        [
            {"op": "add_section", "group_id": hp, "title": "Installation labour"},
            {
                "op": "add_line",
                "section_id": sec,
                "index": 0,
                "line": {
                    "title": "Site survey and labour",
                    "qty": 2,
                    "uom": "day",
                    "unit_price": "4500.00",
                    "manual_price_reason": "ITCraft rate card 2026",
                },
            },
            {
                "op": "update_line",
                "id": line(b, "System sanitization")["id"],
                "fields": {"qty": 31, "description": "Per endpoint including spares"},
            },
            {"op": "delete_line", "id": line(b, "Acronis XDR")["id"]},
            {"op": "set_terms", "terms": ["GST @ 18% extra", "Valid for 5 days"]},
            {
                "op": "update_settings",
                "fields": {
                    "show_totals": True,
                    "show_gst_rows": True,
                    "intro": "Offer for your office IT.",
                },
            },
        ],
        "Director's adjustments after the site visit",
    )
    assert r.status_code == 200, r.text
    b2 = r.json()
    assert b2["draft_rev"] == b["draft_rev"] + 1
    assert (
        line(b2, "Site survey")["amount"] == "9000.00"
        and "manual_price" in line(b2, "Site survey")["flags"]
    )
    assert line(b2, "System sanitization")["qty"] == 31 and all(
        not x["title"].startswith("Acronis") for x in b2["lines"]
    )
    assert (
        b2["terms"] == ["GST @ 18% extra", "Valid for 5 days"]
        and b2["settings"]["show_totals"] is True
    )
    new_sec = next(s for s in b2["sections"] if s["title"] == "Installation labour")
    moved = await edit(
        client,
        c.director,
        b2,
        [{"op": "move_line", "id": line(b2, "Site survey")["id"], "section_id": new_sec["id"]}],
        "Belongs with labour",
    )
    assert (
        moved.status_code == 200
        and line(moved.json(), "Site survey")["section_id"] == new_sec["id"]
    )
    # A stale editor is refused; nothing is lost.
    stale = await edit(
        client, c.sm, b, [{"op": "update_line", "id": line(b2, "NAS")["id"], "fields": {"qty": 2}}]
    )
    assert stale.status_code == 409
    # No reason, no change.
    none = await client.post(
        f"{API}/boq/{b['id']}/edit",
        json={
            "draft_rev": moved.json()["draft_rev"],
            "reason": "",
            "ops": [{"op": "set_terms", "terms": []}],
        },
        headers=c.sm.headers,
    )
    assert none.status_code == 422
    # A price without a reason is refused.
    bad = await edit(
        client,
        c.sm,
        moved.json(),
        [{"op": "update_line", "id": line(b2, "NAS")["id"], "fields": {"unit_price": "40000.00"}}],
    )
    assert bad.status_code == 422 and bad.json()["code"] == "manual_price_reason"
    log = (await client.get(f"{API}/boq/{b['id']}/edits", headers=c.sm.headers)).json()
    assert log[0]["reason"] == "Belongs with labour" and any("Director" in x["reason"] for x in log)
    # Add from the catalogue.
    added = await client.post(
        f"{API}/boq/{b['id']}/add-item",
        json={
            "draft_rev": moved.json()["draft_rev"],
            "reason": "Customer also wants DLP",
            "item_code": "SW-DLP",
            "section_id": new_sec["id"],
            "qty": 1,
        },
        headers=c.director.headers,
    )
    assert added.status_code == 200 and line(added.json(), "DLP")["source"]["kind"] == "catalogue"


async def test_add_remove_and_reorder_options(client: Any) -> None:
    c = await ready(client)
    b = await generate(client, c)
    sophos, forti = line(b, "Sophos XGS-108"), line(b, "FortiGate FG40F")
    grp = sophos["option_group"]
    r = await edit(
        client,
        c.sm,
        b,
        [{"op": "update_line", "id": forti["id"], "fields": {"option_group": None}}],
        "Forti is a separate line now",
    )
    b2 = r.json()
    assert (
        line(b2, "FortiGate")["option_group"] is None
        and any("only" in w for w in b2["warnings"]) is False
    )
    r = await edit(
        client,
        c.sm,
        b2,
        [{"op": "update_line", "id": forti["id"], "fields": {"option_group": grp}}],
        "Back to an option",
    )
    b3 = r.json()
    r = await edit(
        client, c.sm, b3, [{"op": "set_option", "group": grp, "letter": "C"}], "Customer leans to C"
    )
    assert r.status_code == 200 and r.json()["selected_options"][grp] == "C"
    bad = await edit(client, c.sm, r.json(), [{"op": "set_option", "group": grp, "letter": "Z"}])
    assert bad.status_code == 422


# ------------------------------------------------------------------ pricing, segregation, issue


async def test_submission_needs_every_price_then_a_different_person_approves(client: Any) -> None:
    c = await ready(client)
    b = await generate(client, c)
    blocked = await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    assert (
        blocked.status_code == 409
        and blocked.json()["code"] == "boq_blockers"
        and blocked.json()["blockers"]
    )
    b = await price_the_rest(client, c, b)
    # The sales head helps with a correction, so the sales head cannot then approve the pricing.
    r = await edit(
        client,
        c.head,
        b,
        [
            {
                "op": "update_line",
                "id": line(b, "NAS")["id"],
                "fields": {
                    "unit_price": "41500.00",
                    "manual_price_reason": "Sales head renegotiated",
                },
            }
        ],
        "Better price from the distributor",
    )
    b = r.json()
    sub = await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    assert sub.status_code == 200 and sub.json()["stage"] == "pricing_review"
    # A sales manager has no pricing approval right at all.
    assert (
        await client.post(
            f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.sm.headers
        )
    ).status_code == 403
    same = await client.post(
        f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.head.headers
    )
    assert same.status_code == 403 and same.json()["code"] == "segregation_of_duties"
    # An edit after submission withdraws the review.
    e = await edit(
        client,
        c.sm,
        sub.json(),
        [{"op": "update_settings", "fields": {"validity_days": 7}}],
        "Customer asked for a longer validity",
    )
    assert e.json()["stage"] == "drafting"
    await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    not_approved = await client.post(
        f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()}
    )
    assert not_approved.status_code == 409 and not_approved.json()["code"] == "pricing_not_approved"
    sent_back = await client.post(
        f"{API}/boq/{b['id']}/pricing-decision",
        json={"approve": False, "note": "Margin on the NAS is too thin."},
        headers=c.director.headers,
    )
    assert sent_back.status_code == 200 and sent_back.json()["stage"] == "drafting"
    await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    ok = await client.post(
        f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.director.headers
    )
    assert ok.status_code == 200 and ok.json()["stage"] == "pricing_approved"


async def _approved(client: Any, c: Ctx) -> dict[str, Any]:
    b = await generate(client, c)
    b = await price_the_rest(client, c, b)
    assert (
        await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    ).status_code == 200
    r = await client.post(
        f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.head.headers
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_issue_assigns_the_quote_reference_and_versions_with_a_diff(client: Any) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    v1 = await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    assert v1.status_code == 201, v1.text
    v1 = v1.json()
    fy = (
        f"{today_ist().year % 100:02d}{(today_ist().year + 1) % 100:02d}"
        if today_ist().month >= 4
        else f"{(today_ist().year - 1) % 100:02d}{today_ist().year % 100:02d}"
    )
    assert (
        v1["number"] == 1
        and v1["quote_ref"] == f"ITCraft/TU/{fy}/001"
        and v1["change_summary"].startswith("First version")
    )
    # The customer wants changes: the draft carries on, and v2 shows what changed.
    cur = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    assert cur["quote_ref"] == v1["quote_ref"] and cur["stage"] == "drafting"
    r = await edit(
        client,
        c.sm,
        cur,
        [
            {
                "op": "update_line",
                "id": line(cur, "System sanitization")["id"],
                "fields": {"qty": 31},
            },
            {"op": "delete_line", "id": line(cur, "Acronis XDR")["id"]},
        ],
        "Customer has 31 systems and already owns XDR",
    )
    cur = r.json()
    await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    await client.post(
        f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.head.headers
    )
    v2 = (
        await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    ).json()
    assert (
        v2["number"] == 2
        and v2["quote_ref"] == v1["quote_ref"]
        and v2["change_summary"] == "1 removed, 1 changed."
    )
    states = {
        v["number"]: v["state"]
        for v in (await client.get(f"{API}/boq/{b['id']}/versions", headers=c.sm.headers)).json()
    }
    assert states == {1: "superseded", 2: "issued"}
    # Issued versions are immutable in the database too.
    import pytest

    async with get_sessionmaker()() as s:
        with pytest.raises(Exception):
            await s.execute(text("UPDATE boq_versions SET content = '{}'::jsonb WHERE number = 2"))
            await s.commit()


async def test_acceptance_locks_the_version_with_the_purchase_order(client: Any) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    v1 = (
        await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    ).json()
    cur = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    r = await edit(
        client,
        c.sm,
        cur,
        [{"op": "update_settings", "fields": {"validity_days": 7}}],
        "Longer validity",
    )
    await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    await client.post(
        f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.head.headers
    )
    v2 = (
        await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    ).json()
    po = {"po_number": "SHK/PO/2026/417", "po_date": str(today_ist())}
    old = await client.post(
        f"{API}/boq/{b['id']}/versions/1/accept", json=po, headers={**c.sm.headers, **idem()}
    )
    assert old.status_code == 409 and old.json()["code"] == "not_latest"
    need = await client.post(
        f"{API}/boq/{b['id']}/versions/2/accept", json=po, headers={**c.sm.headers, **idem()}
    )
    assert need.status_code == 422 and need.json()["code"] == "option_required"
    future = await client.post(
        f"{API}/boq/{b['id']}/versions/2/accept",
        json={
            **po,
            "po_date": str(today_ist() + timedelta(days=3)),
            "selected_options": {"firewall": "B"},
        },
        headers={**c.sm.headers, **idem()},
    )
    assert future.status_code == 422
    grp = line(cur, "Sophos XGS-108")["option_group"]
    ok = await client.post(
        f"{API}/boq/{b['id']}/versions/2/accept",
        json={**po, "selected_options": {grp: "B"}},
        headers={**c.sm.headers, **idem()},
    )
    assert ok.status_code == 200, ok.text
    acc = ok.json()
    assert (
        acc["state"] == "accepted"
        and acc["po_number"] == "SHK/PO/2026/417"
        and acc["selected_options"] == {grp: "B"}
    )
    assert (
        acc["totals"]["complete"] is True
        and acc["totals"]["subtotal_min"] == acc["totals"]["subtotal_max"]
    )
    # Locked: the draft cannot change, and the accepted version cannot change in the database.
    locked = await edit(client, c.sm, cur, [{"op": "set_terms", "terms": []}])
    assert locked.status_code == 409 and locked.json()["code"] == "boq_locked"
    await outbox.dispatch_batch(get_sessionmaker())
    arts = (
        await client.get(f"{API}/projects/{c.pid}/artifacts", headers=c.ws.architect.headers)
    ).json()
    boq_art = [a for a in arts if a["artifact_type"] == "boq_version"]
    assert (
        len(boq_art) == 1
        and "SHK/PO/2026/417" in boq_art[0]["title"]
        and boq_art[0]["stage"] == "boq"
    )
    import pytest

    async with get_sessionmaker()() as s:
        with pytest.raises(Exception):
            await s.execute(text("UPDATE boq_versions SET po_number = 'CHANGED' WHERE number = 2"))
            await s.commit()
    # A customer change after acceptance: reopen into a new draft, the accepted version stays.
    again = await client.post(
        f"{API}/boq/{b['id']}/reopen",
        json={"reason": "Customer added a branch office"},
        headers=c.sm.headers,
    )
    assert (
        again.status_code == 200
        and again.json()["status"] == "draft"
        and again.json()["selected_options"] == {}
    )
    assert (await client.get(f"{API}/boq/{b['id']}/versions/2", headers=c.sm.headers)).json()[
        "state"
    ] == "accepted"
    assert v1["number"] == 1


# ------------------------------------------------------------------ documents, history, master data


async def test_quotation_documents_follow_the_itcraft_format(client: Any) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    r = await client.get(
        f"{API}/boq/{b['id']}/render", params={"fmt": "html", "version": 1}, headers=c.sm.headers
    )
    assert r.status_code == 200
    h = r.text
    for needle in (
        "QUOTATION",
        "Sr N",
        "Components",
        "High Priority",
        "Quote Ref No: ITCraft/TU/",
        "Terms &amp; Conditions",
        "Thanking you and Regards",
        "₹ 66,812.00",
        "₹ 1,562.00",
        "Firewall Options",
    ):
        assert needle in h, needle
    import re

    assert re.search(r">\d+A<", h) and re.search(
        r">\d+B<", h
    )  # options share a number, like 6A and 6B
    assert (
        "Price" in h and "Amount" in h and "Grand total" not in h
    )  # totals rows are off by default, like the sample
    summary = await client.get(
        f"{API}/boq/{b['id']}/render",
        params={"fmt": "html", "kind": "summary", "version": 1},
        headers=c.sm.headers,
    )
    assert "BOQ" in summary.text and "₹" not in summary.text and "Price" not in summary.text
    x = await client.get(
        f"{API}/boq/{b['id']}/render", params={"fmt": "xlsx", "version": 1}, headers=c.sm.headers
    )
    assert x.status_code == 200 and x.content[:2] == b"PK"
    pdf = await client.get(
        f"{API}/boq/{b['id']}/render", params={"fmt": "pdf", "version": 1}, headers=c.sm.headers
    )
    assert pdf.status_code in (
        200,
        503,
    )  # 503 only where the PDF libraries are missing (this Windows host)
    if pdf.status_code == 200:
        assert pdf.content[:4] == b"%PDF"
    draft = await client.get(
        f"{API}/boq/{b['id']}/render", params={"fmt": "html"}, headers=c.sm.headers
    )
    assert "Draft" in draft.text or "ITCraft/" in draft.text


async def test_totals_rows_appear_only_when_asked_and_options_are_not_summed(client: Any) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    cur = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    await edit(
        client,
        c.sm,
        cur,
        [{"op": "update_settings", "fields": {"show_totals": True, "show_gst_rows": True}}],
        "Customer wants totals",
    )
    await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    await client.post(
        f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.head.headers
    )
    await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    h = (
        await client.get(
            f"{API}/boq/{b['id']}/render",
            params={"fmt": "html", "version": 2},
            headers=c.sm.headers,
        )
    ).text
    assert "Grand total" in h and "Sub total" in h and "GST @ 18%" in h and " to ₹" in h
    assert "not added together" in h


async def test_history_advice_comes_from_the_library_and_never_sets_a_price(client: Any) -> None:
    c = await ready(client)
    b = await generate(client, c)
    sm = c.sm
    empty = (
        await client.get(
            f"{API}/boq/{b['id']}/lines/{line(b, 'Sophos XGS-108')['id']}/history",
            headers=sm.headers,
        )
    ).json()
    assert empty["occurrences"] == 0
    pdf = next(SAMPLES.glob("*Sanitization*.pdf"))
    r = await client.post(
        "/api/v1/library/files",
        files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
        headers=sm.headers,
    )
    assert r.status_code == 201
    await outbox.dispatch_batch(get_sessionmaker())
    h = (
        await client.get(
            f"{API}/boq/{b['id']}/lines/{line(b, 'Sophos XGS-108')['id']}/history",
            headers=sm.headers,
        )
    ).json()
    assert (
        h["occurrences"] == 1
        and h["median_unit_price"] == "66812.00"
        and h["customers"] == 1
        and "Advice only" in h["note"]
    )
    assert (
        line(
            (await client.get(f"{API}/boq/{b['id']}", headers=sm.headers)).json(), "Sophos XGS-108"
        )["unit_price"]
        == "66812.00"
    )


async def test_recommender_explains_itself(client: Any) -> None:
    c = await ready(client, {"excluded_brands": ["Fortinet"], "preferred_brands": ["Sophos"]})
    b = await generate(client, c)
    r = (
        await client.get(
            f"{API}/boq/{b['id']}/recommend", params={"category": "firewall"}, headers=c.sm.headers
        )
    ).json()
    assert (
        r["ranked"][0]["name"].startswith("Sophos")
        and "customer prefers Sophos" in r["ranked"][0]["reasons"]
    )
    assert any("supports 50 users, 35 needed" in x for x in r["ranked"][0]["reasons"])
    assert [x["name"] for x in r["rejected"]] == ["FortiGate FG40F UTM with 3 year subscription"]


async def test_templates_company_and_weights_are_master_data(client: Any) -> None:
    c = await ready(client)
    admin = await make_user(client, Role.ADMIN)
    tpls = (await client.get(f"{API}/boq/templates", headers=c.head.headers)).json()
    dr = next(t for t in tpls if t["gap_type"] == "no_disaster_recovery")
    body = {"title": dr["title"], "lines": dr["lines"], "active": True, "version": dr["version"]}
    assert (
        await client.put(
            f"{API}/boq/templates/no_disaster_recovery", json=body, headers=c.sm.headers
        )
    ).status_code == 403
    lines = [{**dr["lines"][0], "qty": {"rule": "expr", "expr": "ceil(endpoint_count / 25)"}}]
    ok = await client.put(
        f"{API}/boq/templates/no_disaster_recovery",
        json={**body, "lines": lines},
        headers=c.head.headers,
    )
    assert ok.status_code == 200 and ok.json()["revision"] == 2
    bad = await client.put(
        f"{API}/boq/templates/no_disaster_recovery",
        json={
            **body,
            "version": ok.json()["version"],
            "lines": [{**dr["lines"][0], "item_code": "NOT-A-REAL-ITEM"}],
        },
        headers=c.head.headers,
    )
    assert bad.status_code == 422 and bad.json()["code"] == "template_item_missing"
    evil = await client.put(
        f"{API}/boq/templates/no_disaster_recovery",
        json={
            **body,
            "version": ok.json()["version"],
            "lines": [
                {**dr["lines"][0], "qty": {"rule": "expr", "expr": "__import__('os').system('x')"}}
            ],
        },
        headers=c.head.headers,
    )
    assert evil.status_code == 422
    stale = await client.put(
        f"{API}/boq/templates/no_disaster_recovery", json=body, headers=c.head.headers
    )
    assert stale.status_code == 409
    b = await generate(client, c)
    assert line(b, "Phoenix ODR")["qty"] == 2  # ceil(27 / 25)
    co = (await client.get(f"{API}/boq/company", headers=c.sm.headers)).json()
    assert co["quote_prefix"] == "ITCraft" and co["gstin"] == "27AAPCP3476M1ZL"
    assert (
        await client.put(
            f"{API}/boq/company",
            json={"data": {**co, "signatory_name": "Asha Menon"}, "version": 1},
            headers=c.head.headers,
        )
    ).status_code == 403
    assert (
        await client.put(
            f"{API}/boq/company",
            json={"data": {**co, "signatory_name": "Asha Menon"}, "version": 1},
            headers=admin.headers,
        )
    ).status_code == 200
    w = await client.put(
        f"{API}/boq/weights/small", json={"weights": {"vendor": 0.3}}, headers=admin.headers
    )
    assert (
        w.status_code == 200
        and (
            await client.put(
                f"{API}/boq/weights/small", json={"weights": {"nonsense": 1}}, headers=admin.headers
            )
        ).status_code
        == 422
    )


async def test_generation_needs_the_boq_stage_and_a_locked_register(client: Any) -> None:
    await seed_reference_data()
    async with get_sessionmaker()() as s:
        await seed_boq(s)
    ws = await make_workspace(client)
    r = await client.post(
        f"{API}/projects/{ws.project_id}/boq/generate", json={}, headers=ws.sales.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "not_boq_stage"
    assert (
        await client.get(f"{API}/projects/{ws.project_id}/boq", headers=ws.sales.headers)
    ).status_code == 404
