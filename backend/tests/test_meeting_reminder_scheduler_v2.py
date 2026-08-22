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

import app.services.meeting_reminder_scheduler as meeting_reminder_scheduler
from app.broadcast_models import Broadcast, BroadcastRecipient, BroadcastTemplate
from app.config import settings
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


SUPER_ADMIN_EMAIL = "superadmin@siteops.local"
SUPER_ADMIN_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


class MeetingReminderPassTests(unittest.TestCase):
    """Plan Phase 9: `run_meeting_reminder_pass` - the scheduled caller of
    `send_scheduled_broadcast`, mirroring
    `test_weekly_summary_scheduler_v2.py`'s harness pattern for the
    scheduler side and `test_broadcasts_v2.py`'s fixtures for the
    `Broadcast`/`BroadcastRecipient` side.
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
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2AuditEvent.__table__,
            Broadcast.__table__,
            BroadcastRecipient.__table__,
            BroadcastTemplate.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        # `run_meeting_reminder_pass` opens its own session from the app's
        # SessionLocal by design (see outbox_scheduler.py's own rationale) -
        # the harness swaps in its own sessionmaker rather than passing a
        # session in.
        self._session_patch = patch.object(meeting_reminder_scheduler, "SessionLocal", self.Session)
        self._session_patch.start()
        self.addCleanup(self._session_patch.stop)
        self._settings_patch = patch.object(settings, "bootstrap_super_admin_email", SUPER_ADMIN_EMAIL)
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

        self.project_id = uuid.uuid4()
        self._seed()

    def tearDown(self):
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            session.add(User(
                id=SUPER_ADMIN_ID, name="Developer Super Admin", email=SUPER_ADMIN_EMAIL,
                role=UserRole.super_admin, active=True,
            ))
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.add(User(
                id=PM_ID, name="Niddhi", email="niddhi@example.com", phone="+919876500001",
                role=UserRole.project_manager, active=True,
            ))
            session.flush()
            session.add(EmployeeProfile(user_id=PM_ID, employee_code="EMP-PM", designation="PM", availability="available"))
            session.flush()

            session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Test Project", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))
            session.flush()

            pm_employee = session.query(EmployeeProfile).filter_by(user_id=PM_ID).one()
            session.add(V2ProjectMembership(
                project_id=self.project_id, employee_id=pm_employee.id, project_role="project_manager",
                assigned_by=ADMIN_ID, assignment_reason="Initial assignment.",
            ))

    def _make_broadcast(self, session, *, status: str, scheduled_at, title="Site Walkthrough") -> Broadcast:
        broadcast = Broadcast(
            id=uuid.uuid4(), project_id=self.project_id, title=title, message_body="Body",
            recipient_groups=["project_manager"], send_mode="scheduled", scheduled_at=scheduled_at,
            status=status, created_by=ADMIN_ID,
        )
        session.add(broadcast)
        session.flush()
        session.add(BroadcastRecipient(
            broadcast_id=broadcast.id, recipient_type="project_manager", user_id=PM_ID,
            name="Niddhi", role_label="Project Manager", phone="+919876500001", email="niddhi@example.com",
            channels=["in_app", "email", "whatsapp"], delivery_status="pending",
        ))
        return broadcast

    def _get(self, broadcast_id) -> Broadcast:
        with self.Session() as session:
            return session.get(Broadcast, broadcast_id)

    # ---- a due scheduled broadcast gets sent -------------------------------

    def test_a_due_scheduled_broadcast_is_sent(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        with self.Session.begin() as session:
            broadcast = self._make_broadcast(session, status="scheduled", scheduled_at=past)
            broadcast_id = broadcast.id

        sent = meeting_reminder_scheduler.run_meeting_reminder_pass()

        self.assertEqual(sent, 1)
        row = self._get(broadcast_id)
        self.assertEqual(row.status, "sent")
        self.assertIsNotNone(row.sent_at)
        with self.Session() as session:
            recipient = session.scalars(
                select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast_id)
            ).one()
            self.assertEqual(recipient.delivery_status, "sent")

    def test_sending_writes_an_audit_event(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        with self.Session.begin() as session:
            self._make_broadcast(session, status="scheduled", scheduled_at=past)

        meeting_reminder_scheduler.run_meeting_reminder_pass()

        with self.Session() as session:
            events = session.query(V2AuditEvent).filter_by(project_id=self.project_id, action="BROADCAST_SENT").all()
            self.assertEqual(len(events), 1)

    # ---- a not-yet-due scheduled broadcast is left alone -------------------

    def test_a_not_yet_due_scheduled_broadcast_is_left_alone(self):
        future = datetime.now(timezone.utc) + timedelta(days=1)
        with self.Session.begin() as session:
            broadcast = self._make_broadcast(session, status="scheduled", scheduled_at=future)
            broadcast_id = broadcast.id

        sent = meeting_reminder_scheduler.run_meeting_reminder_pass()

        self.assertEqual(sent, 0)
        self.assertEqual(self._get(broadcast_id).status, "scheduled")

    # ---- an already-sent broadcast is never touched ------------------------

    def test_an_already_sent_broadcast_is_never_touched(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        with self.Session.begin() as session:
            broadcast = self._make_broadcast(session, status="sent", scheduled_at=past)
            broadcast.sent_at = past
            broadcast_id = broadcast.id

        sent = meeting_reminder_scheduler.run_meeting_reminder_pass()

        self.assertEqual(sent, 0)
        self.assertEqual(self._get(broadcast_id).status, "sent")

    # ---- key regression: running the pass twice never double-sends --------

    def test_running_the_pass_twice_does_not_double_send(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        with self.Session.begin() as session:
            broadcast = self._make_broadcast(session, status="scheduled", scheduled_at=past)
            broadcast_id = broadcast.id

        first = meeting_reminder_scheduler.run_meeting_reminder_pass()
        second = meeting_reminder_scheduler.run_meeting_reminder_pass()

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        with self.Session() as session:
            events = session.query(V2AuditEvent).filter_by(project_id=self.project_id, action="BROADCAST_SENT").all()
            self.assertEqual(len(events), 1)
        self.assertEqual(self._get(broadcast_id).status, "sent")

    # ---- multiple due broadcasts in one pass -------------------------------

    def test_multiple_due_broadcasts_are_all_sent_in_one_pass(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        with self.Session.begin() as session:
            self._make_broadcast(session, status="scheduled", scheduled_at=past, title="Reminder A")
            self._make_broadcast(session, status="scheduled", scheduled_at=past, title="Reminder B")

        sent = meeting_reminder_scheduler.run_meeting_reminder_pass()
        self.assertEqual(sent, 2)

    # ---- a pass with nothing due completes without error -------------------

    def test_a_pass_with_nothing_due_completes_without_error(self):
        self.assertEqual(meeting_reminder_scheduler.run_meeting_reminder_pass(), 0)


class MeetingReminderLoopTests(unittest.IsolatedAsyncioTestCase):
    """The loop and its lifecycle, tested with an injected runner - same
    shape as `WeeklySummaryLoopTests`. No wall-clock waiting and no
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

        task = asyncio.create_task(meeting_reminder_scheduler.meeting_reminder_loop(0.001, runner=runner))
        await self._run_briefly(task, lambda: len(calls) >= 3)
        self.assertGreaterEqual(len(calls), 3)

    async def test_the_loop_sleeps_before_its_first_pass(self):
        calls = []
        task = asyncio.create_task(
            meeting_reminder_scheduler.meeting_reminder_loop(30.0, runner=lambda: calls.append(1)),
        )
        await asyncio.sleep(0.02)
        self.assertEqual(calls, [])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_the_scheduler_does_not_start_when_disabled(self):
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(settings, "meeting_reminder_enabled", False):
            started = meeting_reminder_scheduler.start_meeting_reminder_scheduler(app)
        self.assertFalse(started)
        self.assertIsNone(getattr(app.state, meeting_reminder_scheduler.TASK_ATTRIBUTE, None))

    async def test_the_scheduler_starts_and_stops_when_enabled(self):
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(settings, "meeting_reminder_enabled", True), \
             patch.object(settings, "meeting_reminder_interval_seconds", 30.0):
            started = meeting_reminder_scheduler.start_meeting_reminder_scheduler(app)
            self.assertTrue(started)
            self.assertIsNotNone(getattr(app.state, meeting_reminder_scheduler.TASK_ATTRIBUTE))
            await meeting_reminder_scheduler.stop_meeting_reminder_scheduler(app)
        self.assertIsNone(getattr(app.state, meeting_reminder_scheduler.TASK_ATTRIBUTE))

    async def test_stopping_a_scheduler_that_never_started_is_harmless(self):
        app = SimpleNamespace(state=SimpleNamespace())
        await meeting_reminder_scheduler.stop_meeting_reminder_scheduler(app)  # must not raise


class MeetingReminderWiringTests(unittest.IsolatedAsyncioTestCase):
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
                self.assertIsNotNone(getattr(app.state, meeting_reminder_scheduler.TASK_ATTRIBUTE, None))
            self.assertIsNone(getattr(app.state, meeting_reminder_scheduler.TASK_ATTRIBUTE, None))

    def test_the_interval_and_switch_are_configurable_settings(self):
        self.assertIsInstance(settings.meeting_reminder_enabled, bool)
        self.assertGreater(settings.meeting_reminder_interval_seconds, 0)
        # Shorter than the hourly schedulers - see config.py's own comment
        # for why a meeting reminder needs finer-grained polling.
        self.assertLess(settings.meeting_reminder_interval_seconds, settings.weekly_summary_interval_seconds)


if __name__ == "__main__":
    unittest.main()
