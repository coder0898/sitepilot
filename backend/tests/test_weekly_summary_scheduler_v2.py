from __future__ import annotations

import asyncio
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.weekly_summary_scheduler as weekly_summary_scheduler
from app.config import settings
from app.execution_models import (
    BaselineTask,
    OutboxEvent,
    ProjectBaseline,
    ProjectExternalApproval,
    SupportAssignmentChange,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDelayEvent,
    TaskDependency,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    ProjectRoleChange,
    V2AuditEvent,
    V2Project,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.report_models import ReportSnapshot
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


SUPER_ADMIN_EMAIL = "superadmin@siteops.local"
SUPER_ADMIN_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")


class WeeklySummaryPassTests(unittest.TestCase):
    """Plan Phase 8 (Part C): `run_weekly_summary_pass` - the scheduled
    caller of `ReportGenerationService.generate('weekly', ...)` on a 7-day
    cadence, mirroring `test_outbox_dispatch_schedule_v2.py`'s /
    `test_report_generation_v2.py`'s harness patterns.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2ProjectTaskDependency.__table__,
            ProjectRoleChange.__table__,
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            TaskVerification.__table__,
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            TaskApprovalDecision.__table__,
            TaskSupportAssignment.__table__,
            SupportAssignmentChange.__table__,
            OutboxEvent.__table__,
            ReportSnapshot.__table__,
            ProjectExternalApproval.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        # `run_weekly_summary_pass` opens its own session from the app's
        # SessionLocal by design (see outbox_scheduler.py's own rationale) -
        # the harness swaps in its own sessionmaker rather than passing a
        # session in.
        self._session_patch = patch.object(weekly_summary_scheduler, "SessionLocal", self.Session)
        self._session_patch.start()
        self.addCleanup(self._session_patch.stop)
        self._settings_patch = patch.object(settings, "bootstrap_super_admin_email", SUPER_ADMIN_EMAIL)
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

        self._seed()

    def tearDown(self):
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            session.add(User(
                id=SUPER_ADMIN_ID, name="Developer Super Admin", email=SUPER_ADMIN_EMAIL,
                role=UserRole.super_admin, active=True,
            ))
            session.flush()

            active_project = V2Project(
                code="PRJ-ACTIVE", name="Active Project", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=SUPER_ADMIN_ID,
            )
            session.add(active_project)
            session.flush()
            self.active_project_id = active_project.id

            draft_project = V2Project(
                code="PRJ-DRAFT", name="Draft Project", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="draft", created_by=SUPER_ADMIN_ID,
            )
            session.add(draft_project)
            session.flush()
            self.draft_project_id = draft_project.id

    def _weekly_snapshots(self, project_id) -> list[ReportSnapshot]:
        with self.Session() as session:
            return list(session.scalars(
                select(ReportSnapshot).where(
                    ReportSnapshot.project_id == project_id, ReportSnapshot.report_type == "weekly",
                )
            ).all())

    def _outbox_events(self, event_type: str) -> list[OutboxEvent]:
        with self.Session() as session:
            return list(session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == event_type)
            ).all())

    # ---- happy path: first-ever weekly report -----------------------------

    def test_a_project_with_no_prior_weekly_snapshot_gets_one_generated(self):
        generated = weekly_summary_scheduler.run_weekly_summary_pass()

        self.assertEqual(generated, 1)
        snapshots = self._weekly_snapshots(self.active_project_id)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].report_type, "weekly")

    def test_generating_the_first_report_emits_the_weekly_summary_event(self):
        weekly_summary_scheduler.run_weekly_summary_pass()

        events = self._outbox_events("report.weekly_summary_generated")
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.aggregate_type, "project")
        self.assertEqual(event.aggregate_id, self.active_project_id)
        self.assertEqual(event.payload["project_id"], str(self.active_project_id))
        snapshot = self._weekly_snapshots(self.active_project_id)[0]
        self.assertEqual(event.payload["report_snapshot_id"], str(snapshot.id))

    # ---- cadence: not due within 7 days, due after -------------------------

    def test_a_second_pass_within_seven_days_does_not_regenerate(self):
        first = weekly_summary_scheduler.run_weekly_summary_pass()
        self.assertEqual(first, 1)

        second = weekly_summary_scheduler.run_weekly_summary_pass()
        self.assertEqual(second, 0)
        self.assertEqual(len(self._weekly_snapshots(self.active_project_id)), 1)

    def test_a_pass_after_seven_days_regenerates(self):
        weekly_summary_scheduler.run_weekly_summary_pass()
        snapshot = self._weekly_snapshots(self.active_project_id)[0]

        # Push the existing snapshot's period_start back 8 days so the
        # cadence check sees it as due again, without needing to actually
        # wait real wall-clock time.
        with self.Session() as session:
            row = session.get(ReportSnapshot, snapshot.id)
            row.period_start = row.period_start - timedelta(days=8)
            row.period_end = row.period_end - timedelta(days=8)
            session.add(row)
            session.commit()

        second = weekly_summary_scheduler.run_weekly_summary_pass()
        self.assertEqual(second, 1)
        self.assertEqual(len(self._weekly_snapshots(self.active_project_id)), 2)

    # ---- only active projects are considered -------------------------------

    def test_a_draft_project_is_never_swept(self):
        weekly_summary_scheduler.run_weekly_summary_pass()
        self.assertEqual(self._weekly_snapshots(self.draft_project_id), [])

    # ---- the pass opens its own session -------------------------------------

    def test_a_pass_with_nothing_due_completes_without_error(self):
        weekly_summary_scheduler.run_weekly_summary_pass()
        self.assertEqual(weekly_summary_scheduler.run_weekly_summary_pass(), 0)


class WeeklySummaryLoopTests(unittest.IsolatedAsyncioTestCase):
    """The loop and its lifecycle, tested with an injected runner - same
    shape as `OutboxDispatchLoopTests`. No wall-clock waiting and no
    database: what is under test is that the schedule survives a bad pass,
    sleeps before its first one, and honours the disable switch."""

    async def _run_briefly(self, task, predicate, timeout=2.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_an_exception_in_one_pass_does_not_stop_the_schedule(self):
        calls = []

        def runner():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("system actor missing")
            return 0

        task = asyncio.create_task(weekly_summary_scheduler.weekly_summary_loop(0.001, runner=runner))
        await self._run_briefly(task, lambda: len(calls) >= 3)
        self.assertGreaterEqual(len(calls), 3)

    async def test_the_loop_sleeps_before_its_first_pass(self):
        calls = []
        task = asyncio.create_task(
            weekly_summary_scheduler.weekly_summary_loop(30.0, runner=lambda: calls.append(1)),
        )
        await asyncio.sleep(0.02)
        self.assertEqual(calls, [])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_the_scheduler_does_not_start_when_disabled(self):
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(settings, "weekly_summary_enabled", False):
            started = weekly_summary_scheduler.start_weekly_summary_scheduler(app)
        self.assertFalse(started)
        self.assertIsNone(getattr(app.state, weekly_summary_scheduler.TASK_ATTRIBUTE, None))

    async def test_the_scheduler_starts_and_stops_when_enabled(self):
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(settings, "weekly_summary_enabled", True), \
             patch.object(settings, "weekly_summary_interval_seconds", 30.0):
            started = weekly_summary_scheduler.start_weekly_summary_scheduler(app)
            self.assertTrue(started)
            self.assertIsNotNone(getattr(app.state, weekly_summary_scheduler.TASK_ATTRIBUTE))
            await weekly_summary_scheduler.stop_weekly_summary_scheduler(app)
        self.assertIsNone(getattr(app.state, weekly_summary_scheduler.TASK_ATTRIBUTE))

    async def test_stopping_a_scheduler_that_never_started_is_harmless(self):
        app = SimpleNamespace(state=SimpleNamespace())
        await weekly_summary_scheduler.stop_weekly_summary_scheduler(app)  # must not raise


class WeeklySummaryWiringTests(unittest.IsolatedAsyncioTestCase):
    """The app actually registers the scheduler, which is the whole point."""

    async def test_the_apps_lifespan_starts_and_stops_the_scheduler(self):
        # `main.py`'s startup/shutdown is a single `lifespan` context manager
        # (not per-feature `@app.on_event` handlers), so wiring is verified
        # by actually running it - `ensure_seed_data` is stubbed out since
        # it would otherwise open a real database connection.
        from app.main import create_app

        app = create_app()
        with patch("app.main.ensure_seed_data"):
            async with app.router.lifespan_context(app):
                self.assertIsNotNone(getattr(app.state, weekly_summary_scheduler.TASK_ATTRIBUTE, None))
            self.assertIsNone(getattr(app.state, weekly_summary_scheduler.TASK_ATTRIBUTE, None))

    def test_the_interval_and_switch_are_configurable_settings(self):
        self.assertIsInstance(settings.weekly_summary_enabled, bool)
        self.assertGreater(settings.weekly_summary_interval_seconds, 0)


if __name__ == "__main__":
    unittest.main()
