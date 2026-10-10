"""The Director's bottleneck view (backlog 10): how long each open project has been in its
stage and who it waits on."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import text

from app.core.db import get_sessionmaker
from app.core.timeutil import utcnow
from app.modules.fieldops.tests.test_field_flow import field_ready

API = "/api/v1"


async def test_bottlenecks_show_stage_age_and_who_it_waits_on(client: Any) -> None:
    p, _both, _runs = await field_ready(client)
    rows = (await client.get(f"{API}/dashboard/bottlenecks", headers=p.c.director.headers)).json()
    row = next(r for r in rows if r["project_id"] == p.pid)
    assert row["stage"] == "field_work" and row["waiting_for"] == "the work"
    assert "field_engineer" in row["waiting_on_roles"] and row["waiting_on_people"]
    assert row["health"] == "moving" and row["days_in_stage"] == 0

    # three weeks without a decision: stuck, and listed first
    async with get_sessionmaker()() as s:
        await s.execute(
            text("UPDATE projects SET created_at = :t WHERE id = :p"),
            {"t": utcnow() - timedelta(days=21), "p": p.pid},
        )
        await s.commit()
    rows = (await client.get(f"{API}/dashboard/bottlenecks", headers=p.c.director.headers)).json()
    assert rows[0]["project_id"] == p.pid and rows[0]["health"] == "stuck"
    assert rows[0]["days_in_stage"] == 21

    # only people with the dashboard
    eng = p.eng[0]
    assert (
        await client.get(f"{API}/dashboard/bottlenecks", headers=eng.headers)
    ).status_code == 403
