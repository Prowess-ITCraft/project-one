"""The scheduler on its own: no database, fixed dates."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from itertools import pairwise

import pytest

from app.core.timeutil import IST
from app.modules.planning import scheduler as s

MON = date(2026, 10, 5)  # a Monday
RULES = s.Rules(time(10, 0), time(18, 0), frozenset({0, 1, 2, 3, 4, 5}), 30)


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=IST)


def test_a_task_uses_working_time_only() -> None:
    out = s.schedule([s.SchedTask("A", 120)], RULES, at(MON, 8))
    assert out["A"].start == at(MON, 10) and out["A"].end == at(MON, 12)


def test_a_long_task_continues_the_next_working_day() -> None:
    out = s.schedule([s.SchedTask("A", 600)], RULES, at(MON, 10))  # 10 hours
    assert out["A"].start == at(MON, 10)
    assert out["A"].end == at(MON + timedelta(days=1), 12)


def test_sunday_is_skipped() -> None:
    sat = date(2026, 10, 10)
    out = s.schedule([s.SchedTask("A", 600)], RULES, at(sat, 10))
    assert out["A"].end == at(date(2026, 10, 12), 12)  # Saturday 8h, Monday 2h


def test_dependencies_and_buffer() -> None:
    tasks = [
        s.SchedTask("B", 60, depends_on=["A"], assignee="e1"),
        s.SchedTask("A", 60, assignee="e1"),
        s.SchedTask("C", 60, assignee="e1"),
    ]
    out = s.schedule(tasks, RULES, at(MON, 10))
    assert out["A"].end <= out["B"].start
    assert out["B"].start >= out["A"].end + timedelta(minutes=30)
    spans = sorted(out.values(), key=lambda x: x.start)
    for a, b in pairwise(spans):
        assert a.end <= b.start  # one engineer is never double booked


def test_two_engineers_work_in_parallel() -> None:
    out = s.schedule(
        [s.SchedTask("A", 120, assignee="e1"), s.SchedTask("B", 120, assignee="e2")],
        RULES,
        at(MON, 10),
    )
    assert out["A"].start == out["B"].start == at(MON, 10)


def test_leave_moves_the_work() -> None:
    out = s.schedule(
        [s.SchedTask("A", 60, assignee="e1")], RULES, at(MON, 10), leaves={"e1": {MON}}
    )
    assert out["A"].start == at(MON + timedelta(days=1), 10)


def test_downtime_tasks_run_only_in_windows() -> None:
    win = s.Slot(at(MON, 20), at(MON, 23))
    out = s.schedule([s.SchedTask("A", 120, downtime=True)], RULES, at(MON, 10), windows=[win])
    assert out["A"].start == at(MON, 20) and out["A"].end == at(MON, 22)


def test_downtime_task_can_span_windows_and_fails_when_too_short() -> None:
    w1, w2 = (
        s.Slot(at(MON, 20), at(MON, 21)),
        s.Slot(at(MON + timedelta(days=1), 20), at(MON + timedelta(days=1), 22)),
    )
    out = s.schedule([s.SchedTask("A", 150, downtime=True)], RULES, at(MON, 10), windows=[w1, w2])
    assert out["A"].start == at(MON, 20) and out["A"].end == at(MON + timedelta(days=1), 21, 30)
    with pytest.raises(s.ScheduleError) as e:
        s.schedule([s.SchedTask("A", 500, downtime=True)], RULES, at(MON, 10), windows=[w1, w2])
    assert e.value.code == "downtime_short"


def test_window_on_leave_day_is_skipped() -> None:
    w1, w2 = (
        s.Slot(at(MON, 20), at(MON, 22)),
        s.Slot(at(MON + timedelta(days=1), 20), at(MON + timedelta(days=1), 22)),
    )
    out = s.schedule(
        [s.SchedTask("A", 60, assignee="e1", downtime=True)],
        RULES,
        at(MON, 10),
        leaves={"e1": {MON}},
        windows=[w1, w2],
    )
    assert out["A"].start == at(MON + timedelta(days=1), 20)


def test_cycles_unknown_and_duplicate_references_are_refused() -> None:
    for tasks, code in (
        ([s.SchedTask("A", 30, ["B"]), s.SchedTask("B", 30, ["A"])], "dependency_cycle"),
        ([s.SchedTask("A", 30, ["A"])], "dependency_cycle"),
        ([s.SchedTask("A", 30, ["Z"])], "unknown_dependency"),
        ([s.SchedTask("A", 30), s.SchedTask("A", 30)], "duplicate_ref"),
    ):
        with pytest.raises(s.ScheduleError) as e:
            s.schedule(tasks, RULES, at(MON, 10))
        assert e.value.code == code


def test_no_working_days_fails_cleanly() -> None:
    r = s.Rules(work_days=frozenset())
    with pytest.raises(s.ScheduleError) as e:
        s.schedule([s.SchedTask("A", 30)], r, at(MON, 10))
    assert e.value.code == "no_working_time"


def test_a_long_window_is_only_cut_on_leave_days() -> None:
    win = s.Slot(at(MON, 0), at(MON + timedelta(days=10), 0))
    leave = {MON, MON + timedelta(days=1)}
    out = s.schedule(
        [s.SchedTask("A", 60, assignee="e1", downtime=True)],
        RULES,
        at(MON, 10),
        leaves={"e1": leave},
        windows=[win],
    )
    assert out["A"].start == at(MON + timedelta(days=2), 0)
