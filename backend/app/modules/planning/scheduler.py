"""Pure scheduling logic. No database, no clock: give it tasks and rules, get start and end times.

Rules it follows:
- work happens inside working hours on working days (default Mon to Sat, 10:00 to 18:00 IST);
- an engineer is never double booked, and gets a buffer between tasks;
- a task starts only after everything it depends on has ended;
- an engineer on leave does not work that day;
- a task that needs downtime runs only inside the customer's downtime windows.

A task longer than the time left today carries on into the next working period.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from app.core.timeutil import IST

HORIZON_DAYS = 400


@dataclass(frozen=True)
class Rules:
    work_start: time = time(10, 0)
    work_end: time = time(18, 0)
    work_days: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5})  # Monday is 0
    buffer_minutes: int = 30


@dataclass
class SchedTask:
    ref: str
    minutes: int
    depends_on: list[str] = field(default_factory=list)
    assignee: str | None = None
    downtime: bool = False


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


class ScheduleError(Exception):
    def __init__(self, message: str, code: str = "schedule_failed") -> None:
        super().__init__(message)
        self.code = code


def order_tasks(tasks: Sequence[SchedTask]) -> list[SchedTask]:
    """Dependencies first, otherwise the given order. Raises on an unknown reference or a cycle."""
    by_ref = {t.ref: t for t in tasks}
    if len(by_ref) != len(tasks):
        raise ScheduleError("Two tasks share the same reference.", "duplicate_ref")
    for t in tasks:
        for d in t.depends_on:
            if d not in by_ref:
                raise ScheduleError(
                    f"{t.ref} depends on {d}, which is not in the plan.", "unknown_dependency"
                )
            if d == t.ref:
                raise ScheduleError(f"{t.ref} cannot depend on itself.", "dependency_cycle")
    out: list[SchedTask] = []
    state: dict[str, int] = {}  # 1 = visiting, 2 = done

    def visit(t: SchedTask, trail: list[str]) -> None:
        if state.get(t.ref) == 2:
            return
        if state.get(t.ref) == 1:
            raise ScheduleError(
                "The tasks depend on each other in a circle: " + " to ".join([*trail, t.ref]),
                "dependency_cycle",
            )
        state[t.ref] = 1
        for d in t.depends_on:
            visit(by_ref[d], [*trail, t.ref])
        state[t.ref] = 2
        out.append(t)

    for t in tasks:
        visit(t, [])
    return out


def _at(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=IST)


def _without_leave(w: Slot, leave: set[date]) -> Iterator[Slot]:
    """A downtime window minus the days the engineer is away. Runs of free days stay joined."""
    if not leave:
        yield w
        return
    run_start: datetime | None = None
    day = w.start.astimezone(IST).date()
    last = w.end.astimezone(IST).date()
    while day <= last:
        seg_start = max(w.start, _at(day, time(0, 0)))
        seg_end = min(w.end, _at(day + timedelta(days=1), time(0, 0)))
        if day in leave or seg_end <= seg_start:
            if run_start is not None:
                yield Slot(run_start, _at(day, time(0, 0)))
                run_start = None
        elif run_start is None:
            run_start = seg_start
        day += timedelta(days=1)
    if run_start is not None:
        yield Slot(run_start, w.end)


def _periods(
    after: datetime,
    rules: Rules,
    leave: set[date],
    windows: Sequence[Slot],
    downtime: bool,
) -> Iterator[Slot]:
    """Working periods that end after `after`, earliest first."""
    if downtime:
        for w in sorted(windows, key=lambda s: s.start):
            if w.end <= after:
                continue
            yield from _without_leave(Slot(max(w.start, after), w.end), leave)
        return
    day = after.astimezone(IST).date()
    for _ in range(HORIZON_DAYS):
        if day.weekday() in rules.work_days and day not in leave:
            s, e = _at(day, rules.work_start), _at(day, rules.work_end)
            if e > after:
                yield Slot(max(s, after), e)
        day += timedelta(days=1)


def place(
    after: datetime,
    minutes: int,
    rules: Rules,
    leave: set[date],
    windows: Sequence[Slot],
    downtime: bool,
) -> Slot:
    """Start at the first working moment on or after `after` and use `minutes` of working time."""
    remaining = max(minutes, 1)
    start: datetime | None = None
    cursor = after
    for p in _periods(after, rules, leave, windows, downtime):
        cursor = p.start
        if start is None:
            start = cursor
        take = min(timedelta(minutes=remaining), p.end - cursor)
        cursor += take
        remaining -= int(take.total_seconds() // 60)
        if remaining <= 0:
            return Slot(start, cursor)
    if downtime:
        raise ScheduleError(
            "The downtime windows are too short for the tasks that need downtime. "
            "Add more window time.",
            "downtime_short",
        )
    raise ScheduleError("No working time was found for this task.", "no_working_time")


def schedule(
    tasks: Sequence[SchedTask],
    rules: Rules,
    start: datetime,
    *,
    leaves: dict[str, set[date]] | None = None,
    windows: Sequence[Slot] = (),
) -> dict[str, Slot]:
    """Place every task. `start` is the earliest moment anything may begin."""
    leaves = leaves or {}
    placed: dict[str, Slot] = {}
    free_at: dict[str, datetime] = {}
    buf = timedelta(minutes=rules.buffer_minutes)
    for t in order_tasks(tasks):
        earliest = start
        for d in t.depends_on:
            earliest = max(earliest, placed[d].end)
        if t.assignee:
            earliest = max(earliest, free_at.get(t.assignee, start))
        slot = place(
            earliest,
            t.minutes,
            rules,
            leaves.get(t.assignee or "", set()),
            windows,
            t.downtime,
        )
        placed[t.ref] = slot
        if t.assignee:
            free_at[t.assignee] = slot.end + buf
    return placed
