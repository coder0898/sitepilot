"""app.services.evidence_retention: 6-month-post-completion evidence purge.

Uses the real `TaskProgressService.submit_progress` / `ProjectGateSubmission
Service.submit` paths to create evidence, so what is under test is the
actual on-disk files those units write in production - not a hand-built
`FileObject` row that might not match what they actually produce.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import template_models  # noqa: F401  - registers v2_template_* tables for V2Project's nullable FK.
from app.config import settings
from app.execution_models import (
    FileObject,
    OutboxEvent,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
    Task,
    TaskEvidence,
    TaskProgressUpdate,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.evidence_retention import purge_expired_evidence
from app.services.project_gate_submission import ProjectGateSubmissionService
from app.services.task_progress import TaskProgressService


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")

TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


class EvidenceRetentionSweepTests(unittest.TestCase):
    def setUp(self):
        self.evidence_dir = tempfile.mkdtemp(prefix="siteops-retention-test-")
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
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__, EmployeeProfile.__table__,
            V2Project.__table__, V2ProjectMembership.__table__, V2ProjectExternalGate.__table__,
            V2AuditEvent.__table__,
            ProjectExternalApproval.__table__, ProjectExternalApprovalSubmission.__table__,
            ProjectExternalApprovalEvidence.__table__,
            Task.__table__, TaskProgressUpdate.__table__, TaskEvidence.__table__,
            FileObject.__table__, OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._sequence = 0
        self._seed()

    def tearDown(self):
        self.engine.dispose()
        settings.evidence_upload_dir = self._original_evidence_dir
        shutil.rmtree(self.evidence_dir, ignore_errors=True)

    def admin_user(self) -> User:
        return User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)

    def internal_user(self) -> User:
        return User(id=INTERNAL_ID, name="Internal", email="internal@example.com", role=UserRole.internal_employee, active=True)

    def _seed(self) -> None:
        with self.Session.begin() as session:
            session.add_all([self.admin_user(), self.internal_user()])
            session.flush()
            self.internal_employee = EmployeeProfile(
                user_id=INTERNAL_ID, employee_code="INT-001", designation="Internal Employee", availability="available",
            )
            session.add(self.internal_employee)
            session.flush()

            self.project_id = uuid.uuid4()
            session.add(V2Project(
                id=self.project_id, code="P001", name="Project 1", client_name="Client",
                site_address="Somewhere", start_date=date(2026, 1, 1), status="completed",
                created_by=ADMIN_ID,
            ))
            session.add(V2ProjectMembership(
                project_id=self.project_id, employee_id=self.internal_employee.id,
                project_role="internal_employee", assigned_by=ADMIN_ID, assignment_reason="Seeded for tests.",
            ))
            session.flush()

            self.task = Task(
                project_id=self.project_id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Mobilise",
                schedule_classification="execution", applicability="mandatory",
                evidence_required=False, lifecycle_status="planned",
            )
            session.add(self.task)
            session.flush()
            self.task_id = self.task.id

    def _set_completed_at(self, when: datetime | None) -> None:
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).completed_at = when

    def _submit_task_evidence(self) -> FileObject:
        db = self.Session()
        try:
            update = TaskProgressService(db).submit_progress(
                self.project_id, self.task_id, self.admin_user(), note="Evidence.",
                evidence_bytes=TINY_PNG_BYTES, evidence_filename="proof.png", evidence_content_type="image/png",
            )
            evidence = db.scalar(select(TaskEvidence).where(TaskEvidence.task_progress_update_id == update.id))
            return db.get(FileObject, evidence.file_id)
        finally:
            db.close()

    def _make_gate_with_evidence(self) -> FileObject:
        with self.Session.begin() as session:
            self._sequence += 1
            gate = V2ProjectExternalGate(
                id=uuid.uuid4(), project_id=self.project_id,
                original_code=f"E{self._sequence:03d}", template_sequence=self._sequence,
                approval_name=f"Fire NOC {self._sequence}", mapping_classification="exact",
                applicability_state="applicable", blocking=True,
                accountable_pm_user_id=ADMIN_ID, source_type="project_manual",
            )
            session.add(gate)
            session.flush()
            approval = ProjectExternalApproval(
                id=uuid.uuid4(), project_id=self.project_id, project_gate_id=gate.id,
                status="assigned", assigned_to_user_id=INTERNAL_ID, assigned_by=ADMIN_ID,
                assigned_at=datetime.now(timezone.utc),
            )
            session.add(approval)
            session.flush()
            approval_id = approval.id

        db = self.Session()
        try:
            submission = ProjectGateSubmissionService(db).submit(
                self.project_id, approval_id, self.internal_user(), note="NOC.",
                files=[(TINY_PNG_BYTES, "noc.png", "image/png")],
            )
            evidence = db.scalar(
                select(ProjectExternalApprovalEvidence).where(ProjectExternalApprovalEvidence.submission_id == submission.id)
            )
            return db.get(FileObject, evidence.file_id)
        finally:
            db.close()

    # ---- tests -------------------------------------------------------

    def test_evidence_past_the_retention_window_is_purged(self):
        file_object = self._submit_task_evidence()
        file_path = Path(self.evidence_dir) / file_object.storage_key
        self.assertTrue(file_path.is_file())

        self._set_completed_at(datetime.now(timezone.utc) - timedelta(days=200))

        db = self.Session()
        self.assertEqual(purge_expired_evidence(db, retention_months=6), 1)
        self.assertFalse(file_path.is_file())

        # The record survives - only the bytes are gone, so
        # get_evidence_file's existing is_file() check answers "no longer
        # available" for it with no route change.
        self.assertIsNotNone(db.get(FileObject, file_object.id))
        self.assertIsNotNone(db.get(V2Project, self.project_id).evidence_purged_at)

    def test_evidence_inside_the_retention_window_is_left_alone(self):
        file_object = self._submit_task_evidence()
        file_path = Path(self.evidence_dir) / file_object.storage_key

        self._set_completed_at(datetime.now(timezone.utc) - timedelta(days=30))

        db = self.Session()
        self.assertEqual(purge_expired_evidence(db, retention_months=6), 0)
        self.assertTrue(file_path.is_file())

    def test_a_project_never_marked_complete_is_never_swept(self):
        # completed_at is None - the exact protection a delayed project (one
        # that overran target_handover_date but was never actually marked
        # 'completed') relies on.
        file_object = self._submit_task_evidence()
        file_path = Path(self.evidence_dir) / file_object.storage_key

        db = self.Session()
        self.assertEqual(purge_expired_evidence(db, retention_months=6), 0)
        self.assertTrue(file_path.is_file())

    def test_an_active_project_is_never_swept_even_with_a_stale_completed_at(self):
        file_object = self._submit_task_evidence()
        file_path = Path(self.evidence_dir) / file_object.storage_key
        self._set_completed_at(datetime.now(timezone.utc) - timedelta(days=200))
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "active"

        db = self.Session()
        self.assertEqual(purge_expired_evidence(db, retention_months=6), 0)
        self.assertTrue(file_path.is_file())

    def test_gate_evidence_is_covered_by_the_sweep_too(self):
        file_object = self._make_gate_with_evidence()
        file_path = Path(self.evidence_dir) / file_object.storage_key
        self.assertTrue(file_path.is_file())

        self._set_completed_at(datetime.now(timezone.utc) - timedelta(days=200))

        db = self.Session()
        self.assertEqual(purge_expired_evidence(db, retention_months=6), 1)
        self.assertFalse(file_path.is_file())

    def test_an_already_purged_project_is_not_rescanned(self):
        self._submit_task_evidence()
        self._set_completed_at(datetime.now(timezone.utc) - timedelta(days=200))

        db = self.Session()
        self.assertEqual(purge_expired_evidence(db, retention_months=6), 1)
        self.assertEqual(purge_expired_evidence(db, retention_months=6), 0)


if __name__ == "__main__":
    unittest.main()
