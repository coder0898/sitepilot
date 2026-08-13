"""U13: delay measured as variance against the frozen baseline.

Delay stops being something a person types and becomes the gap between what
the baseline promised (`planned_end_date`, resolved in
`app/services/project_schedule_dates.py`) and what execution recorded
(`actual_finish_at`, written by `app/services/task_lifecycle.py`). Nothing
here is stored: variance is derived on read, so it can never go stale
against the two facts it is derived from.

Four decisions are pinned here:

- **Early, on-time and late are distinct answers.** A task delivered two
  days ahead of plan is not "no delay" - the timeline and the dashboards
  need the credit, and collapsing it into zero would hide every schedule
  saving on the project.
- **A terminal task with no recorded finish is not measured** (R15). A
  cancelled task never finished, and a task completed before the actuals
  landed has no finish to measure. Measuring either against today would
  manufacture a delay that grows by a day forever.
- **Calendar days, not working days** (KTD4, user-directed). No weekend or
  holiday calendar is consulted, matching `project_schedule_dates.py`, so
  the promise and the variance are counted on the same calendar.
- **This is not the user-logged delay event** (KTD6). `TaskDelayEvent`
  records an operational condition a person observed on site; this module
  computes schedule variance. They answer different questions, so this
  module never reads, writes or imports it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task

NOT_MEASURED = "not_measured"
EARLY = "early"
ON_TIME = "on_time"
LATE = "late"

MEASURED_AGAINST_ACTUAL_FINISH = "actual_finish"
MEASURED_AGAINST_TODAY = "today"

# Mirrors `TERMINAL_STATUSES` in `app/services/project_visibility.py`, which
# excludes the same two statuses from `_overdue_tasks` for the same reason.
# Duplicated rather than imported: that module pulls in the whole visibility
# read-model stack, and this one is meant to stay a leaf its consumers can
# import without dragging any of it along.
TERMINAL_STATUSES = ("completed", "cancelled")


@dataclass(frozen=True)
class DelayVariance:
    """One task's schedule variance, in calendar days.

    `variance_days` is signed - negative is ahead of plan, positive is
    behind - so a project's tasks can be summed or sorted without consulting
    `status` first. `days` is the magnitude a screen actually renders
    ("2 days early"), and is 0 whenever nothing was measured.
    """

    status: str
    variance_days: int
    measured_against: str | None

    @property
    def days(self) -> int:
        return abs(self.variance_days)

    @property
    def is_measured(self) -> bool:
        return self.status != NOT_MEASURED

    @property
    def is_late(self) -> bool:
        return self.status == LATE


_NO_VARIANCE = DelayVariance(status=NOT_MEASURED, variance_days=0, measured_against=None)


def _finished_on(actual_finish_at: datetime) -> date:
    """The calendar day a finish instant falls on, read in UTC.

    `actual_finish_at` is a timezone-aware UTC instant while
    `planned_end_date` is a bare date, so one side has to be projected onto
    the other's calendar. UTC is the choice because that is the clock the
    lifecycle transition stamps and the only one every row here shares; the
    portal has no per-project site timezone to convert into. The cost is
    that a finish logged late in the evening at a site running well ahead of
    UTC lands on the previous UTC day - one day of jitter on a schedule
    counted in days, which is preferable to inventing a timezone.

    A naive value is read as UTC: SQLite (the test harness) drops tzinfo on
    read, and a naive/aware comparison would raise rather than answer.
    """
    if actual_finish_at.tzinfo is None:
        return actual_finish_at.replace(tzinfo=timezone.utc).date()
    return actual_finish_at.astimezone(timezone.utc).date()


def compute_delay_variance(
    *,
    planned_end_date: date | None,
    actual_finish_at: datetime | None,
    lifecycle_status: str,
    today: date,
) -> DelayVariance:
    """Variance between one task's planned end and what it actually did.

    Pure - plain values in, a value object out - so the arithmetic and the
    R15 guard are testable without a database, and so a caller can ask the
    question about a task it is still assembling.

    Order matters. A recorded finish wins over the task's current status:
    the finish is the harder fact, and reading it first keeps the answer
    stable if a completed task is later reopened for rework.
    """
    if planned_end_date is None:
        # No baseline promise, so there is nothing to have missed. Covers
        # pre-activation tasks and any project activated before U9 dated it.
        return _NO_VARIANCE

    if actual_finish_at is not None:
        return _variance(
            (_finished_on(actual_finish_at) - planned_end_date).days,
            MEASURED_AGAINST_ACTUAL_FINISH,
        )

    if lifecycle_status in TERMINAL_STATUSES:
        # R15: the task will never record a finish - it was cancelled, or it
        # completed before the actuals existed. Either way today's date says
        # nothing about it, and measuring against today would grow a delay
        # for the rest of the project's life.
        return _NO_VARIANCE

    # Still in flight, so the exposure so far is measured against today. It
    # can only be late or not-yet-late: running early is a claim only a
    # finish can support, and an unfinished task may still overrun.
    return _variance(max((today - planned_end_date).days, 0), MEASURED_AGAINST_TODAY)


def _variance(variance_days: int, measured_against: str) -> DelayVariance:
    if variance_days < 0:
        status = EARLY
    elif variance_days == 0:
        status = ON_TIME
    else:
        status = LATE
    return DelayVariance(
        status=status,
        variance_days=variance_days,
        measured_against=measured_against,
    )


def variance_for_task(task: Task, *, today: date | None = None) -> DelayVariance:
    """Variance for a task row a caller already holds.

    `today` defaults to the current UTC day rather than the server's local
    day, so the in-flight branch is counted on the same calendar the actuals
    are stamped in.
    """
    return compute_delay_variance(
        planned_end_date=task.planned_end_date,
        actual_finish_at=task.actual_finish_at,
        lifecycle_status=task.lifecycle_status,
        today=today or datetime.now(timezone.utc).date(),
    )


class TaskDelayVarianceService:
    """Reads a project's tasks and computes each one's variance.

    Read-only by construction: it selects, computes and returns. Nothing in
    this unit writes, so a caller can invoke it on any request without
    thinking about the transaction.
    """

    def __init__(self, db: Session):
        self.db = db

    def for_project(
        self, project_id: uuid.UUID, *, today: date | None = None
    ) -> dict[uuid.UUID, DelayVariance]:
        """Every task's variance, keyed by task id for joining on the caller's side.

        Undated and terminal-without-finish tasks are included with a
        not-measured variance rather than omitted, so a consumer iterating
        its own task list always finds an entry and never has to decide what
        a missing key meant.
        """
        as_of = today or datetime.now(timezone.utc).date()
        tasks = self.db.scalars(select(Task).where(Task.project_id == project_id))
        return {task.id: variance_for_task(task, today=as_of) for task in tasks}

    def late_tasks(
        self, project_id: uuid.UUID, *, today: date | None = None
    ) -> list[tuple[uuid.UUID, DelayVariance]]:
        """The behind-schedule tasks, worst first - what a dashboard leads with."""
        late = [
            (task_id, variance)
            for task_id, variance in self.for_project(project_id, today=today).items()
            if variance.is_late
        ]
        return sorted(late, key=lambda row: row[1].variance_days, reverse=True)
