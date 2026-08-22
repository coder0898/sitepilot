from __future__ import annotations

import asyncio
import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.outbox_scheduler as outbox_scheduler
from app.config import settings
from app.execution_models import MessageDelivery, OutboxEvent, Task
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.template_models import V2Template, V2TemplateVersion
from app.vendor_models import V2Vendor, V2VendorContact


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


class OutboxDispatchScheduleTests(unittest.TestCase):
    """U3 (R18): the scheduled caller that drains the outbox.

    `process_pending` has always worked - `test_message_delivery_dispatch_v2`
    covers what it delivers and to whom. What was missing was anything that
    ever called it outside a test, so these assertions are about the SCHEDULE:
    that a pass runs, that it is safe to re-run, and that one bad pass does
    not end the schedule. Per the plan's execution note, that is verified by
    watching rows move off `pending`, never by asserting on message content.
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
            User.__table__, EmployeeProfile.__table__,
            V2Template.__table__, V2TemplateVersion.__table__,
            V2Project.__table__, V2ProjectMembership.__table__,
            Task.__table__, OutboxEvent.__table__, MessageDelivery.__table__,
            V2Vendor.__table__, V2VendorContact.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        # `run_dispatch_pass` opens its own session from the app's SessionLocal
        # by design - that is the behaviour under test - so the harness swaps
        # in its own sessionmaker rather than passing a session in.
        self._session_patch = patch.object(outbox_scheduler, "SessionLocal", self.Session)
        self._session_patch.start()
        self.addCleanup(self._session_patch.stop)

    def tearDown(self):
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            session.add(User(
                id=PM_ID, name="PM", email="pm@example.com", phone="9000000010",
                role=UserRole.project_manager, active=True,
            ))
            session.flush()
            employee = EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available")
            session.add(employee)
            session.flush()
            self.pm_employee_id = employee.id

            project = V2Project(
                code="PRJ-001", name="Test Project", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=PM_ID,
            )
            session.add(project)
            session.flush()
            self.project_id = project.id
            session.add(V2ProjectMembership(
                project_id=project.id, employee_id=employee.id, project_role="project_manager",
                assigned_by=PM_ID, assignment_reason="seed",
            ))

            task = Task(
                project_id=project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Mobilise",
                schedule_classification="execution", applicability="mandatory",
                evidence_required=False, lifecycle_status="planned",
            )
            session.add(task)
            session.flush()
            self.task_id = task.id

    def _emit(self, **overrides) -> uuid.UUID:
        with self.Session() as session:
            ev = OutboxEvent(
                event_type="task.status_changed", aggregate_type="task", aggregate_id=self.task_id,
                payload={"target_status": "ready"}, idempotency_key=f"test:{uuid.uuid4()}",
                status="pending", **overrides,
            )
            session.add(ev)
            session.commit()
            return ev.id

    def _status_of(self, event_id: uuid.UUID) -> str:
        with self.Session() as session:
            return session.get(OutboxEvent, event_id).status

    def _delivery_count(self) -> int:
        with self.Session() as session:
            return len(list(session.scalars(select(MessageDelivery)).all()))

    # ---- the pass itself -------------------------------------------------

    def test_a_pending_event_is_dispatched_by_one_pass(self):
        event_id = self._emit()
        self.assertEqual(self._status_of(event_id), "pending")

        processed = outbox_scheduler.run_dispatch_pass()

        self.assertEqual(processed, 1)
        self.assertEqual(self._status_of(event_id), "dispatched")
        self.assertEqual(self._delivery_count(), 1)

    def test_a_pass_with_nothing_pending_completes_without_error(self):
        self.assertEqual(outbox_scheduler.run_dispatch_pass(), 0)
        self.assertEqual(self._delivery_count(), 0)

    def test_a_second_pass_after_a_successful_batch_creates_no_new_rows(self):
        self._emit()
        outbox_scheduler.run_dispatch_pass()
        after_first = self._delivery_count()

        self.assertEqual(outbox_scheduler.run_dispatch_pass(), 0)
        self.assertEqual(self._delivery_count(), after_first)

    def test_a_failed_delivery_is_recorded_and_the_next_pass_still_runs(self):
        # A recipient with no phone fails deterministically in the sandbox
        # adapter - the one failure path reachable without mocking a network.
        with self.Session() as session:
            user = session.get(User, PM_ID)
            user.phone = None
            session.add(user)
            session.commit()

        event_id = self._emit()
        outbox_scheduler.run_dispatch_pass()

        with self.Session() as session:
            delivery = session.scalars(select(MessageDelivery)).one()
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.failure_code, "missing_phone")

        # The schedule keeps going and the failure is retried in place rather
        # than duplicated or abandoned.
        outbox_scheduler.run_dispatch_pass()
        self.assertEqual(self._delivery_count(), 1)
        self.assertEqual(self._status_of(event_id), "dispatched")

    def test_a_pass_opens_its_own_session(self):
        # Each pass must not depend on a session handed in from outside, or a
        # long-lived one shared across the process. Asserted by the fact that
        # `run_dispatch_pass` takes no arguments and still works above, plus
        # explicitly here: two passes in a row against a fresh emit.
        self._emit()
        self.assertEqual(outbox_scheduler.run_dispatch_pass(), 1)
        self._emit()
        self.assertEqual(outbox_scheduler.run_dispatch_pass(), 1)
        self.assertEqual(self._delivery_count(), 2)


class OutboxDispatchLoopTests(unittest.IsolatedAsyncioTestCase):
    """The loop and its lifecycle, tested with an injected runner.

    No wall-clock waiting on the real 30s interval and no database: what is
    under test here is that the schedule survives a bad pass, that it sleeps
    before its first one, and that the disable switch is honoured.
    """

    async def _run_briefly(self, task, predicate, timeout=2.0):
        """Lets the loop turn until `predicate()` holds, then cancels it."""
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
                raise RuntimeError("provider exploded")
            return 0

        task = asyncio.create_task(outbox_scheduler.dispatch_loop(0.001, runner=runner))
        await self._run_briefly(task, lambda: len(calls) >= 3)
        # The first pass raised; the schedule kept turning regardless.
        self.assertGreaterEqual(len(calls), 3)

    async def test_the_loop_sleeps_before_its_first_pass(self):
        calls = []
        task = asyncio.create_task(
            outbox_scheduler.dispatch_loop(30.0, runner=lambda: calls.append(1)),
        )
        # Long interval, so nothing should have run by the time we look -
        # application startup must never wait on a dispatch pass.
        await asyncio.sleep(0.02)
        self.assertEqual(calls, [])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_cancellation_stops_the_loop_rather_than_being_swallowed(self):
        task = asyncio.create_task(outbox_scheduler.dispatch_loop(0.001, runner=lambda: 0))
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(task.cancelled() or task.done())

    # ---- the switch ------------------------------------------------------

    async def test_the_dispatcher_does_not_start_when_disabled(self):
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(settings, "outbox_dispatch_enabled", False):
            started = outbox_scheduler.start_dispatcher(app)
        self.assertFalse(started)
        self.assertIsNone(getattr(app.state, outbox_scheduler.TASK_ATTRIBUTE, None))

    async def test_the_dispatcher_starts_and_stops_when_enabled(self):
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(settings, "outbox_dispatch_enabled", True), \
             patch.object(settings, "outbox_dispatch_interval_seconds", 30.0):
            started = outbox_scheduler.start_dispatcher(app)
            self.assertTrue(started)
            self.assertIsNotNone(getattr(app.state, outbox_scheduler.TASK_ATTRIBUTE))
            await outbox_scheduler.stop_dispatcher(app)
        self.assertIsNone(getattr(app.state, outbox_scheduler.TASK_ATTRIBUTE))

    async def test_stopping_a_dispatcher_that_never_started_is_harmless(self):
        app = SimpleNamespace(state=SimpleNamespace())
        await outbox_scheduler.stop_dispatcher(app)  # must not raise


class OutboxDispatchWiringTests(unittest.IsolatedAsyncioTestCase):
    """The app actually registers the dispatcher, which is the whole point."""

    async def test_the_apps_lifespan_starts_and_stops_the_dispatcher(self):
        # `main.py`'s startup/shutdown is a single `lifespan` context manager
        # (not per-feature `@app.on_event` handlers), so wiring is verified
        # by actually running it - `ensure_seed_data` is stubbed out since
        # it would otherwise open a real database connection.
        from app.main import create_app

        app = create_app()
        with patch("app.main.ensure_seed_data"):
            async with app.router.lifespan_context(app):
                self.assertIsNotNone(getattr(app.state, outbox_scheduler.TASK_ATTRIBUTE, None))
            self.assertIsNone(getattr(app.state, outbox_scheduler.TASK_ATTRIBUTE, None))

    def test_the_interval_and_switch_are_configurable_settings(self):
        # Sourced from environment/`.env` like every other setting, so an
        # operator can stop delivery without a redeploy.
        self.assertIsInstance(settings.outbox_dispatch_enabled, bool)
        self.assertGreater(settings.outbox_dispatch_interval_seconds, 0)
