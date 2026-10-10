"""The library: drop in old BOQs and reports, the engine reads them into datasets."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.core.db import get_sessionmaker
from app.modules.datasets import cleaning, library
from app.modules.identity.permissions import Role
from tests.helpers import drain_outbox, make_user

LIB = "/api/v1/library"
DS = "/api/v1/datasets"
SAMPLES = Path(__file__).parents[5] / "samples"


def _sample(pattern: str) -> Path:
    return next(SAMPLES.glob(pattern))


async def _drop(client: Any, user: Any, path: Path, mime: str) -> dict[str, Any]:
    r = await client.post(
        f"{LIB}/files", files={"file": (path.name, path.read_bytes(), mime)}, headers=user.headers
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _process() -> None:
    await drain_outbox()


async def _collections(client: Any, user: Any) -> dict[str, Any]:
    return dict((await client.get(f"{LIB}/collections", headers=user.headers)).json())


async def test_summary_and_priced_boq_become_one_dataset(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    a = await _drop(client, sm, _sample("*- BOQ.pdf"), "application/pdf")
    b = await _drop(client, sm, _sample("*Sanitization*.pdf"), "application/pdf")
    assert a["duplicate"] is False and b["file"]["status"] == "queued"
    await _process()

    files = {
        f["original_name"]: f for f in (await client.get(f"{LIB}/files", headers=sm.headers)).json()
    }
    summary = next(f for n, f in files.items() if n.endswith("- BOQ.pdf"))
    priced = next(f for n, f in files.items() if "Sanitization" in n)
    assert (
        summary["status"] == "processed" and summary["rows_added"] == 9 and summary["kind"] == "boq"
    )
    # One line of the priced quotation is garbled in the PDF, so it is held for a person.
    assert (
        priced["status"] == "needs_review"
        and priced["rows_added"] == 8
        and priced["rows_held"] == 1
    )
    assert priced["facts"]["quote_ref"] == "ITCraft/NN/2627/030"

    coll = (await _collections(client, sm))["historical_boq_lines"]
    assert coll["latest_version"] == 3  # empty, then one version per file
    rows = (
        await client.get(f"{DS}/{coll['id']}/rows", params={"limit": 50}, headers=sm.headers)
    ).json()
    assert rows["total"] == 17
    sophos = next(r for r in rows["rows"] if r["component"].startswith("Sophos XGS-108"))
    assert (sophos["line_ref"], sophos["option"], sophos["section"]) == (
        "6A",
        "A",
        "Firewall Options",
    )
    assert (
        sophos["unit_price"] == "66812.00"
        and sophos["customer"] == "Shobhaglobs Engineers Hub Private Limited"
    )
    assert sophos["quote_date"] == "2026-09-26" and sophos["gst_rate"] == "18.00"


async def test_the_same_file_is_never_added_twice(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    await _drop(client, sm, _sample("*- BOQ.pdf"), "application/pdf")
    again = await _drop(client, sm, _sample("*- BOQ.pdf"), "application/pdf")
    assert again["duplicate"] is True
    await _process()
    coll = (await _collections(client, sm))["historical_boq_lines"]
    assert (await client.get(f"{DS}/{coll['id']}/rows", headers=sm.headers)).json()["total"] == 9


async def test_held_rows_are_fixed_by_a_person_and_join_the_dataset(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    await _drop(client, sm, _sample("*Sanitization*.pdf"), "application/pdf")
    await _process()
    coll = (await _collections(client, sm))["historical_boq_lines"]
    held = (await client.get(f"{DS}/{coll['id']}/quarantine", headers=sm.headers)).json()
    # The cleaner repaired the overprinted heading, but a repair is a suggestion: the row is
    # still held (below the 0.8 floor) for a person to confirm.
    assert len(held) == 1 and held[0]["confidence"] == 0.75
    assert "printed over this line" in held[0]["errors"][0]
    assert held[0]["raw"]["component"].startswith("Fortinet / Sophos One Time Setup")
    r = await client.post(
        f"{DS}/{coll['id']}/quarantine/{held[0]['id']}",
        json={
            "action": "fix",
            "values": {
                "component": "Fortinet / Sophos One Time Setup Installation Configuration Charges"
            },
        },
        headers=sm.headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "fixed"
    rows = (
        await client.get(f"{DS}/{coll['id']}/rows", params={"limit": 50}, headers=sm.headers)
    ).json()
    fixed = next(x for x in rows["rows"] if x["line_ref"] == "7")
    assert (
        fixed["component"].startswith("Fortinet / Sophos One Time") and fixed["confidence"] == 1.0
    )
    assert rows["total"] == 9
    assert (await client.get(f"{DS}/{coll['id']}/quarantine", headers=sm.headers)).json() == []
    # with its last held line settled, the file no longer waits for a person
    lf = (await client.get(f"{LIB}/files", headers=sm.headers)).json()[0]
    assert lf["status"] == "processed" and "settled" in lf["message"]


async def test_prismsuite_report_becomes_audit_findings(client: Any) -> None:
    from tests.helpers import sample_report_path

    sa = await make_user(client, Role.SOLUTION_ARCHITECT)
    p = sample_report_path()
    up = await _drop(
        client, sa, p, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert up["file"]["status"] == "queued"
    await _process()
    lf = (await client.get(f"{LIB}/files", headers=sa.headers)).json()[0]
    assert lf["kind"] == "audit" and lf["parser"] == "prismsuite.docx.v1"
    assert (
        lf["status"] == "needs_review" and lf["facts"]["conflicts"] == 1
    )  # the firewall HA conflict
    coll = (await _collections(client, sa))["audit_findings"]
    chart = (
        await client.get(
            f"{DS}/{coll['id']}/chart",
            params={"kind": "bar", "x": "category", "agg": "count"},
            headers=sa.headers,
        )
    ).json()
    cats = {d["label"]: d["value"] for d in chart["data"]}
    assert cats["score"] == 6 and cats["component_score"] >= 10 and cats["vulnerability"] == 10
    rows = (
        await client.post(
            f"{DS}/{coll['id']}/pipeline",
            json={
                "steps": [
                    {
                        "op": "filter",
                        "conditions": [
                            {"column": "key", "op": "eq", "value": "security"},
                            {"column": "category", "op": "eq", "value": "score"},
                        ],
                    }
                ]
            },
            headers=sa.headers,
        )
    ).json()
    assert rows["total"] == 1 and rows["rows"][0]["value_num"] == "58.70"


async def test_unknown_files_are_skipped_not_guessed(client: Any) -> None:
    sm = await make_user(client, Role.SALES_MANAGER)
    r = await client.post(
        f"{LIB}/files",
        files={"file": ("prices.csv", b"a,b\n1,2\n", "text/csv")},
        headers=sm.headers,
    )
    assert r.status_code == 201, r.text
    await _process()
    lf = (await client.get(f"{LIB}/files", headers=sm.headers)).json()[0]
    assert lf["status"] == "skipped" and "BOQ" in lf["message"]
    assert (
        await client.post(f"{LIB}/files/{lf['id']}/retry", headers=sm.headers)
    ).status_code == 200


async def test_who_can_use_the_library(client: Any) -> None:
    fe = await make_user(client, Role.FIELD_ENGINEER)
    sm = await make_user(client, Role.SALES_MANAGER)
    tl = await make_user(client, Role.TECHNICAL_LEAD)
    assert (await client.get(f"{LIB}/files", headers=fe.headers)).status_code == 403
    r = await client.post(
        f"{LIB}/files",
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        headers=tl.headers,
    )
    assert r.status_code == 403  # read only
    assert (await client.get(f"{LIB}/files", headers=tl.headers)).status_code == 200
    await _drop(client, sm, _sample("*- BOQ.pdf"), "application/pdf")
    await _process()
    coll = (await _collections(client, tl))["historical_boq_lines"]
    assert (
        await client.get(f"{DS}/{coll['id']}/rows", headers=tl.headers)
    ).status_code == 200  # shared by role
    assert (await client.delete(f"{DS}/{coll['id']}", headers=sm.headers)).status_code in (
        403,
        409,
    )  # built-in


async def test_watched_folder_picks_files_up_and_skips_duplicates(
    client: Any, tmp_path: Path
) -> None:
    await make_user(client, Role.ADMIN)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copy(_sample("*- BOQ.pdf"), inbox / "a.pdf")
    shutil.copy(_sample("*- BOQ.pdf"), inbox / "same-content.pdf")
    (inbox / "notes.txt").write_text("ignored")
    counts = await library.scan_folder(get_sessionmaker(), inbox)
    assert counts == {"added": 1, "duplicates": 1, "failed": 0}
    assert sorted(p.name for p in (inbox / "processed").iterdir())[0].endswith("a.pdf")
    assert (inbox / "duplicates").is_dir() and (inbox / "notes.txt").exists()
    await _process()
    admin = await make_user(client, Role.ADMIN)
    coll = (await _collections(client, admin))["historical_boq_lines"]
    assert (await client.get(f"{DS}/{coll['id']}/rows", headers=admin.headers)).json()["total"] == 9
    files = (await client.get(f"{LIB}/files", headers=admin.headers)).json()
    assert files[0]["source"] == "folder"


async def test_every_file_becomes_a_canonical_corpus_record(client: Any) -> None:
    """ADR 0014: a file is converted once; the collections, the analysis and a rebuild all work
    from the compact record, and originals are only purged under the retention rule."""
    from datetime import timedelta

    from sqlalchemy import update

    from app.core.timeutil import utcnow
    from app.modules.datasets import corpus_service
    from app.modules.datasets.models import CorpusDocument

    admin = await make_user(client, Role.ADMIN)
    sm = await make_user(client, Role.SALES_MANAGER)
    await _drop(client, sm, _sample("*- BOQ.pdf"), "application/pdf")
    await _drop(client, sm, _sample("*Sanitization*.pdf"), "application/pdf")
    await _process()

    docs = (await client.get(f"{LIB}/corpus", headers=sm.headers)).json()
    assert len(docs) == 2 and {d["kind"] for d in docs} == {"boq"}
    priced = next(d for d in docs if "Sanitization" in d["name"])
    assert priced["gzip_bytes"] * 20 < priced["original_bytes"]
    assert priced["labels"]["firewall_underconfigured"] == 4 and priced["quality_score"] >= 90

    full = (await client.get(f"{LIB}/corpus/{priced['id']}", headers=sm.headers)).json()
    rec = full["record"]
    assert rec["schema"] == "p1.corpus.v1" and len(rec["text"]["pages"]) >= 1
    repaired = next(ln for ln in rec["lines"] if ln["line_ref"] == "7")
    assert repaired["component"].startswith("Fortinet / Sophos")

    # the held row carries the repaired text, so a person only confirms it
    coll = (await _collections(client, sm))["historical_boq_lines"]
    held = (await client.get(f"{DS}/{coll['id']}/quarantine", headers=sm.headers)).json()
    assert held[0]["raw"]["component"].startswith("Fortinet / Sophos")

    rows = (
        await client.get(f"{DS}/{coll['id']}/rows", params={"limit": 50}, headers=sm.headers)
    ).json()["rows"]
    assert all(r["gap_type"] for r in rows) and {r["cleaning_version"] for r in rows} == {
        cleaning.CLEANING_VERSION
    }

    an = (await client.get(f"{LIB}/analysis", headers=sm.headers)).json()
    assert an["corpus"]["documents"] == 2 and an["corpus"]["saved_share"] > 0.9
    fw = next(
        b
        for b in an["boq"]["bands"]
        if (b["gap_type"], b["line_role"]) == ("firewall_underconfigured", "product")
    )
    assert fw["lines"] == 2 and fw["price_median"] == "88232.50"  # Sophos and FortiGate

    # rebuild: only the admin, and it writes one new version per collection
    assert (await client.post(f"{LIB}/rebuild", headers=sm.headers)).status_code == 403
    before = coll["latest_version"]
    r = await client.post(f"{LIB}/rebuild", headers=admin.headers)
    assert r.json() == {"rebuilt": 2, "reused": 0, "failed": 0}
    coll = (await _collections(client, sm))["historical_boq_lines"]
    assert coll["latest_version"] == before + 1

    # retention: nothing happens at 0 days; old originals go once the record checks out
    async with get_sessionmaker()() as s:
        assert await corpus_service.purge_originals(s) == 0
        await s.execute(update(CorpusDocument).values(created_at=utcnow() - timedelta(days=40)))
        await s.commit()
        assert await corpus_service.purge_originals(s, days=30) == 2
    docs = (await client.get(f"{LIB}/corpus", headers=sm.headers)).json()
    assert {d["original_state"] for d in docs} == {"purged"}
    # the record survives the original, and a rebuild reuses it
    assert (await client.get(f"{LIB}/corpus/{priced['id']}", headers=sm.headers)).status_code == 200
    r = await client.post(f"{LIB}/rebuild", headers=admin.headers)
    assert r.json() == {"rebuilt": 0, "reused": 2, "failed": 0}
