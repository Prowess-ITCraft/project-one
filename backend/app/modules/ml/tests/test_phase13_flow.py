"""Phase 13 end to end: drafted and accepted BOQs become line examples, prices become price
points with the rule's verdict and an alert, models train from frozen sets with a model card,
run in shadow mode, and only the Director approves one after its shadow run. One flag switches
all of it off without touching anything else."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update

from app.core import flags, outbox
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.timeutil import today_ist, utcnow
from app.modules.boq.tests.test_boq_flow import _approved, generate, ready
from app.modules.ml import service, tracking
from app.modules.ml.models import MlLineExample, MlModel, MlPricePoint
from app.modules.ml.tests.test_lines_and_drift import _examples
from app.modules.notifications.models import Notification
from tests.helpers import idem

API = "/api/v1"
ML = f"{API}/ml"


async def _settle() -> None:
    for _ in range(10):
        if not await outbox.dispatch_batch(get_sessionmaker()):
            break


async def test_drafted_and_accepted_boqs_become_line_examples(client: Any) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    await _settle()
    async with get_sessionmaker()() as s:
        ex = await s.scalar(select(MlLineExample).where(MlLineExample.boq_id == uuid.UUID(b["id"])))
    assert ex is not None and ex.labels is None
    assert (
        ex.features and ex.rule_labels and all(isinstance(v, float) for v in ex.features.values())
    )
    assert "price" not in str(ex.features).lower()

    await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    v = (await client.get(f"{API}/boq/{b['id']}/versions", headers=c.sm.headers)).json()[0]
    r = await client.post(
        f"{API}/boq/{b['id']}/versions/1/accept",
        json={
            "po_number": "PO-77",
            "po_date": str(today_ist()),
            "selected_options": {
                g: next(iter(o)) for g, o in v["totals"].get("options", {}).items()
            },
        },
        headers={**c.sm.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    await _settle()
    async with get_sessionmaker()() as s:
        ex = await s.scalar(select(MlLineExample).where(MlLineExample.boq_id == uuid.UUID(b["id"])))
    assert ex is not None and ex.labels and ex.labelled_at is not None
    assert set(ex.labels) <= set(ex.rule_labels) | {x for x in ex.labels if x.startswith("title:")}

    report = (await client.get(f"{ML}/report", headers=c.director.headers)).json()
    assert report["lines"]["accepted"] == 1 and report["lines"]["needed"] == 20
    assert report["enabled"] is True


async def test_prices_are_checked_against_their_history(client: Any) -> None:
    c = await ready(client)  # enters one price per item
    await _settle()
    item = (
        await client.get(
            f"{API}/catalogue/items", params={"q": "SVC-FW-SETUP"}, headers=c.sm.headers
        )
    ).json()["items"][0]
    today = today_ist()
    for selling in ("12500.00", "21000.00"):
        r = await client.post(
            f"{API}/catalogue/items/{item['id']}/prices",
            json={
                "supplier": "Distributor",
                "cost": str(float(selling) * 0.8),
                "selling": selling,
                "quoted_on": str(today),
                "valid_until": str(today + timedelta(days=10)),
                "source_note": "Test",
            },
            headers={**c.sm.headers, **idem()},
        )
        assert r.status_code == 201, r.text
        await _settle()
    async with get_sessionmaker()() as s:
        points = list(
            await s.scalars(
                select(MlPricePoint)
                .where(MlPricePoint.item_id == uuid.UUID(item["id"]))
                .order_by(MlPricePoint.created_at)
            )
        )
        alerts = list(
            await s.scalars(
                select(Notification).where(
                    Notification.template == "price_drift", Notification.channel == "email"
                )
            )
        )
    assert [p.rule_flag for p in points] == [False, False, True]
    assert points[-1].alerted and points[-1].change_pct == 68.0
    # every sales head hears, nobody else
    assert {a.to_user_id for a in alerts} == {c.head.id, c.ws.head.id}
    assert "68 percent above" in alerts[0].body


async def test_one_flag_switches_learning_off(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(flags.DEFAULTS, "ml_enabled", False)
    flags.clear_cache()
    try:
        c = await ready(client)
        b = await generate(client, c)
        await _settle()
        async with get_sessionmaker()() as s:
            assert (await s.scalar(select(MlLineExample))) is None
            assert (await s.scalar(select(MlPricePoint))) is None
        r = await client.post(
            f"{ML}/training-sets", json={"kind": "boq_lines"}, headers=c.director.headers
        )
        assert r.status_code == 409 and r.json()["code"] == "ml_off"
        s2 = await client.get(f"{ML}/projects/{c.pid}/suggested-lines", headers=c.sm.headers)
        assert s2.json()["available"] is False
        # the BOQ itself is untouched
        assert (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).status_code == 200
    finally:
        flags.clear_cache()


async def _line_history(n: int) -> None:
    async with get_sessionmaker()() as s:
        for e in _examples(n):
            s.add(
                MlLineExample(
                    boq_id=uuid.uuid4(),
                    project_id=uuid.uuid4(),
                    features=e.features,
                    rule_labels=sorted(e.rule_labels),
                    titles={lab: lab.replace(".", " ").title() for lab in e.labels},
                    labels=sorted(e.labels),
                    labelled_at=utcnow(),
                )
            )
        await s.commit()


async def test_line_model_from_frozen_set_to_shadow_to_approval(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = await ready(client)
    await _line_history(40)
    d = c.director.headers
    ts = (await client.post(f"{ML}/training-sets", json={"kind": "boq_lines"}, headers=d)).json()
    assert ts["kind"] == "boq_lines" and ts["data_card"]["rows"] == 40

    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("get-by-name"):
            return httpx.Response(404, json={})
        if req.url.path.endswith("experiments/create"):
            return httpx.Response(200, json={"experiment_id": "1"})
        if req.url.path.endswith("runs/create"):
            return httpx.Response(200, json={"run": {"info": {"run_id": "run-9"}}})
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        tracking, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(get_settings(), "mlflow_tracking_uri", "http://mlflow:5000")
    r = await client.post(f"{ML}/models", json={"training_set_id": ts["id"]}, headers=d)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["kind"] == "boq_lines" and m["metrics"]["model"]["f1"] > 0.8
    assert m["metrics"]["mlflow_run"] == "run-9" and any("log-batch" in p for p in calls)

    card = (await client.get(f"{ML}/models/{m['id']}/card", headers=d)).json()
    assert card["card"]["kind"] == "boq_lines" and "Never used for" in card["markdown"]

    # approval only after a shadow run, and only by the Director
    r = await client.post(
        f"{ML}/models/{m['id']}/approve", json={"note": "Looks right to me"}, headers=d
    )
    assert r.json()["code"] == "not_in_shadow"
    r = await client.post(f"{ML}/models/{m['id']}/status", json={"status": "shadow"}, headers=d)
    assert r.json()["status"] == "shadow" and r.json()["shadow_started_at"]
    r = await client.post(
        f"{ML}/models/{m['id']}/approve", json={"note": "Looks right to me"}, headers=d
    )
    assert r.status_code == 409 and r.json()["code"] == "shadow_too_short"

    # a BOQ drafted now is predicted by the shadow model, next to the rules
    b = await generate(client, c)
    await _settle()
    async with get_sessionmaker()() as s:
        ex = await s.scalar(select(MlLineExample).where(MlLineExample.boq_id == uuid.UUID(b["id"])))
        assert ex is not None and ex.model_id == uuid.UUID(m["id"]) and ex.model_labels is not None
        # thirty days and twenty decisions later
        await s.execute(
            update(MlModel)
            .where(MlModel.id == uuid.UUID(m["id"]))
            .values(shadow_started_at=utcnow() - timedelta(days=31))
        )
        await s.execute(
            update(MlLineExample)
            .where(MlLineExample.labels.is_not(None))
            .values(model_id=uuid.UUID(m["id"]), model_labels=["eps.xdr"])
        )
        await s.commit()
    report = (await client.get(f"{ML}/report", headers=d)).json()
    assert report["lines"]["shadow"]["compared"] >= 20

    # the sales head manages nothing here, and even an admin is not the Director
    r = await client.post(
        f"{ML}/models/{m['id']}/approve", json={"note": "Looks right to me"}, headers=c.head.headers
    )
    assert r.status_code == 403
    r = await client.post(
        f"{ML}/models/{m['id']}/approve",
        json={"note": "Forty BOQs, better recall than the drafts"},
        headers=d,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["approval_note"]

    # an approved line model suggests lines; nothing is added to the BOQ by itself
    sug = (await client.get(f"{ML}/projects/{c.pid}/suggested-lines", headers=c.sm.headers)).json()
    assert sug["available"] is True and sug["lines"]
    assert all(0.5 <= x["probability"] <= 1 for x in sug["lines"])
    after = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    assert len(after["lines"]) == len(b["lines"])


async def test_model_status_rules(client: Any) -> None:
    c = await ready(client)
    await _line_history(25)
    d = c.director.headers
    ts = (await client.post(f"{ML}/training-sets", json={"kind": "boq_lines"}, headers=d)).json()
    m = (await client.post(f"{ML}/models", json={"training_set_id": ts["id"]}, headers=d)).json()
    m2 = (await client.post(f"{ML}/models", json={"training_set_id": ts["id"]}, headers=d)).json()
    await client.post(f"{ML}/models/{m['id']}/status", json={"status": "shadow"}, headers=d)
    await client.post(f"{ML}/models/{m2['id']}/status", json={"status": "shadow"}, headers=d)
    models = {x["id"]: x for x in (await client.get(f"{ML}/models", headers=d)).json()}
    assert models[m["id"]]["status"] == "trained" and models[m2["id"]]["status"] == "shadow"
    await client.post(f"{ML}/models/{m['id']}/status", json={"status": "retired"}, headers=d)
    r = await client.post(f"{ML}/models/{m['id']}/status", json={"status": "shadow"}, headers=d)
    assert r.json()["code"] == "retired"
    # a ranker in shadow mode does not displace a line model in shadow mode
    async with get_sessionmaker()() as s:
        assert await service.active_shadow(s, "boq_lines") is not None
        assert await service.active_shadow(s, "ranker") is None
