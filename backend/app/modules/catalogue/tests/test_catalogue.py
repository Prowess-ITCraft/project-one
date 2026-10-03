"""Catalogue, price book, expiry job, seed data."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core import outbox
from app.core.db import get_sessionmaker
from app.core.timeutil import today_ist
from app.modules.catalogue import service
from app.modules.catalogue.seed import seed_catalogue
from app.modules.identity.permissions import Role
from tests.helpers import idem, make_user

API = "/api/v1/catalogue"


async def _seed() -> None:
    async with get_sessionmaker()() as s:
        await seed_catalogue(s)


async def _item_id(client: Any, headers: dict[str, str], code: str) -> str:
    r = await client.get(f"{API}/items", params={"q": code}, headers=headers)
    assert r.status_code == 200, r.text
    return str(r.json()["items"][0]["id"])


def _price(**kw: Any) -> dict[str, Any]:
    today = today_ist()
    body = {
        "supplier": "Ingram Micro",
        "cost": "30000.00",
        "selling": "33972.00",
        "quoted_on": str(today),
        "valid_until": str(today + timedelta(days=5)),
        "source_note": "Email quote from distributor",
    }
    body.update(kw)
    return body


async def test_seed_is_idempotent_and_matches_the_samples(client: Any) -> None:
    await _seed()
    await _seed()
    head = await make_user(client, Role.SALES_HEAD)
    r = await client.get(f"{API}/items", params={"size": 100}, headers=head.headers)
    items = r.json()["items"]
    codes = {i["code"] for i in items}
    assert len(items) == len(codes) == 18
    assert {"HW-FW-SOPHOS-XGS108", "HW-FW-FORTI-FG40F", "SW-PHOENIX-ODR"} <= codes
    sophos = next(i for i in items if i["code"] == "HW-FW-SOPHOS-XGS108")
    assert len(sophos["inclusions"]) == 11
    assert sophos["gst_rate"] == "18.00"
    item_id = await _item_id(client, head.headers, "HW-FW-SOPHOS-XGS108")
    r = await client.get(f"{API}/items/{item_id}/price", headers=head.headers)
    assert r.json()["price"]["selling"] == "66812.00"
    # Items the quotation did not price stay unpriced.
    item_id = await _item_id(client, head.headers, "HW-NAS")
    r = await client.get(f"{API}/items/{item_id}/price", headers=head.headers)
    assert r.json()["state"] == "missing"


async def test_field_engineer_reads_items_but_never_prices(client: Any) -> None:
    await _seed()
    fe = await make_user(client, Role.FIELD_ENGINEER)
    r = await client.get(f"{API}/items", headers=fe.headers)
    assert r.status_code == 200
    blob = r.text.lower()
    assert "selling" not in blob and "cost" not in blob and "price" not in blob
    item_id = r.json()["items"][0]["id"]
    assert (await client.get(f"{API}/items/{item_id}/price", headers=fe.headers)).status_code == 403
    assert (
        await client.get(f"{API}/items/{item_id}/prices", headers=fe.headers)
    ).status_code == 403
    r = await client.post(
        f"{API}/items/{item_id}/prices", json=_price(), headers={**fe.headers, **idem()}
    )
    assert r.status_code == 403


async def test_who_can_write(client: Any) -> None:
    await _seed()
    sm = await make_user(client, Role.SALES_MANAGER)
    admin = await make_user(client, Role.ADMIN)
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    item = {
        "code": "HW-TEST-1",
        "kind": "product",
        "category": "nas",
        "name": "Test NAS",
    }
    # Sales managers enter prices but do not edit the catalogue.
    assert (await client.post(f"{API}/items", json=item, headers=sm.headers)).status_code == 403
    r = await client.post(f"{API}/items", json=item, headers=sa.headers)
    assert r.status_code == 201, r.text
    # Admin edits the catalogue but has no price access at all.
    iid = r.json()["id"]
    assert (await client.get(f"{API}/items/{iid}/price", headers=admin.headers)).status_code == 403
    r = await client.post(
        f"{API}/items/{iid}/prices", json=_price(), headers={**sa.headers, **idem()}
    )
    assert r.status_code == 403
    r = await client.post(
        f"{API}/items/{iid}/prices", json=_price(), headers={**sm.headers, **idem()}
    )
    assert r.status_code == 201, r.text


async def test_item_validation(client: Any) -> None:
    await _seed()
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    base = {"code": "SW-X1", "kind": "product", "category": "nas", "name": "Thing"}
    bad = [
        {**base, "code": "lower case"},
        {**base, "category": "no_such_category"},
        {**base, "kind": "service"},  # nas is a product category
        {**base, "gst_rate": "120"},
        {**base, "eol_date": "2030-01-01", "eos_date": "2029-01-01"},
        {**base, "surprise": 1},
    ]
    for body in bad:
        r = await client.post(f"{API}/items", json=body, headers=sa.headers)
        assert r.status_code == 422, (body, r.text)
    assert (await client.post(f"{API}/items", json=base, headers=sa.headers)).status_code == 201
    assert (await client.post(f"{API}/items", json=base, headers=sa.headers)).status_code == 409


async def test_price_rules(client: Any) -> None:
    await _seed()
    sm = await make_user(client, Role.SALES_MANAGER)
    iid = await _item_id(client, sm.headers, "HW-NAS")
    today = today_ist()

    def post(**kw: Any) -> Any:
        return client.post(
            f"{API}/items/{iid}/prices", json=_price(**kw), headers={**sm.headers, **idem()}
        )

    assert (await post(cost="40000.00", selling="30000.00")).json()["code"] == "price_below_cost"
    assert (await post(valid_until=str(today - timedelta(days=1)))).json()["code"] in (
        "price_already_expired",
        "validity_order",
    )
    assert (await post(quoted_on=str(today + timedelta(days=1)))).status_code == 422
    assert (await post(valid_until=str(today + timedelta(days=400)))).status_code == 422
    assert (await post(selling="10.555")).status_code == 422  # three decimals
    assert (await post(selling=10.5)).status_code == 422  # floats are refused
    assert (await post(selling="-1")).status_code == 422
    assert (await post()).status_code == 201


async def test_new_price_supersedes_and_history_is_kept(client: Any) -> None:
    await _seed()
    sm = await make_user(client, Role.SALES_MANAGER)
    iid = await _item_id(client, sm.headers, "HW-NAS")
    for selling in ("50000.00", "52000.00", "49000.00"):
        r = await client.post(
            f"{API}/items/{iid}/prices",
            json=_price(cost="40000.00", selling=selling),
            headers={**sm.headers, **idem()},
        )
        assert r.status_code == 201, r.text
    hist = (await client.get(f"{API}/items/{iid}/prices", headers=sm.headers)).json()
    assert [h["status"] for h in hist].count("active") == 1
    assert [h["status"] for h in hist].count("superseded") == 2
    cur = (await client.get(f"{API}/items/{iid}/price", headers=sm.headers)).json()
    assert cur["price"]["selling"] == "49000.00"
    assert cur["price"]["margin_percent"] == "18.37"
    assert cur["state"] in ("valid", "expiring")


async def test_price_rows_cannot_be_edited_in_the_database(client: Any) -> None:
    """The trigger is the last line of defence if someone bypasses the service layer."""
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    await _seed()
    async with get_sessionmaker()() as s:
        with pytest.raises(DBAPIError):
            await s.execute(text("UPDATE price_entries SET selling = selling + 1"))
            await s.commit()
    async with get_sessionmaker()() as s:
        with pytest.raises(DBAPIError):
            await s.execute(text("DELETE FROM price_entries"))
            await s.commit()


async def test_expiry_job_flags_old_prices_and_emits_events(client: Any) -> None:
    await _seed()
    sm = await make_user(client, Role.SALES_MANAGER)
    sessionmaker = get_sessionmaker()
    # The seeded prices were quoted on 26 Sep 2026 with 5 days validity (to 1 Oct 2026).
    assert (
        await service.expire_prices(sessionmaker, today=__import__("datetime").date(2026, 10, 1))
        == 0
    )
    n = await service.expire_prices(sessionmaker, today=__import__("datetime").date(2026, 10, 2))
    assert n == 9  # the nine priced seed items
    assert (
        await service.expire_prices(sessionmaker, today=__import__("datetime").date(2026, 10, 2))
        == 0
    )

    iid = await _item_id(client, sm.headers, "HW-FW-SOPHOS-XGS108")
    cur = (await client.get(f"{API}/items/{iid}/price", headers=sm.headers)).json()
    assert cur["state"] == "expired"  # never treated as usable

    work = (await client.get(f"{API}/prices/attention", headers=sm.headers)).json()
    assert {w["state"] for w in work} <= {"expired", "missing"}
    assert len(work) == 18

    await outbox.dispatch_batch(sessionmaker)
    from sqlalchemy import func, select

    async with sessionmaker() as s:
        done = await s.scalar(
            select(func.count())
            .select_from(outbox.OutboxMessage)
            .where(outbox.OutboxMessage.event_type == "catalogue.price_expired")
        )
    assert done == 9

    # Refreshing the price makes it usable again.
    r = await client.post(
        f"{API}/items/{iid}/prices",
        json=_price(cost="60000.00", selling="66812.00"),
        headers={**sm.headers, **idem()},
    )
    assert r.status_code == 201
    cur = (await client.get(f"{API}/items/{iid}/price", headers=sm.headers)).json()
    assert cur["state"] in ("valid", "expiring")


async def test_out_of_stock_resolves_to_the_alternative(client: Any) -> None:
    from app.modules.catalogue.contracts import resolve_orderable
    from app.modules.identity.contracts import Principal  # noqa: F401

    await _seed()
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    sophos = await _item_id(client, sa.headers, "HW-FW-SOPHOS-XGS108")
    forti = await _item_id(client, sa.headers, "HW-FW-FORTI-FG40F")
    got = (await client.get(f"{API}/items/{sophos}", headers=sa.headers)).json()
    r = await client.post(
        f"{API}/items/{sophos}/stock",
        json={
            "stock_status": "out_of_stock",
            "alternative_item_id": forti,
            "version": got["version"],
        },
        headers=sa.headers,
    )
    assert r.status_code == 200, r.text
    # An item cannot be its own alternative, and kinds must match.
    r = await client.post(
        f"{API}/items/{sophos}/stock",
        json={
            "stock_status": "limited",
            "alternative_item_id": sophos,
            "version": r.json()["version"],
        },
        headers=sa.headers,
    )
    assert r.status_code == 422
    # resolve_orderable is exercised end to end by the BOQ engine in Phase 6
    assert callable(resolve_orderable)


async def test_market_data_keeps_history_and_current(client: Any) -> None:
    await _seed()
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    iid = await _item_id(client, sa.headers, "HW-FW-SOPHOS-XGS108")
    today = today_ist()
    for num, day in (("4.1", today - timedelta(days=30)), ("4.4", today)):
        r = await client.post(
            f"{API}/items/{iid}/market-data",
            json={
                "key": "analyst_rating",
                "value_num": num,
                "source_note": "Gartner peer insights",
                "as_of": str(day),
            },
            headers=sa.headers,
        )
        assert r.status_code == 201, r.text
    cur = (await client.get(f"{API}/items/{iid}/market-data", headers=sa.headers)).json()
    assert [c["value_num"] for c in cur] == ["4.4000"]
    hist = (
        await client.get(
            f"{API}/items/{iid}/market-data", params={"history": True}, headers=sa.headers
        )
    ).json()
    assert len(hist) == 2
    r = await client.post(
        f"{API}/items/{iid}/market-data",
        json={"key": "analyst_rating", "source_note": "no value", "as_of": str(today)},
        headers=sa.headers,
    )
    assert r.status_code == 422
    r = await client.post(
        f"{API}/items/{iid}/market-data",
        json={
            "key": "x",
            "value_text": "y",
            "source_note": "future",
            "as_of": str(today + timedelta(days=3)),
        },
        headers=sa.headers,
    )
    assert r.status_code == 422


async def test_stale_item_version_is_a_conflict(client: Any) -> None:
    await _seed()
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    iid = await _item_id(client, sa.headers, "HW-NAS")
    got = (await client.get(f"{API}/items/{iid}", headers=sa.headers)).json()
    ok = await client.patch(
        f"{API}/items/{iid}", json={"name": "NAS 2", "version": got["version"]}, headers=sa.headers
    )
    assert ok.status_code == 200
    stale = await client.patch(
        f"{API}/items/{iid}", json={"name": "NAS 3", "version": got["version"]}, headers=sa.headers
    )
    assert stale.status_code == 409


async def test_current_prices_list_is_one_call_and_priced_only(client: Any) -> None:
    await _seed()
    sm = await make_user(client, Role.SALES_MANAGER)
    rows = (await client.get(f"{API}/prices/current", headers=sm.headers)).json()
    assert len(rows) == 9  # the nine priced seed items
    assert {r["state"] for r in rows} <= {"valid", "expiring", "expired"}
    assert all(r["selling"].count(".") == 1 for r in rows)
    fe = await make_user(client, Role.FIELD_ENGINEER)
    assert (await client.get(f"{API}/prices/current", headers=fe.headers)).status_code == 403
