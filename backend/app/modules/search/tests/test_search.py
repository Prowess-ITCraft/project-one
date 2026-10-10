"""Global search (backlog 11): full text and partial matches across customers, projects,
quotes, field tasks and catalogue items, fed by the outbox, filtered by role. A field engineer
finds their own tasks and never a quote or a price."""

from __future__ import annotations

from typing import Any

from app.core import outbox
from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.modules.fieldops.tests.test_field_flow import field_ready
from app.modules.identity.permissions import Role
from app.modules.search import service
from tests.helpers import make_user

API = "/api/v1"


async def _drain() -> None:
    maker = get_sessionmaker()
    for _ in range(20):
        if not await outbox.dispatch_batch(maker):
            break


async def _find(client: Any, user: Any, q: str, **params: Any) -> list[dict[str, Any]]:
    r = await client.get(f"{API}/search", params={"q": q, **params}, headers=user.headers)
    assert r.status_code == 200, r.text
    return list(r.json())


async def test_search_finds_everything_people_may_open_and_nothing_else(client: Any) -> None:
    p, _both, runs = await field_ready(client)
    await _drain()
    async with get_sessionmaker()() as s:  # the seeded catalogue went in without events
        await service.reindex(s)
    sales = p.c.sm
    customer = p.c.ws.customer

    # a customer by part of its name, a project by its code, a quote by part of its reference
    hits = await _find(client, sales, customer["display_name"].split()[0][:5])
    assert any(h["kind"] == "customer" and h["url"] == f"/customers/{customer['id']}" for h in hits)
    project = (await client.get(f"{API}/projects/{p.pid}", headers=sales.headers)).json()
    hits = await _find(client, sales, project["code"])
    assert hits[0]["kind"] == "project" and hits[0]["url"] == f"/projects/{p.pid}"
    quote = next(h for h in await _find(client, sales, "ITCraft", kind="quote"))
    assert quote["url"] == f"/projects/{p.pid}#boq" and "v1" in quote["subtitle"]
    tail = quote["title"].rsplit("/", 1)[1]
    assert any(h["title"] == quote["title"] for h in await _find(client, sales, tail))
    # catalogue items by code or name, without a price anywhere
    items = await _find(client, sales, "firewall", kind="item")
    assert items and all("₹" not in str(h) and "price" not in str(h).lower() for h in items)

    # a field engineer: their own tasks and catalogue items, never a quote
    eng = p.eng[0]
    mine = {r["id"] for r in runs if r["assignee_id"] == str(eng.id)}
    task = next(r for r in runs if r["id"] in mine)
    hits = await _find(client, eng, task["task_ref"], kind="task")
    assert hits and {h["url"].rsplit("/", 1)[1] for h in hits} <= mine
    assert await _find(client, eng, "ITCraft", kind="quote") == []
    assert all(h["kind"] != "quote" for h in await _find(client, eng, quote["title"]))
    # the project manager sees every task on the project
    all_refs = await _find(client, p.pm, "T0", kind="task", limit=30)
    assert len(all_refs) >= len({r["id"] for r in runs if r["task_ref"].startswith("T0")}) - 1

    # someone outside the project finds nothing of it
    await get_redis().flushall()
    stranger = await make_user(client, Role.SALES_MANAGER)
    assert all(h["kind"] in ("item",) for h in await _find(client, stranger, project["code"]))

    # too short or only punctuation: no search
    assert await _find(client, sales, "a") == []
    assert await _find(client, sales, "%%") == []


async def test_changes_reach_the_index_and_reindex_rebuilds_it(client: Any) -> None:
    p, _both, _runs = await field_ready(client)
    await _drain()
    head = p.c.ws.head
    cust = p.c.ws.customer
    r = await client.patch(
        f"{API}/customers/{cust['id']}",
        json={"display_name": "Zephyr Pumps", "version": cust["version"]},
        headers=head.headers,
    )
    if r.status_code == 409:  # the customer changed while the project was set up
        fresh = (await client.get(f"{API}/customers/{cust['id']}", headers=head.headers)).json()
        r = await client.patch(
            f"{API}/customers/{cust['id']}",
            json={"display_name": "Zephyr Pumps", "version": fresh["version"]},
            headers=head.headers,
        )
    assert r.status_code == 200, r.text
    await _drain()
    hits = await _find(client, head, "zephyr")
    assert [h["title"] for h in hits if h["kind"] == "customer"] == ["Zephyr Pumps"]

    async with get_sessionmaker()() as s:
        counts = await service.reindex(s)
    assert counts["customer"] >= 1 and counts["project"] >= 1 and counts["task"] >= 1
    assert counts.get("quote", 0) >= 1 and counts.get("item", 0) >= 1
    assert await _find(client, head, "zephyr")
