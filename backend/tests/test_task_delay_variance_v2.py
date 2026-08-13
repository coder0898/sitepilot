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
    TaskDelayVarianceService,
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


class TaskDelayVarianceServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        # V2Project carries FKs to users and template versions, so those
        # tables must exist before it can be created - even though this unit
        # never reads them.
        for table in (
            User.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            Task.__table__,
        ):
            table.create(bind=self.engine, checkfirst=True)

        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()
        self.service = TaskDelayVarianceService(self.db)
        self._sequence = 0

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _project(self) -> V2Project:
        self._sequence += 1
        project = V2Project(
            id=uuid.uuid4(),
            code=f"P{self._sequence:03d}",
            name=f"Project {self._sequence}",
            client_name="Client",
            site_address="Somewhere",
            start_date=date(2026, 8, 1),
            status="active",
            created_by=uuid.uuid4(),
        )
        self.db.add(project)
        self.db.flush()
        return project

    def _task(self, project, *, planned_end, status="in_progress", finished_on=None) -> Task:
        self._sequence += 1
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            baseline_id=uuid.uuid4(),
            baseline_task_id=uuid.uuid4(),
            original_code=f"T{self._sequence:03d}",
            template_sequence=self._sequence,
            title=f"Task {self._sequence}",
            schedule_classification="execution",
            applicability="mandatory",
            lifecycle_status=status,
            planned_start_date=date(2026, 8, 1) if planned_end else None,
            planned_end_date=planned_end,
            actual_finish_at=_at(finished_on) if finished_on else None,
        )
        self.db.add(task)
        self.db.flush()
        return task

    def test_it_returns_a_variance_for_every_task_in_the_project(self):
        project = self._project()
        late = self._task(project, planned_end=date(2026, 8, 10))
        early = self._task(
            project, planned_end=date(2026, 8, 10),
            status="completed", finished_on=date(2026, 8, 8),
        )
        results = self.service.for_project(project.id, today=date(2026, 8, 12))
        self.assertEqual(set(results), {late.id, early.id})
        self.assertEqual(results[late.id].status, LATE)
        self.assertEqual(results[late.id].days, 2)
        self.assertEqual(results[early.id].status, EARLY)
        self.assertEqual(results[early.id].days, 2)

    def test_a_cancelled_task_long_past_its_window_reports_nothing(self):
        project = self._project()
        cancelled = self._task(project, planned_end=date(2026, 8, 10), status="cancelled")
        results = self.service.for_project(project.id, today=date(2027, 6, 1))
        self.assertEqual(results[cancelled.id].status, NOT_MEASURED)
        self.assertEqual(results[cancelled.id].days, 0)

    def test_it_reads_only_the_requested_project(self):
        first = self._project()
        second = self._project()
        self._task(first, planned_end=date(2026, 8, 10))
        other = self._task(second, planned_end=date(2026, 8, 10))
        results = self.service.for_project(first.id, today=date(2026, 8, 12))
        self.assertNotIn(other.id, results)

    def test_it_writes_nothing(self):
        """This unit computes and returns - it must never persist."""
        project = self._project()
        task = self._task(project, planned_end=date(2026, 8, 10))
        self.service.for_project(project.id, today=date(2026, 8, 12))
        self.assertFalse(self.db.dirty)
        self.assertFalse(self.db.new)
        self.db.refresh(task)
        self.assertIsNone(task.actual_finish_at)

    def test_late_tasks_are_the_measured_late_subset(self):
        project = self._project()
        late = self._task(project, planned_end=date(2026, 8, 10))
        self._task(project, planned_end=date(2026, 8, 30))
        self._task(project, planned_end=date(2026, 8, 10), status="cancelled")
        late_only = self.service.late_tasks(project.id, today=date(2026, 8, 12))
        self.assertEqual([task_id for task_id, _ in late_only], [late.id])


if __name__ == "__main__":
    unittest.main()
