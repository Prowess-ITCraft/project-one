"""Learning end to end: a BOQ drafted by the recommender and accepted by the customer becomes
labelled examples; examples are frozen into a training set; a model trains only on frozen data,
runs in shadow mode next to the rules and never touches a BOQ."""

from __future__ import annotations

import random
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text

from app.core import outbox
from app.core.db import get_sessionmaker
from app.core.events import DomainEvent
from app.core.timeutil import today_ist
from app.modules.boq.tests.test_boq_flow import _approved, line, ready
from app.modules.identity.permissions import Role
from app.modules.ml import service
from app.modules.ml import train as t
from app.modules.ml.models import MlExample
from tests.helpers import idem, make_user

API = "/api/v1"
ML = f"{API}/ml"


async def _settle() -> None:
    for _ in range(5):
        if not await outbox.dispatch_batch(get_sessionmaker()):
            break


async def _synthetic_history(groups: int) -> None:
    """Accepted recommendations from earlier projects: the kept product was always the one
    from the customer's preferred vendor."""
    rng = random.Random(3)
    async with get_sessionmaker()() as s:
        for g in range(groups):
            boq, pid = uuid.uuid4(), uuid.uuid4()
            for rank, (vendor, kept) in enumerate(((0.5, False), (1.0, True)), start=1):
                crit = {k: round(rng.uniform(0.3, 0.9), 2) for k in t.FEATURES}
                crit["vendor"] = vendor
                s.add(
                    MlExample(
                        boq_id=boq,
                        project_id=pid,
                        rec_key=f"G{g}:firewall",
                        category="firewall",
                        item_id=uuid.uuid4(),
                        item_name=f"Firewall {g}{'B' if kept else 'A'}",
                        rule_rank=rank,
                        rule_score=0.7 if rank == 1 else 0.6,
                        criteria=crit,
                        kept=kept,
                        labelled_at=today_ist(),
                    )
                )
        await s.commit()


async def test_accepted_boq_teaches_and_the_model_stays_in_shadow(client: Any) -> None:
    c = await ready(client)
    b = await _approved(client, c)
    await _settle()
    async with get_sessionmaker()() as s:
        examples = list(await s.scalars(select(MlExample).where(MlExample.boq_id == b["id"])))
    assert examples and all(x.kept is None for x in examples)
    assert all(set(x.criteria) >= {"need_fit", "vendor"} for x in examples)

    # The customer takes the second firewall (option B): that candidate is kept, the other not.
    await client.post(f"{API}/boq/{b['id']}/issue", headers={**c.sm.headers, **idem()})
    cur = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    grp = line(cur, "Sophos XGS-108")["option_group"]
    ok = await client.post(
        f"{API}/boq/{b['id']}/versions/1/accept",
        json={"po_number": "PO-1", "po_date": str(today_ist()), "selected_options": {grp: "B"}},
        headers={**c.sm.headers, **idem()},
    )
    assert ok.status_code == 200, ok.text
    await _settle()
    async with get_sessionmaker()() as s:
        fw = {
            x.item_name: x.kept
            for x in await s.scalars(
                select(MlExample).where(
                    MlExample.boq_id == b["id"], MlExample.category == "firewall"
                )
            )
        }
    assert fw and any(fw.values()) and not all(fw.values())
    letters = {
        x["title"]: x["letter"]
        for x in cur["lines"]
        if x["option_group"] == grp and x["title"] in fw
    }
    assert {fw[title] for title, ltr in letters.items() if ltr == "B"} == {True}
    assert {fw[title] for title, ltr in letters.items() if ltr != "B"} == {False}

    # Reading is wider than managing.
    head = c.head
    rep = (await client.get(f"{ML}/report", headers=head.headers)).json()
    assert rep["labelled"] >= 2 and rep["usable_groups"] >= 1 and rep["shadow"] is None
    denied = await client.post(f"{ML}/training-sets", headers=head.headers)
    assert denied.status_code == 403
    engineer = await make_user(client, Role.FIELD_ENGINEER)
    assert (await client.get(f"{ML}/report", headers=engineer.headers)).status_code == 403

    # One accepted BOQ is far too little: training says so instead of fitting noise.
    d = c.director
    first = (await client.post(f"{ML}/training-sets", headers=d.headers)).json()
    assert first["number"] == 1 and first["data_card"]["usable_groups"] >= 1
    thin = await client.post(
        f"{ML}/models", json={"training_set_id": first["id"]}, headers=d.headers
    )
    assert thin.status_code == 422 and thin.json()["code"] == "not_enough_data"

    # With enough history the model learns what customers chose.
    await _synthetic_history(t.MIN_GROUPS + 5)
    second = (await client.post(f"{ML}/training-sets", headers=d.headers)).json()
    assert second["number"] == 2 and second["data_card"]["usable_groups"] >= t.MIN_GROUPS
    m = await client.post(f"{ML}/models", json={"training_set_id": second["id"]}, headers=d.headers)
    assert m.status_code == 201, m.text
    model = m.json()
    w = model["weights"]
    assert max(w, key=lambda k: w[k]) == "vendor" and model["metrics"]["training_set"] == 2

    # Training sets are frozen in the database too.
    async with get_sessionmaker()() as s:
        with pytest.raises(Exception, match="frozen"):
            await s.execute(text("UPDATE ml_training_sets SET data_card = '{}'::jsonb"))
            await s.commit()

    # Shadow mode: the model ranks next to the rules and only the report hears about it.
    sh = await client.post(
        f"{ML}/models/{model['id']}/status", json={"status": "shadow"}, headers=d.headers
    )
    assert sh.status_code == 200 and sh.json()["status"] == "shadow"
    crit_a = dict.fromkeys(t.FEATURES, 0.9) | {"vendor": 0.5}
    crit_b = dict.fromkeys(t.FEATURES, 0.6) | {"vendor": 1.0}
    async with get_sessionmaker()() as s:
        await service.record_recommendations(
            s,
            DomainEvent(
                event_type="boq.recommended",
                aggregate_type="boq",
                aggregate_id=str(uuid.uuid4()),
                payload={
                    "project_id": str(uuid.uuid4()),
                    "groups": [
                        {
                            "key": "G9:firewall",
                            "category": "firewall",
                            "candidates": [
                                {
                                    "item_id": str(uuid.uuid4()),
                                    "name": "Rules pick",
                                    "score": 0.8,
                                    "criteria": crit_a,
                                },
                                {
                                    "item_id": str(uuid.uuid4()),
                                    "name": "Model pick",
                                    "score": 0.7,
                                    "criteria": crit_b,
                                },
                            ],
                        }
                    ],
                },
            ),
        )
    rep = (await client.get(f"{ML}/report", headers=d.headers)).json()
    shadow = rep["shadow"]
    assert shadow["number"] == model["number"] and shadow["runs"] == 1
    assert shadow["agreement"] == 0.0
    assert shadow["disagreements"][0] == {
        "category": "firewall",
        "rules": "Rules pick",
        "model": "Model pick",
        "at": shadow["disagreements"][0]["at"],
    }

    # The BOQ itself never changed: still the rule-ranked lines the customer accepted.
    after = (await client.get(f"{API}/boq/{b['id']}", headers=c.sm.headers)).json()
    assert [x["title"] for x in after["lines"]] == [x["title"] for x in cur["lines"]]

    # Retired models stay retired.
    r = await client.post(
        f"{ML}/models/{model['id']}/status", json={"status": "retired"}, headers=d.headers
    )
    assert r.status_code == 200
    again = await client.post(
        f"{ML}/models/{model['id']}/status", json={"status": "shadow"}, headers=d.headers
    )
    assert again.status_code == 409
