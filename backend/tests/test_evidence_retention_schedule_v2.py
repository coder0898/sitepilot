"""The scheduled caller for the evidence retention sweep - mirrors
`test_outbox_dispatch_schedule_v2.py`'s structure exactly, since
`evidence_retention_scheduler.py` is a deliberate copy of
`outbox_scheduler.py`'s shape. `test_evidence_retention_v2.py` covers what
a pass purges and why; this file covers that a pass runs on schedule, that
it is safe to re-run, and that one bad pass does not end the schedule.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.evidence_retention_scheduler as evidence_retention_scheduler
from app.config import settings
from app.execution_models import (
    FileObject,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
    Task,
    TaskEvidence,
    TaskProgressUpdate,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project

ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class EvidenceRetentionScheduleTests(unittest.TestCase):
    def setUp(self):
        self.evidence_dir = tempfile.mkdtemp(prefix="siteops-retention-schedule-test-")
        self._original_evidence_dir = settings.evidence_upload_dir
        settings.evidence_upload_dir = self.evidence_dir

        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__,
            Task.__table__, TaskProgressUpdate.__table__, TaskEvidence.__table__, FileObject.__table__,
            # purge_expired_evidence always queries the gate-evidence join
            # path too (a project can have both kinds of evidence), so
            # these tables must exist even though this fixture seeds only
            # task evidence.
            ProjectExternalApproval.__table__, ProjectExternalApprovalSubmission.__table__,
            ProjectExternalApprovalEvidence.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self._session_patch = patch.object(evidence_retention_scheduler, "SessionLocal", self.Session)
        self._session_patch.start()
        self.addCleanup(self._session_patch.stop)

    def tearDown(self):
        self.engine.dispose()
        settings.evidence_upload_dir = self._original_evidence_dir
        shutil.rmtree(self.evidence_dir, ignore_errors=True)

    def _seed(self) -> None:
        self.file_path = Path(self.evidence_dir) / "expired-evidence.jpg"
        self.file_path.write_bytes(b"fake evidence bytes")

        with self.Session.begin() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.flush()

            self.project_id = uuid.uuid4()
            session.add(V2Project(
                id=self.project_id, code="P001", name="Project 1", client_name="Client",
                site_address="Somewhere", start_date=date(2026, 1, 1), status="completed",
                completed_at=datetime.now(timezone.utc) - timedelta(days=200),
                created_by=ADMIN_ID,
            ))
            session.flush()

            task = Task(
                project_id=self.project_id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Mobilise",
                schedule_classification="execution", applicability="mandatory",
                evidence_required=False, lifecycle_status="planned",
            )
            session.add(task)
            session.flush()

            update = TaskProgressUpdate(
                task_id=task.id, project_id=self.project_id, update_type="evidence",
                submitted_by=ADMIN_ID, source="portal",
            )
            session.add(update)
            session.flush()

            file_object = FileObject(
                storage_key="expired-evidence.jpg", original_filename="evidence.jpg",
                mime_type="image/jpeg", size_bytes=len(b"fake evidence bytes"),
                checksum="deadbeef", uploaded_by=ADMIN_ID,
            )
            session.add(file_object)
            session.flush()

            session.add(TaskEvidence(task_progress_update_id=update.id, file_id=file_object.id))

    # ---- the pass itself -------------------------------------------------

    def test_a_pass_purges_expired_evidence(self):
        self.assertTrue(self.file_path.is_file())
        purged = evidence_retention_scheduler.run_retention_pass()
        self.assertEqual(purged, 1)
        self.assertFalse(self.file_path.is_file())

    def test_a_second_pass_after_a_purge_is_a_safe_no_op(self):
        evidence_retention_scheduler.run_retention_pass()
        self.assertEqual(evidence_retention_scheduler.run_retention_pass(), 0)

    def test_a_pass_with_nothing_due_completes_without_error(self):
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).completed_at = datetime.now(timezone.utc)
        self.assertEqual(evidence_retention_scheduler.run_retention_pass(), 0)
        self.assertTrue(self.file_path.is_file())


class EvidenceRetentionLoopTests(unittest.IsolatedAsyncioTestCase):
    """The loop and its lifecycle, tested with an injected runner - no
    database, no wall-clock waiting on the real daily interval."""

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
                raise RuntimeError("disk exploded")
            return 0

        task = asyncio.create_task(evidence_retention_scheduler.retention_loop(0.001, runner=runner))
        await self._run_briefly(task, lambda: len(calls) >= 3)
        self.assertGreaterEqual(len(calls), 3)

    async def test_the_loop_sleeps_before_its_first_pass(self):
        calls = []
        task = asyncio.create_task(
            evidence_retention_scheduler.retention_loop(30.0, runner=lambda: calls.append(1)),
        )
        await asyncio.sleep(0.02)
        self.assertEqual(calls, [])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_the_dispatcher_does_not_start_when_disabled(self):
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(settings, "evidence_retention_enabled", False):
            started = evidence_retention_scheduler.start_retention_scheduler(app)
        self.assertFalse(started)
        self.assertIsNone(getattr(app.state, evidence_retention_scheduler.TASK_ATTRIBUTE, None))

    async def test_the_dispatcher_starts_and_stops_when_enabled(self):
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(settings, "evidence_retention_enabled", True), \
             patch.object(settings, "evidence_retention_interval_seconds", 86400.0):
            started = evidence_retention_scheduler.start_retention_scheduler(app)
            self.assertTrue(started)
            self.assertIsNotNone(getattr(app.state, evidence_retention_scheduler.TASK_ATTRIBUTE))
            await evidence_retention_scheduler.stop_retention_scheduler(app)
        self.assertIsNone(getattr(app.state, evidence_retention_scheduler.TASK_ATTRIBUTE))


class EvidenceRetentionWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_apps_lifespan_starts_and_stops_the_scheduler(self):
        # `main.py`'s startup/shutdown is a single `lifespan` context manager
        # (not per-feature `@app.on_event` handlers), so wiring is verified
        # by actually running it - `ensure_seed_data` is stubbed out since
        # it would otherwise open a real database connection.
        from app.main import create_app

        app = create_app()
        with patch("app.main.ensure_seed_data"):
            async with app.router.lifespan_context(app):
                self.assertIsNotNone(getattr(app.state, evidence_retention_scheduler.TASK_ATTRIBUTE, None))
            self.assertIsNone(getattr(app.state, evidence_retention_scheduler.TASK_ATTRIBUTE, None))

    def test_the_interval_and_switch_are_configurable_settings(self):
        self.assertIsInstance(settings.evidence_retention_enabled, bool)
        self.assertGreater(settings.evidence_retention_interval_seconds, 0)
        self.assertEqual(settings.evidence_retention_months, 6)


if __name__ == "__main__":
    unittest.main()
