"""U5: schedule and actuals columns on the execution-layer task.

Pins the column contract the whole date track depends on:

- `planned_start_date` / `planned_end_date` are calendar dates, not
  instants. U9 derives them from the project's start date, and U13/U16
  compare them, so a time-of-day component here would shift a day for any
  site meaningfully offset from UTC.
- `actual_start_at` / `actual_finish_at` are timezone-aware instants, since
  the lifecycle transition that writes them already works in aware UTC.
- The immutable baseline (`planned_start_day` / `planned_end_day`) is a
  separate pair and is never rewritten by actual execution.

The three CHECK constraints are asserted here against SQLite only for the
column contract; the migration carries the authoritative Postgres versions
and a type assertion that fails a drifted database. SQLite does not enforce
these checks, so this file proves the model's shape, not the database's -
see the migration's own verification for that.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import Task


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TaskScheduleColumnsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        Task.__table__.create(bind=self.engine, checkfirst=True)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _task(self, **overrides) -> Task:
        task = Task(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            baseline_id=uuid.uuid4(),
            baseline_task_id=uuid.uuid4(),
            original_code="T001",
            template_sequence=1,
            title="Task",
            schedule_classification="execution",
            applicability="mandatory",
            lifecycle_status="planned",
            **overrides,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def test_all_five_schedule_columns_exist(self):
        columns = {c["name"] for c in inspect(self.engine).get_columns("tasks", schema="siteops_v2")}
        for name in (
            "planned_start_date", "planned_end_date",
            "actual_start_at", "actual_finish_at", "early_start_reason",
        ):
            self.assertIn(name, columns)

    def test_all_five_columns_default_to_null(self):
        task = self._task()
        self.assertIsNone(task.planned_start_date)
        self.assertIsNone(task.planned_end_date)
        self.assertIsNone(task.actual_start_at)
        self.assertIsNone(task.actual_finish_at)
        self.assertIsNone(task.early_start_reason)

    def test_planned_dates_round_trip_as_dates(self):
        task = self._task(
            planned_start_date=date(2026, 8, 1),
            planned_end_date=date(2026, 8, 6),
        )
        self.assertEqual(task.planned_start_date, date(2026, 8, 1))
        self.assertEqual(task.planned_end_date, date(2026, 8, 6))
        self.assertNotIsInstance(task.planned_start_date, datetime)

    def test_actuals_round_trip_as_timestamps(self):
        started = datetime(2026, 8, 2, 7, 30, tzinfo=timezone.utc)
        finished = started + timedelta(days=3)
        task = self._task(actual_start_at=started, actual_finish_at=finished)
        self.assertEqual(task.actual_start_at.year, 2026)
        self.assertEqual(task.actual_start_at.hour, 7)
        self.assertGreater(task.actual_finish_at, task.actual_start_at)

    def test_early_start_reason_round_trips(self):
        task = self._task(
            actual_start_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            early_start_reason="Predecessor cleared and the crew was free.",
        )
        self.assertEqual(task.early_start_reason, "Predecessor cleared and the crew was free.")

    def test_baseline_day_offsets_are_a_separate_pair_and_untouched(self):
        """The immutable baseline must survive alongside the derived dates."""
        task = self._task(
            planned_start_day=5,
            planned_end_day=8,
            planned_start_date=date(2026, 8, 5),
            planned_end_date=date(2026, 8, 8),
        )
        self.assertEqual(task.planned_start_day, 5)
        self.assertEqual(task.planned_end_day, 8)
        self.assertEqual(task.planned_start_date, date(2026, 8, 5))

    def test_the_retired_planned_start_at_column_is_gone(self):
        """The reverted work left a timestamptz `planned_start_at` on some
        machines. It must not be part of the model's contract."""
        columns = {c["name"] for c in inspect(self.engine).get_columns("tasks", schema="siteops_v2")}
        self.assertNotIn("planned_start_at", columns)

    def test_model_declares_the_three_schedule_check_constraints(self):
        names = {c.name for c in Task.__table__.constraints if c.name}
        for name in (
            "ck_v2_tasks_early_start_reason_requires_start",
            "ck_v2_tasks_actual_finish_after_start",
            "ck_v2_tasks_planned_end_after_start",
        ):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
