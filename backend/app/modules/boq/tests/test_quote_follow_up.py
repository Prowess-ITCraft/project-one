"""After a quote is drafted (backlog 1, 2 and 5): lines under the minimum margin need the
approver to accept each one with a reason, lapsed prices are re-priced in one step, quotes are
won or lost with a reason, and the owner hears before a quote's prices lapse."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_sessionmaker
from app.core.timeutil import today_ist
from app.modules.boq import service
from app.modules.boq.models import BoqOutcome
from app.modules.boq.tests.test_boq_flow import _approved, edit, generate, price_the_rest, ready
from app.modules.notifications.models import Notification
from tests.helpers import idem

API = "/api/v1"


async def _submitted(client: Any, c: Any) -> dict[str, Any]:
    b = await generate(client, c)
    b = await price_the_rest(client, c, b)
    r = await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_low_margin_lines_are_accepted_one_by_one_with_a_reason(client: Any) -> None:
    c = await ready(client)
    b = await generate(client, c)
    b = await price_the_rest(client, c, b)
    first = b["lines"][0]
    r = await edit(
        client,
        c.sm,
        b,
        [
            {
                "op": "update_line",
                "id": first["id"],
                "fields": {
                    "unit_price": "1000.00",
                    "cost": "950.00",
                    "manual_price_reason": "Matched a competitor",
                },
            }
        ],
        "Matched the competitor's price",
    )
    b = r.json()
    low = next(x for x in b["lines"] if x["id"] == first["id"])
    assert "low_margin" in low["flags"] and low["margin_pct"] == "5.0"
    assert b["min_margin_pct"] == "10"
    assert any("minimum" in w for w in b["warnings"])
    assert (await client.post(f"{API}/boq/{b['id']}/submit", headers=c.sm.headers)).status_code == (
        200
    )

    r = await client.post(
        f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.head.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "low_margin_ack_required"
    assert r.json()["lines"] == [first["id"]] and r.json()["refs"] == [low["ref"]]
    r = await client.post(
        f"{API}/boq/{b['id']}/pricing-decision",
        json={"approve": True, "margin_ack": [first["id"]]},
        headers=c.head.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "low_margin_reason_required"
    r = await client.post(
        f"{API}/boq/{b['id']}/pricing-decision",
        json={
            "approve": True,
            "margin_ack": [first["id"]],
            "note": "Strategic account; the support contract carries the margin.",
        },
        headers=c.head.headers,
    )
    assert r.status_code == 200 and r.json()["stage"] == "pricing_approved"
    log = (await client.get(f"{API}/boq/{b['id']}/edits", headers=c.sm.headers)).json()
    approved = next(e for e in log if e["action"] == "pricing_approved")
    assert "accepted margin under 10%" in approved["detail"][0]


async def test_the_minimum_margin_is_a_company_setting(client: Any) -> None:
    c = await ready(client)
    company = (await client.get(f"{API}/boq/company", headers=c.sm.headers)).json()
    assert company["min_margin_pct"] == 10
    async with get_sessionmaker()() as s:
        row_version: int = (
            await s.execute(text("SELECT version FROM company_settings WHERE key = 'company'"))
        ).scalar_one()
    for bad in (-1, 95, "lots"):
        r = await client.put(
            f"{API}/boq/company",
            json={"data": {**company, "min_margin_pct": bad}, "version": row_version},
            headers=c.director.headers,
        )
        assert r.status_code == 422, bad
    r = await client.put(
        f"{API}/boq/company",
        json={"data": {**company, "quote_prefix": "IT Craft!"}, "version": row_version},
        headers=c.director.headers,
    )
    assert r.status_code == 422
    r = await client.put(
        f"{API}/boq/company",
        json={"data": {**company, "min_margin_pct": 20}, "version": row_version},
        headers=c.director.headers,
    )
    assert r.status_code == 200, r.text
    # the test prices carry 15 percent, now under the minimum
    b = await generate(client, c)
    priced = [x for x in b["lines"] if x["price_source"] == "price_book"]
    assert priced and all("low_margin" in x["flags"] for x in priced)
    # people who do not see prices see no margins
    view = await client.get(f"{API}/boq/{b['id']}", headers=c.lead.headers)
    if view.status_code == 200:
        assert all(x["margin_pct"] is None and x["cost"] is None for x in view.json()["lines"])


async def test_reprice_takes_todays_prices_and_goes_for_approval(client: Any) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    r = await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    assert r.status_code == 201, r.text
    b = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    stale = await client.post(
        f"{API}/boq/{b['id']}/reprice", json={"draft_rev": b["draft_rev"] - 1}, headers=c.sm.headers
    )
    assert stale.status_code == 409
    r = await client.post(
        f"{API}/boq/{b['id']}/reprice", json={"draft_rev": b["draft_rev"]}, headers=c.sm.headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submitted"] is True and body["stage"] == "pricing_review"
    log = (await client.get(f"{API}/boq/{b['id']}/edits", headers=c.sm.headers)).json()
    assert [e["action"] for e in log[:2]] == ["submitted", "prices_refreshed"]
    # the person who re-priced cannot approve it; a sales head can, then v2 is issued
    r = await client.post(
        f"{API}/boq/{b['id']}/pricing-decision", json={"approve": True}, headers=c.head.headers
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    assert r.status_code == 201 and r.json()["number"] == 2


async def test_won_and_lost_with_a_reason(client: Any) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    # nothing issued yet: nothing to lose
    r = await client.post(
        f"{API}/boq/{b['id']}/outcome",
        json={"outcome": "lost", "reason": "price"},
        headers=c.sm.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "not_issued"
    await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})

    r = await client.post(
        f"{API}/boq/{b['id']}/outcome", json={"outcome": "lost"}, headers=c.sm.headers
    )
    assert r.status_code == 422 and r.json()["code"] == "reason_required"
    r = await client.post(
        f"{API}/boq/{b['id']}/outcome",
        json={"outcome": "lost", "reason": "other"},
        headers=c.sm.headers,
    )
    assert r.json()["code"] == "note_required"
    r = await client.post(
        f"{API}/boq/{b['id']}/outcome",
        json={
            "outcome": "lost",
            "reason": "competitor",
            "competitor": "Acme IT",
            "note": "Cheaper",
        },
        headers=c.sm.headers,
    )
    assert r.status_code == 200, r.text
    lost = r.json()
    assert lost["outcome"] == "lost" and lost["outcome_reason"] == "competitor"
    assert lost["status"] == "closed"
    # a lost quote cannot be edited until it is opened again, with a reason
    e = await edit(client, c.sm, lost, [{"op": "update_settings", "fields": {"validity_days": 7}}])
    assert e.status_code == 409 and e.json()["code"] == "boq_locked"
    r = await client.post(
        f"{API}/boq/{b['id']}/outcome", json={"outcome": "open"}, headers=c.sm.headers
    )
    assert r.json()["code"] == "note_required"
    r = await client.post(
        f"{API}/boq/{b['id']}/outcome",
        json={"outcome": "open", "note": "Customer came back after the competitor fell through"},
        headers=c.sm.headers,
    )
    assert r.status_code == 200 and r.json()["outcome"] == "open" and r.json()["status"] == "draft"

    # accepting records the win
    v = (await client.get(f"{API}/boq/{b['id']}/versions", headers=c.sm.headers)).json()[0]
    r = await client.post(
        f"{API}/boq/{b['id']}/versions/{v['number']}/accept",
        json={
            "po_number": "PO-2026-118",
            "po_date": str(today_ist()),
            "selected_options": {
                g: next(iter(o)) for g, o in v["totals"].get("options", {}).items()
            },
        },
        headers={**c.sm.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    view = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    assert view["outcome"] == "won"
    history = (await client.get(f"{API}/boq/{b['id']}/outcomes", headers=c.sm.headers)).json()
    assert [h["outcome"] for h in history] == ["lost", "open", "won"]
    assert history[0]["competitor"] == "Acme IT"
    r = await client.post(
        f"{API}/boq/{b['id']}/outcome",
        json={"outcome": "lost", "reason": "price"},
        headers=c.sm.headers,
    )
    assert r.json()["code"] == "already_won"
    # the history cannot be rewritten
    async with get_sessionmaker()() as s:
        assert (await s.scalar(select(BoqOutcome).limit(1))) is not None
        with pytest.raises(DBAPIError, match="append only"):
            await s.execute(text("UPDATE boq_outcomes SET reason = 'price'"))


async def test_the_owner_hears_before_a_quote_lapses(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    maker = get_sessionmaker()
    assert await service.quote_expiry_alerts(maker) == 0  # five days left: nothing yet

    # four days later its prices lapse tomorrow
    later = today_ist() + timedelta(days=4)
    monkeypatch.setattr(service, "today_ist", lambda: later)
    sent = await service.quote_expiry_alerts(maker)
    assert sent >= 2  # the issuer and the sales head
    async with maker() as s:
        notes = list(
            await s.scalars(select(Notification).where(Notification.template == "quote_expiring"))
        )
    emails = [n for n in notes if n.channel == "email"]
    assert {n.to_user_id for n in emails} >= {c.sm.id, c.head.id}
    assert all("expires tomorrow" in n.subject for n in emails)
    inbox = [n for n in notes if n.channel == "in_app"]
    assert inbox and inbox[0].link == f"/projects/{c.pid}#boq"
    assert await service.quote_expiry_alerts(maker) == 0  # never twice for the same day

    # lost quotes are left alone
    await client.post(
        f"{API}/boq/{b['id']}/outcome",
        json={"outcome": "lost", "reason": "budget"},
        headers=c.sm.headers,
    )
    async with maker() as s:
        await s.execute(text("DELETE FROM notifications"))
        await s.commit()
    assert await service.quote_expiry_alerts(maker) == 0
