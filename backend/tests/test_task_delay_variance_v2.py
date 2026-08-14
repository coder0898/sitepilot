"""U13: delay as variance between the frozen baseline and what really happened.

Pins the arithmetic, the guard that stops an unfinished terminal task
accruing delay forever (R15), and the early/on-time/late distinction that
the timeline and dashboards need - a task delivered ahead of plan is not
the same fact as a task delivered exactly on plan.

Variance is calendar days (KTD4): no weekend or holiday calendar is
consulted anywhere in this unit.

The user-logged `TaskDelayEvent` is a different concept entirely (KTD6) and
is deliberately absent from this file - nothing here reads or writes it.
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
from app.models import User
from app.project_models import V2Project
from app.template_models import V2Template, V2TemplateVersion
from app.services.task_delay_variance import (
    EARLY,
    LATE,
    NOT_MEASURED,
    ON_TIME,
    DelayVariance,
    compute_delay_variance,
    variance_for_task,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


def _at(day: date, hour: int = 12) -> datetime:
    """A UTC instant on the given calendar day."""
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


class DelayVarianceArithmeticTests(unittest.TestCase):
    """The pure computation, with no database and no wall clock in the way."""

    PLANNED_END = date(2026, 8, 20)
    TODAY = date(2026, 8, 25)

    def _compute(self, **overrides) -> DelayVariance:
        kwargs = {
            "planned_end_date": self.PLANNED_END,
            "actual_finish_at": None,
            "lifecycle_status": "in_progress",
            "today": self.TODAY,
        }
        kwargs.update(overrides)
        return compute_delay_variance(**kwargs)

    def test_finished_ahead_of_plan_reports_early_with_the_day_count(self):
        result = self._compute(
            lifecycle_status="completed",
            actual_finish_at=_at(date(2026, 8, 18)),
        )
        self.assertEqual(result.status, EARLY)
        self.assertEqual(result.days, 2)
        self.assertEqual(result.variance_days, -2)
        self.assertEqual(result.measured_against, "actual_finish")

    def test_finished_after_plan_reports_late_with_the_day_count(self):
        result = self._compute(
            lifecycle_status="completed",
            actual_finish_at=_at(date(2026, 8, 23)),
        )
        self.assertEqual(result.status, LATE)
        self.assertEqual(result.days, 3)
        self.assertEqual(result.variance_days, 3)
        self.assertEqual(result.measured_against, "actual_finish")

    def test_finished_on_the_planned_day_reports_on_time(self):
        result = self._compute(
            lifecycle_status="completed",
            actual_finish_at=_at(self.PLANNED_END),
        )
        self.assertEqual(result.status, ON_TIME)
        self.assertEqual(result.days, 0)
        self.assertEqual(result.variance_days, 0)

    def test_an_in_flight_task_past_its_planned_end_is_late_against_today(self):
        result = self._compute(lifecycle_status="in_progress")
        self.assertEqual(result.status, LATE)
        self.assertEqual(result.variance_days, 5)
        self.assertEqual(result.measured_against, "today")

    def test_an_in_flight_task_delay_grows_with_each_passing_day(self):
        first = self._compute(today=date(2026, 8, 21)).variance_days
        later = self._compute(today=date(2026, 8, 28)).variance_days
        self.assertEqual(first, 1)
        self.assertEqual(later, 8)

    def test_an_in_flight_task_inside_its_window_reports_no_delay(self):
        result = self._compute(today=date(2026, 8, 15))
        self.assertEqual(result.status, ON_TIME)
        self.assertEqual(result.variance_days, 0)

    def test_an_in_flight_task_is_never_reported_early(self):
        """Being ahead of schedule is a claim only a finish can support."""
        result = self._compute(today=date(2026, 8, 1))
        self.assertNotEqual(result.status, EARLY)
        self.assertEqual(result.variance_days, 0)

    def test_a_cancelled_task_with_no_finish_reports_no_delay(self):
        result = self._compute(
            lifecycle_status="cancelled",
            today=date(2027, 1, 1),
        )
        self.assertEqual(result.status, NOT_MEASURED)
        self.assertEqual(result.variance_days, 0)
        self.assertEqual(result.days, 0)
        self.assertIsNone(result.measured_against)
        self.assertFalse(result.is_measured)

    def test_a_completed_task_with_no_recorded_finish_reports_no_delay(self):
        """Completed before U10 landed - measuring it against today would
        invent a delay that grows forever."""
        result = self._compute(
            lifecycle_status="completed",
            today=date(2027, 1, 1),
        )
        self.assertEqual(result.status, NOT_MEASURED)
        self.assertEqual(result.variance_days, 0)

    def test_a_task_with_no_planned_end_reports_no_delay(self):
        result = self._compute(planned_end_date=None)
        self.assertEqual(result.status, NOT_MEASURED)
        self.assertIsNone(result.measured_against)

    def test_an_undated_task_that_finished_still_reports_no_delay(self):
        """No baseline means nothing to measure against, finish or not."""
        result = self._compute(
            planned_end_date=None,
            lifecycle_status="completed",
            actual_finish_at=_at(date(2026, 8, 18)),
        )
        self.assertEqual(result.status, NOT_MEASURED)

    def test_a_finish_before_the_planned_start_is_simply_more_days_early(self):
        result = self._compute(
            lifecycle_status="completed",
            actual_finish_at=_at(date(2026, 8, 5)),
        )
        self.assertEqual(result.status, EARLY)
        self.assertEqual(result.days, 15)

    def test_variance_crosses_a_month_boundary_correctly(self):
        result = compute_delay_variance(
            planned_end_date=date(2026, 8, 31),
            actual_finish_at=_at(date(2026, 9, 3)),
            lifecycle_status="completed",
            today=date(2026, 9, 3),
        )
        self.assertEqual(result.status, LATE)
        self.assertEqual(result.days, 3)

    def test_variance_counts_calendar_days_not_working_days(self):
        """Fri 21 Aug 2026 to Mon 24 Aug 2026 is three days, not one (KTD4)."""
        result = compute_delay_variance(
            planned_end_date=date(2026, 8, 21),
            actual_finish_at=_at(date(2026, 8, 24)),
            lifecycle_status="completed",
            today=date(2026, 8, 24),
        )
        self.assertEqual(result.days, 3)

    def test_a_naive_finish_timestamp_is_read_as_utc(self):
        """SQLite drops tzinfo on read; a naive value must not raise."""
        result = self._compute(
            lifecycle_status="completed",
            actual_finish_at=datetime(2026, 8, 18, 12, 0, 0),
        )
        self.assertEqual(result.status, EARLY)
        self.assertEqual(result.days, 2)

    def test_the_time_of_day_of_a_finish_does_not_change_the_day_count(self):
        """Variance is a calendar-day figure; a late-evening finish on the
        planned day is still on time."""
        result = self._compute(
            lifecycle_status="completed",
            actual_finish_at=_at(self.PLANNED_END, hour=23),
        )
        self.assertEqual(result.status, ON_TIME)

    def test_a_rejected_task_still_in_flight_is_measured_against_today(self):
        result = self._compute(lifecycle_status="rejected")
        self.assertEqual(result.status, LATE)
        self.assertEqual(result.measured_against, "today")


class VarianceForTaskTests(unittest.TestCase):
    """The row adapter, which is all U15/U17 need when they already hold a Task."""

    def _task(self, **overrides) -> Task:
        values = {
            "planned_end_date": date(2026, 8, 20),
            "actual_finish_at": None,
            "lifecycle_status": "in_progress",
            # In `values` rather than hardcoded below, so a test can override
            # it - the pre-activation case needs exactly that.
            "schedule_classification": "execution",
        }
        values.update(overrides)
        return Task(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            baseline_id=uuid.uuid4(),
            baseline_task_id=uuid.uuid4(),
            original_code="T001",
            template_sequence=1,
            title="Task",
            applicability="mandatory",
            **values,
        )

    def test_it_reads_the_planned_end_and_actual_finish_off_the_row(self):
        task = self._task(
            lifecycle_status="completed",
            actual_finish_at=_at(date(2026, 8, 22)),
        )
        result = variance_for_task(task, today=date(2026, 8, 22))
        self.assertEqual(result.status, LATE)
        self.assertEqual(result.days, 2)

    def test_a_pre_activation_task_has_no_planned_dates_and_no_variance(self):
        task = self._task(schedule_classification="pre_activation", planned_end_date=None)
        self.assertEqual(variance_for_task(task).status, NOT_MEASURED)

    def test_today_defaults_to_the_current_utc_day(self):
        """The actuals are UTC instants, so the clock the in-flight branch
        measures against must be the same calendar."""
        overdue_by_three = datetime.now(timezone.utc).date() - timedelta(days=3)
        task = self._task(planned_end_date=overdue_by_three)
        self.assertEqual(variance_for_task(task).variance_days, 3)


if __name__ == "__main__":
    unittest.main()
