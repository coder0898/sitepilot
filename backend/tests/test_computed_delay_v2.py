"""U10: delay as a measurement no execution role can influence.

Two things here are easy to get wrong and expensive when wrong:

The operand order. Delay is the completion reference minus the target
finish. Reversed, it is negative for every late task, floors to zero, and
silently neutralises the at-risk flag built on the same number - a bug that
looks like "no delays" rather than like a bug.

The terminal-status guard. A cancelled task, and a task completed before
actual dates were recorded, both have a target finish and no actual finish.
Measured against `now` they would accrue a day of delay every day forever
and pin the project to at-risk permanently.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import Task
from app.services.project_schedule_dates import target_finish_at
from app.services.project_visibility import ProjectVisibilityService


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw): return "JSON"


START = date(2026, 8, 1)


class _Project:
    """The two fields `_handover_at_risk_tasks` actually reads."""

    def __init__(self, handover: date | None):
        self.target_handover_date = handover


class ComputedDelayTests(unittest.TestCase):
    """Exercises the two derived helpers directly with an injected `now`.
    `summarize` reads the clock itself, so a delay measured 'today' can only
    be pinned down at this level."""

    def setUp(self):
        self.service = ProjectVisibilityService.__new__(ProjectVisibilityService)

    @staticmethod
    def task(code, *, end_day=8, status="in_progress", actual_finish=None):
        return Task(
            id=uuid.uuid4(), original_code=code, title=f"Task {code}", lifecycle_status=status,
            due_at=target_finish_at(START, end_day) if end_day is not None else None,
            actual_finish_at=actual_finish,
        )

    def delays(self, tasks, now):
        return {row.original_code: row for row in self.service._computed_delays(tasks, now)}

    # ---- the measurement ---------------------------------------------------

    def test_an_unfinished_task_three_days_past_its_target_reports_three_days(self):
        """Covers AE4. Target finish is the exclusive end of day 8, i.e.
        midnight starting 9 Aug; noon on 12 Aug is three days past it."""
        rows = self.delays([self.task("T008")], datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(rows["T008"].delay_days, 3)

    def test_the_operands_are_not_the_wrong_way_round(self):
        """The specific failure worth naming: reversed, this reports zero
        for a late task, and the at-risk flag built on it silently dies."""
        rows = self.delays([self.task("T008")], datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(rows["T008"].delay_days, 11)
        self.assertGreater(rows["T008"].delay_days, 0)

    def test_a_task_finished_on_time_or_early_reports_zero_not_a_negative(self):
        on_time = self.task("T008", status="completed",
                            actual_finish=datetime(2026, 8, 8, 16, 0, tzinfo=timezone.utc))
        early = self.task("T009", status="completed",
                          actual_finish=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc))
        rows = self.delays([on_time, early], datetime(2026, 8, 30, tzinfo=timezone.utc))
        self.assertEqual(rows["T008"].delay_days, 0)
        self.assertEqual(rows["T009"].delay_days, 0)

    def test_a_task_finished_late_reports_its_delay_and_stops_growing(self):
        finished = self.task("T008", status="completed",
                             actual_finish=datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc))
        for now in (datetime(2026, 8, 13, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc)):
            with self.subTest(now=now.date()):
                self.assertEqual(self.delays([finished], now)["T008"].delay_days, 3)

    def test_a_task_with_no_target_finish_has_no_delay(self):
        """The pre-activation case - nothing to measure against."""
        self.assertEqual(self.delays([self.task("T000", end_day=None)],
                                     datetime(2026, 12, 1, tzinfo=timezone.utc)), {})

    # ---- the guard that stops delay growing forever -------------------------

    def test_a_cancelled_task_with_no_actual_finish_has_no_delay(self):
        cancelled = self.task("T008", status="cancelled")
        self.assertEqual(self.delays([cancelled], datetime(2026, 12, 1, tzinfo=timezone.utc)), {})

    def test_a_task_completed_before_actual_dates_existed_has_no_delay(self):
        """Terminal, target finish long past, no actual finish recorded.
        Measured against `now` this would report 115 days and climbing."""
        historical = self.task("T008", status="completed")
        self.assertEqual(self.delays([historical], datetime(2026, 12, 1, tzinfo=timezone.utc)), {})

    # ---- handover at risk ---------------------------------------------------

    def test_at_risk_names_only_the_task_projected_past_handover(self):
        """Covers AE5.

        Note what actually discriminates here, because it is not what it
        first looks like. An unfinished task's projection is target finish
        plus the delay accrued so far, and that delay is measured against
        now - so every unfinished overdue task projects to *today*. Being
        nine days late is therefore not what threatens a handover five
        weeks out; being scheduled to finish after it is.
        """
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        already_late = self.task("T010", end_day=10)          # target 11 Aug, 9 days late
        scheduled_past_handover = self.task("T052", end_day=52)  # target 22 Sep, not yet due
        delays = self.service._computed_delays([already_late, scheduled_past_handover], now)
        self.assertEqual({r.original_code: r.delay_days for r in delays}, {"T010": 9, "T052": 0})

        at_risk = self.service._handover_at_risk_tasks(_Project(date(2026, 9, 14)), delays)
        self.assertEqual([r.original_code for r in at_risk], ["T052"])

    def test_unfinished_work_past_the_handover_date_puts_handover_at_risk(self):
        """The other way it fires: the handover date has come and gone and
        work is still open."""
        now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        delays = self.service._computed_delays([self.task("T010", end_day=10)], now)
        at_risk = self.service._handover_at_risk_tasks(_Project(date(2026, 9, 14)), delays)
        self.assertEqual([r.original_code for r in at_risk], ["T010"])

    def test_a_project_with_nothing_projected_past_handover_is_not_at_risk(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        delays = self.service._computed_delays([self.task("T010", end_day=10)], now)
        self.assertEqual(self.service._handover_at_risk_tasks(_Project(date(2026, 12, 31)), delays), [])

    def test_a_task_that_already_finished_late_cannot_put_handover_at_risk(self):
        """It has done its damage; it cannot do more."""
        finished_late = self.task("T045", end_day=45, status="completed",
                                  actual_finish=datetime(2026, 10, 1, tzinfo=timezone.utc))
        delays = self.service._computed_delays([finished_late], datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertEqual(self.service._handover_at_risk_tasks(_Project(date(2026, 9, 14)), delays), [])

    def test_a_project_with_no_handover_date_is_never_at_risk(self):
        delays = self.service._computed_delays([self.task("T045", end_day=45)],
                                               datetime(2026, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(self.service._handover_at_risk_tasks(_Project(None), delays), [])

    def test_a_task_finishing_exactly_on_the_handover_day_is_not_at_risk(self):
        """The handover date is inclusive - work landing on it is on time."""
        now = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)
        on_the_day = self.task("T045", end_day=45)
        delays = self.service._computed_delays([on_the_day], now)
        self.assertEqual(delays[0].delay_days, 0)
        self.assertEqual(self.service._handover_at_risk_tasks(_Project(date(2026, 9, 14)), delays), [])


if __name__ == "__main__":
    unittest.main()
