"""The rules behind the field summary and the Director's dashboard, without a database."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from app.modules.fieldops.models import TaskRun
from app.modules.fieldops.service import summarise_runs

NOW = datetime(2026, 10, 4, 10, 0, tzinfo=UTC)


def run(ref: str, state: str, start: int, end: int, **extra: Any) -> TaskRun:
    """A task run planned `start` and `end` hours from NOW."""
    fields = {"last_check_passed": None, "rework_count": 0, **extra}
    return cast(
        TaskRun,
        SimpleNamespace(
            task_ref=ref,
            state=state,
            planned_start=NOW + timedelta(hours=start),
            planned_end=NOW + timedelta(hours=end),
            **fields,
        ),
    )


def test_late_overdue_failing_and_counts() -> None:
    runs = [
        run("T01", "assigned", -1, 2),  # should have started an hour ago: late
        run("T02", "accepted", 1, 3),  # not due yet
        run("T03", "configured", -5, -1, last_check_passed=False, rework_count=1),
        run("T04", "verifier_review", -5, -1),  # past its end but waiting on the verifier
        run("T05", "closed", -5, -1, rework_count=2),
        run("T06", "blocked", -2, 1),
    ]
    s = summarise_runs(runs, NOW)
    assert [r.task_ref for r in s["late"]] == ["T01"]
    assert [r.task_ref for r in s["overdue"]] == ["T03"]
    assert [r.task_ref for r in s["failing_checks"]] == ["T03"]
    assert [r.task_ref for r in s["blocked"]] == ["T06"]
    assert s["counts"]["closed"] == 1 and s["counts"]["engine_check"] == 0
    assert s["total"] == 6 and s["closed_share"] == round(1 / 6, 4) and s["rework"] == 3


def test_a_task_due_within_the_half_hour_grace_is_not_late() -> None:
    s = summarise_runs([run("T01", "assigned", 0, 2)], NOW + timedelta(minutes=29))
    assert s["late"] == []


def test_no_runs() -> None:
    s = summarise_runs([], NOW)
    assert s["total"] == 0 and s["closed_share"] == 0.0 and s["counts"]["assigned"] == 0
