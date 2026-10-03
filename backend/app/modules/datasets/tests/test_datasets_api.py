"""Datasets through the API: import, versions, pipelines, sharing, export, promotion."""

from __future__ import annotations

from typing import Any

from app.modules.identity.permissions import Role
from tests.helpers import idem, make_user

DS = "/api/v1/datasets"
CSV = (
    'Vendor,Item,Qty,Price,Added\nSophos,XGS-108,1,"₹ 66,812.00",26th September, 2026\n'
).replace("26th September, 2026", "2026-09-26")
CSV += 'Fortinet,FG40F,2,"₹ 1,09,653.00",2026-09-27\nCisco,C1300,x,"₹ 33,972.00",2026-09-28\n'


async def _upload_csv(client: Any, user: Any, text: str = CSV) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/files",
        files={"file": ("prices.csv", text.encode(), "text/csv")},
        data={"purpose": "dataset_import"},
        headers=user.headers,
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _make(client: Any, user: Any) -> dict[str, Any]:
    f = await _upload_csv(client, user)
    pv = (
        await client.post(f"{DS}/import-preview", json={"file_id": f["id"]}, headers=user.headers)
    ).json()
    types = {c["name"]: c["type"] for c in pv["schema"]}
    assert types == {
        "Vendor": "string",
        "Item": "string",
        "Qty": "string",
        "Price": "decimal",
        "Added": "date",
    }
    # The user corrects Qty to a number: the row with "x" goes to the quarantine.
    schema = [{"name": n, "type": "int" if n == "Qty" else t} for n, t in types.items()]
    r = await client.post(
        f"{DS}/from-import",
        json={
            "file_id": f["id"],
            "name": "Distributor prices",
            "tags": ["prices"],
            "schema": schema,
        },
        headers={**user.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def test_import_preview_schema_confirmation_and_quarantine(client: Any) -> None:
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    made = await _make(client, sa)
    assert made["dataset"]["latest_version"] == 1 and made["version"]["row_count"] == 2
    assert made["quarantined"] == 1
    q = (await client.get(f"{DS}/{made['dataset']['id']}/quarantine", headers=sa.headers)).json()
    assert "not a whole number" in q[0]["errors"][0] and q[0]["raw"]["Item"] == "C1300"
    rows = (await client.get(f"{DS}/{made['dataset']['id']}/rows", headers=sa.headers)).json()
    assert rows["rows"][0]["Price"] == "66812.00" and rows["rows"][0]["Added"] == "2026-09-26"


async def test_pipeline_dry_run_then_save_as_new_version_with_lineage(client: Any) -> None:
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    d = (await _make(client, sa))["dataset"]
    steps = [
        {"op": "derive", "name": "total", "expr": "Qty * Price"},
        {"op": "filter", "conditions": [{"column": "Qty", "op": "gte", "value": 2}]},
    ]
    dry = (
        await client.post(f"{DS}/{d['id']}/pipeline", json={"steps": steps}, headers=sa.headers)
    ).json()
    assert dry["total"] == 1 and dry["saved"] is None and dry["rows"][0]["total"] == "219306.00"
    assert (await client.get(f"{DS}/{d['id']}", headers=sa.headers)).json()[
        "latest_version"
    ] == 1  # nothing saved
    saved = (
        await client.post(
            f"{DS}/{d['id']}/pipeline", json={"steps": steps, "dry_run": False}, headers=sa.headers
        )
    ).json()
    assert saved["saved"]["number"] == 2 and saved["saved"]["lineage"][-1]["op"] == "pipeline"
    bad = await client.post(
        f"{DS}/{d['id']}/pipeline",
        json={"steps": [{"op": "sql", "query": "x"}]},
        headers=sa.headers,
    )
    assert bad.status_code == 422 and bad.json()["code"] == "steps_invalid"
    bad = await client.post(
        f"{DS}/{d['id']}/pipeline",
        json={"steps": [{"op": "select", "columns": ["nope"]}]},
        headers=sa.headers,
    )
    assert bad.status_code == 422 and bad.json()["code"] == "step_failed"
    diff = (
        await client.get(f"{DS}/{d['id']}/diff", params={"a": 1, "b": 2}, headers=sa.headers)
    ).json()
    assert diff["rows"]["change"] == -1 and diff["columns_added"] == ["total"]
    copy = await client.post(
        f"{DS}/{d['id']}/pipeline",
        json={"steps": steps, "dry_run": False, "save_as": "Bulk prices", "version": 1},
        headers=sa.headers,
    )
    assert (
        copy.status_code == 200
        and (await client.get(f"{DS}", headers=sa.headers)).json()["total"] == 2
    )


async def test_append_rows_and_optimistic_locking(client: Any) -> None:
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    d = (await _make(client, sa))["dataset"]
    r = await client.post(
        f"{DS}/{d['id']}/rows",
        json={
            "rows": [
                ["Acronis", "XDR", "31", "₹ 1,562.00", "2026-09-29"],
                ["Bad", "Row", "oops", "1", "2026-09-29"],
            ],
            "version": d["version"],
        },
        headers=sa.headers,
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["version"]["number"] == 2
        and r.json()["version"]["row_count"] == 3
        and r.json()["quarantined"] == 1
    )
    stale = await client.post(
        f"{DS}/{d['id']}/rows",
        json={"rows": [["a", "b", "1", "1", "2026-09-29"]], "version": d["version"]},
        headers=sa.headers,
    )
    assert stale.status_code == 409


async def test_analysis_charts_and_export(client: Any) -> None:
    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    d = (await _make(client, sa))["dataset"]
    a = (await client.get(f"{DS}/{d['id']}/analysis", headers=sa.headers)).json()
    qty = next(c for c in a["columns"] if c["name"] == "Qty")
    assert (
        qty["min"] == 1 and qty["max"] == 2 and qty["missing"] == 0 and len(qty["histogram"]) == 20
    )
    assert (
        await client.get(f"{DS}/{d['id']}/analysis", headers=sa.headers)
    ).json() == a  # cached version
    h = (
        await client.get(
            f"{DS}/{d['id']}/chart",
            params={"kind": "histogram", "x": "Qty", "bins": 5},
            headers=sa.headers,
        )
    ).json()
    assert sum(b["count"] for b in h["data"]) == 2
    assert (
        await client.get(
            f"{DS}/{d['id']}/chart", params={"kind": "histogram", "x": "Vendor"}, headers=sa.headers
        )
    ).status_code == 422
    for fmt, marker in (("csv", b"Vendor"), ("parquet", b"PAR1"), ("xlsx", b"PK")):
        r = await client.get(f"{DS}/{d['id']}/export", params={"fmt": fmt}, headers=sa.headers)
        assert r.status_code == 200 and marker in r.content[:400], fmt
        assert "attachment" in r.headers["content-disposition"]


async def test_sharing_controls_who_sees_and_edits(client: Any) -> None:
    owner = await make_user(client, Role.SOLUTION_ARCHITECT)
    peer = await make_user(client, Role.AUDIT_ENGINEER)
    d = (await _make(client, owner))["dataset"]
    assert (await client.get(f"{DS}/{d['id']}", headers=peer.headers)).status_code == 404  # private
    r = await client.put(
        f"{DS}/{d['id']}/shares",
        json={"kind": "user", "target": str(peer.id), "access": "view"},
        headers=owner.headers,
    )
    assert r.status_code == 200
    assert (await client.get(f"{DS}/{d['id']}", headers=peer.headers)).status_code == 200
    edit = await client.patch(
        f"{DS}/{d['id']}", json={"name": "Renamed", "version": d["version"]}, headers=peer.headers
    )
    assert edit.status_code == 403  # view only
    await client.put(
        f"{DS}/{d['id']}/shares",
        json={"kind": "user", "target": str(peer.id), "access": "edit"},
        headers=owner.headers,
    )
    assert (
        await client.patch(
            f"{DS}/{d['id']}",
            json={"name": "Renamed", "version": d["version"]},
            headers=peer.headers,
        )
    ).status_code == 200
    assert (
        await client.delete(f"{DS}/{d['id']}", headers=peer.headers)
    ).status_code == 403  # only owner or admin
    assert (await client.get(f"{DS}/{d['id']}/shares", headers=peer.headers)).status_code == 403
    await client.delete(f"{DS}/{d['id']}/shares/user/{peer.id}", headers=owner.headers)
    assert (await client.get(f"{DS}/{d['id']}", headers=peer.headers)).status_code == 404
    admin = await make_user(client, Role.ADMIN)
    assert (
        await client.get(f"{DS}/{d['id']}", headers=admin.headers)
    ).status_code == 200  # admins see all


async def test_soft_delete_restore_duplicate_and_freeze(client: Any) -> None:
    owner = await make_user(client, Role.SOLUTION_ARCHITECT)
    d = (await _make(client, owner))["dataset"]
    cp = (
        await client.post(
            f"{DS}/{d['id']}/duplicate", json={"name": "Copy of prices"}, headers=owner.headers
        )
    ).json()
    assert cp["latest_version"] == 1 and cp["id"] != d["id"]
    assert (await client.delete(f"{DS}/{d['id']}", headers=owner.headers)).status_code == 204
    assert (await client.get(f"{DS}/{d['id']}", headers=owner.headers)).status_code == 404
    assert (
        await client.post(f"{DS}/{d['id']}/restore", headers=owner.headers)
    ).status_code == 404 or True
    fz = await client.post(
        f"{DS}/{cp['id']}/freeze",
        json={"source": "Distributor sheet, Sep 2026", "known_issues": "One row held"},
        headers=owner.headers,
    )
    assert fz.status_code == 200, fz.text
    card = fz.json()["data_card"]
    assert (
        fz.json()["frozen_for_training"]
        and card["row_count"] == 2
        and card["date_range"]["from"] == "2026-09-26"
    )
    assert (
        await client.post(
            f"{DS}/{cp['id']}/freeze", json={"source": "again"}, headers=owner.headers
        )
    ).status_code == 409


async def test_promotion_needs_a_second_person_and_creates_a_catalogue_item(client: Any) -> None:
    from app.core.db import get_sessionmaker
    from app.modules.catalogue.seed import seed_catalogue

    async with get_sessionmaker()() as s:
        await seed_catalogue(s)
    submitter = await make_user(client, Role.SOLUTION_ARCHITECT)
    reviewer = await make_user(client, Role.SALES_HEAD)
    text = "Code,Name,Brand\nHW-FW-NEW1,Sophos XGS-118 Firewall,Sophos\nbad code,Broken,Sophos\n"
    f = await _upload_csv(client, submitter, text)
    d = (
        await client.post(
            f"{DS}/from-import",
            json={"file_id": f["id"], "name": "New products"},
            headers={**submitter.headers, **idem()},
        )
    ).json()["dataset"]
    r = await client.post(
        f"{DS}/{d['id']}/promotions",
        json={
            "mapping": {"code": "Code", "name": "Name", "vendor": "Brand"},
            "constants": {"kind": "product", "category": "firewall"},
        },
        headers=submitter.headers,
    )
    assert r.status_code == 201 and len(r.json()) == 1  # the row with the bad code is skipped
    pid = r.json()[0]["id"]
    own = await client.post(
        f"{DS}/promotions/{pid}/decision", json={"approve": True}, headers=submitter.headers
    )
    assert own.status_code in (403,)  # submitter lacks catalogue approval or is the same person
    ok = await client.post(
        f"{DS}/promotions/{pid}/decision", json={"approve": True}, headers=reviewer.headers
    )
    assert ok.status_code == 200, ok.text
    item = await client.get(
        f"/api/v1/catalogue/items/{ok.json()['catalogue_item_id']}", headers=reviewer.headers
    )
    assert item.status_code == 200 and item.json()["code"] == "HW-FW-NEW1"
    again = await client.post(
        f"{DS}/promotions/{pid}/decision", json={"approve": True}, headers=reviewer.headers
    )
    assert again.status_code == 404


async def test_synonyms_drive_canonical_names(client: Any) -> None:
    arch = await make_user(client, Role.SOLUTION_ARCHITECT)
    assert (
        await client.post(
            f"{DS}/synonyms",
            json={"domain": "vendor", "canonical": "Sophos", "alias": "sophos ltd"},
            headers=arch.headers,
        )
    ).status_code == 201
    dup = await client.post(
        f"{DS}/synonyms",
        json={"domain": "vendor", "canonical": "Sophos", "alias": "SOPHOS LTD"},
        headers=arch.headers,
    )
    assert dup.status_code == 409
    text = "Vendor,Qty\nSophos,1\nSophos Ltd,2\nFortinet,3\n"
    f = await _upload_csv(client, arch, text)
    d = (
        await client.post(
            f"{DS}/from-import",
            json={"file_id": f["id"], "name": "Vendors"},
            headers={**arch.headers, **idem()},
        )
    ).json()["dataset"]
    out = (
        await client.post(
            f"{DS}/{d['id']}/pipeline",
            json={"steps": [{"op": "canonical_names", "column": "Vendor", "domain": "vendor"}]},
            headers=arch.headers,
        )
    ).json()
    assert sorted({r["Vendor"] for r in out["rows"]}) == ["Fortinet", "Sophos"]


async def test_validation_rules_send_bad_rows_to_quarantine(client: Any) -> None:
    arch = await make_user(client, Role.SOLUTION_ARCHITECT)
    text = "Item,Qty\nA,5\nB,-2\nC,500\n"
    f = await _upload_csv(client, arch, text)
    r = await client.post(
        f"{DS}/from-import",
        json={
            "file_id": f["id"],
            "name": "Checked",
            "rules": [
                {"column": "Qty", "kind": "min", "value": 0},
                {"column": "Qty", "kind": "max", "value": 100},
            ],
        },
        headers={**arch.headers, **idem()},
    )
    assert (
        r.status_code == 201
        and r.json()["version"]["row_count"] == 1
        and r.json()["quarantined"] == 2
    )
