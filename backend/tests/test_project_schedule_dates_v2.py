"""U9: resolving baseline day offsets into real calendar dates.

Pins the conversion rule itself, the pre-activation carve-out, and the
backfill's idempotency. The rule is deliberately calendar-day arithmetic
(KTD4, user-directed): no weekend or holiday calendar is consulted, so a
45-day project starting on a Tuesday hands over on a calendar day 44 later
regardless of what falls in between.

The immutable baseline (`planned_start_day` / `planned_end_day`) must
survive every path here untouched (R13) - it is what the whole variance
track measures against.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import Task
from app.models import User
from app.project_models import V2Project
from app.template_models import V2Template, V2TemplateVersion
from app.services.project_schedule_dates import (
    ProjectScheduleDateService,
    planned_date_for_day,
    resolve_planned_dates,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class PlannedDateArithmeticTests(unittest.TestCase):
    """The pure conversion, with no database in the way."""

    START = date(2026, 8, 1)

    def test_day_one_is_the_project_start_date(self):
        self.assertEqual(planned_date_for_day(self.START, 1), date(2026, 8, 1))

    def test_day_forty_five_is_forty_four_days_after_the_start(self):
        self.assertEqual(planned_date_for_day(self.START, 45), date(2026, 9, 14))

    def test_a_null_day_yields_no_date(self):
        self.assertIsNone(planned_date_for_day(self.START, None))

    def test_a_day_range_spans_the_corresponding_date_range(self):
        start, end = resolve_planned_dates(self.START, "execution", 4, 6)
        self.assertEqual(start, date(2026, 8, 4))
        self.assertEqual(end, date(2026, 8, 6))

    def test_a_pre_activation_task_receives_no_dates(self):
        start, end = resolve_planned_dates(self.START, "pre_activation", 1, 2)
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_a_project_with_no_start_date_yields_no_dates(self):
        start, end = resolve_planned_dates(None, "execution", 1, 2)
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_dates_cross_a_month_boundary_correctly(self):
        start, end = resolve_planned_dates(date(2026, 1, 20), "execution", 20, 21)
        self.assertEqual(start, date(2026, 2, 8))
        self.assertEqual(end, date(2026, 2, 9))

    def test_dates_cross_a_leap_day_correctly(self):
        """2028 is a leap year; day 3 from 27 Feb must land on 29 Feb."""
        start, _ = resolve_planned_dates(date(2028, 2, 27), "execution", 3, 3)
        self.assertEqual(start, date(2028, 2, 29))


class ProjectScheduleDateServiceTests(unittest.TestCase):
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
        self.service = ProjectScheduleDateService(self.db)
        self._sequence = 0

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _project(self, start_date: date = date(2026, 8, 1)) -> V2Project:
        self._sequence += 1
        project = V2Project(
            id=uuid.uuid4(),
            code=f"P{self._sequence:03d}",
            name=f"Project {self._sequence}",
            client_name="Client",
            site_address="Somewhere",
            start_date=start_date,
            status="active",
            created_by=uuid.uuid4(),
        )
        self.db.add(project)
        self.db.flush()
        return project

    def _task(self, project, start_day, end_day, classification="execution") -> Task:
        self._sequence += 1
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            baseline_id=uuid.uuid4(),
            baseline_task_id=uuid.uuid4(),
            original_code=f"T{self._sequence:03d}",
            template_sequence=self._sequence,
            title=f"Task {self._sequence}",
            schedule_classification=classification,
            applicability="mandatory",
            planned_start_day=start_day,
            planned_end_day=end_day,
            lifecycle_status="planned",
        )
        self.db.add(task)
        self.db.flush()
        return task

    def test_generate_dates_an_undated_project(self):
        project = self._project()
        task = self._task(project, 5, 8)
        changed = self.service.generate_for_project(project)
        self.assertEqual(changed, 1)
        self.db.refresh(task)
        self.assertEqual(task.planned_start_date, date(2026, 8, 5))
        self.assertEqual(task.planned_end_date, date(2026, 8, 8))

    def test_generate_leaves_the_baseline_day_offsets_untouched(self):
        project = self._project()
        task = self._task(project, 5, 8)
        self.service.generate_for_project(project)
        self.db.refresh(task)
        self.assertEqual(task.planned_start_day, 5)
        self.assertEqual(task.planned_end_day, 8)

    def test_generate_skips_pre_activation_tasks(self):
        project = self._project()
        pre = self._task(project, 1, 1, classification="pre_activation")
        self.service.generate_for_project(project)
        self.db.refresh(pre)
        self.assertIsNone(pre.planned_start_date)
        self.assertIsNone(pre.planned_end_date)

    def test_a_second_generate_run_changes_nothing(self):
        project = self._project()
        self._task(project, 5, 8)
        self.assertEqual(self.service.generate_for_project(project), 1)
        self.assertEqual(self.service.generate_for_project(project), 0)

    def test_backfill_dates_a_project_activated_before_this_unit(self):
        project = self._project()
        task = self._task(project, 1, 3)
        report = self.service.backfill()
        self.assertEqual(report["projects_updated"], 1)
        self.assertEqual(report["tasks_updated"], 1)
        self.db.refresh(task)
        self.assertEqual(task.planned_start_date, date(2026, 8, 1))

    def test_re_running_the_backfill_changes_nothing(self):
        project = self._project()
        self._task(project, 1, 3)
        self.service.backfill()
        second = self.service.backfill()
        self.assertEqual(second["tasks_updated"], 0)
        self.assertEqual(second["projects_updated"], 0)

    def test_backfill_can_be_scoped_to_one_project(self):
        first = self._project(date(2026, 8, 1))
        second = self._project(date(2026, 9, 1))
        first_task = self._task(first, 1, 1)
        second_task = self._task(second, 1, 1)
        report = self.service.backfill(project_id=first.id)
        self.assertEqual(report["projects_scanned"], 1)
        self.db.refresh(first_task)
        self.db.refresh(second_task)
        self.assertEqual(first_task.planned_start_date, date(2026, 8, 1))
        self.assertIsNone(second_task.planned_start_date)

    def test_backfill_ignores_a_project_with_no_execution_tasks(self):
        self._project()
        report = self.service.backfill()
        self.assertEqual(report["projects_scanned"], 0)

    def test_each_project_is_dated_from_its_own_start_date(self):
        august = self._project(date(2026, 8, 1))
        september = self._project(date(2026, 9, 1))
        august_task = self._task(august, 3, 3)
        september_task = self._task(september, 3, 3)
        self.service.backfill()
        self.db.refresh(august_task)
        self.db.refresh(september_task)
        self.assertEqual(august_task.planned_start_date, date(2026, 8, 3))
        self.assertEqual(september_task.planned_start_date, date(2026, 9, 3))


if __name__ == "__main__":
    unittest.main()
