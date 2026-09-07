"""Plan: WhatsApp Gate Workflow (U8, KTD4/KTD5-KTD9).

Pins `GateEvidenceSessionService`:

- `open_session` only succeeds against an `assigned` gate (KTD8, AE6), for
  the gate's own assignee, and enforces at most one open session per
  employee - both proactively (AE2) and via the partial unique index's
  `IntegrityError` on a lost race.
- `append_text`/`append_attachment` bump `last_activity_at`.
- `close_session` re-checks the assignee (KTD7, AE8), refuses an empty
  session (KTD9, AE7), and otherwise calls
  `ProjectGateSubmissionService.submit(existing_file_ids=...)` (KTD17) -
  never re-writing a session attachment's bytes to storage a second time.
- `expire_stale_sessions` discards (never submits) a session silent for
  `EVIDENCE_SESSION_SILENCE_DAYS`+ (KTD5/KTD6), committing per session.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import template_models  # noqa: F401  - registers v2_template_* tables for V2Project's nullable FK.
from app.execution_models import (
    FileObject,
    GateEvidenceSession,
    GateEvidenceSessionAttachment,
    OutboxEvent,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.project_gate_evidence_session import EVIDENCE_SESSION_SILENCE_DAYS, GateEvidenceSessionService
from app.services.project_gate_submission import ProjectGateSubmissionService


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
OTHER_INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")


class GateEvidenceSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectExternalGate.__table__,
            V2AuditEvent.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalSubmission.__table__,
            ProjectExternalApprovalEvidence.__table__,
            FileObject.__table__,
            OutboxEvent.__table__,
            GateEvidenceSession.__table__,
            GateEvidenceSessionAttachment.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._sequence = 0
        self._seed()
        self.db = self.Session()
        self.service = GateEvidenceSessionService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # ---- actors -----------------------------------------------------------

    def admin_user(self) -> User:
        return User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)

    def pm_user(self) -> User:
        return User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)

    def internal_user(self) -> User:
        return User(
            id=INTERNAL_ID, name="Internal", email="internal@example.com",
            role=UserRole.internal_employee, active=True,
        )

    def other_internal_user(self) -> User:
        return User(
            id=OTHER_INTERNAL_ID, name="Other Internal", email="other@example.com",
            role=UserRole.internal_employee, active=True,
        )

    # ---- seeding ------------------------------------------------------------

    def _seed(self) -> None:
        with self.Session.begin() as session:
            session.add_all([
                self.admin_user(), self.pm_user(), self.internal_user(), self.other_internal_user(),
            ])
            session.flush()
            profiles = {
                PM_ID: EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                INTERNAL_ID: EmployeeProfile(user_id=INTERNAL_ID, employee_code="INT-001", designation="Internal Employee", availability="available"),
                OTHER_INTERNAL_ID: EmployeeProfile(user_id=OTHER_INTERNAL_ID, employee_code="INT-002", designation="Internal Employee", availability="available"),
            }
            session.add_all(profiles.values())
            session.flush()

            self.project_id = uuid.uuid4()
            session.add(V2Project(
                id=self.project_id, code="P001", name="Project 1", client_name="Client",
                site_address="Somewhere", start_date=date(2026, 8, 1), status="active",
                created_by=ADMIN_ID,
            ))
            session.flush()

            for user_id, project_role in (
                (PM_ID, "project_manager"),
                (INTERNAL_ID, "internal_employee"),
                (OTHER_INTERNAL_ID, "internal_employee"),
            ):
                session.add(V2ProjectMembership(
                    project_id=self.project_id, employee_id=profiles[user_id].id,
                    project_role=project_role, assigned_by=ADMIN_ID,
                    assignment_reason="Seeded for tests.",
                ))

    def make_approval(self, *, status: str = "assigned", assigned_to_user_id=INTERNAL_ID) -> ProjectExternalApproval:
        with self.Session.begin() as session:
            self._sequence += 1
            gate = V2ProjectExternalGate(
                id=uuid.uuid4(), project_id=self.project_id,
                original_code=f"E{self._sequence:03d}", template_sequence=self._sequence,
                approval_name=f"Fire NOC {self._sequence}", mapping_classification="exact",
                applicability_state="applicable", blocking=True,
                accountable_pm_user_id=PM_ID, source_type="project_manual",
            )
            session.add(gate)
            session.flush()
            decided = status in ("approved", "rejected")
            approval = ProjectExternalApproval(
                id=uuid.uuid4(), project_id=self.project_id, project_gate_id=gate.id,
                status=status,
                assigned_to_user_id=assigned_to_user_id,
                assigned_by=ADMIN_ID if assigned_to_user_id else None,
                assigned_at=datetime.now(timezone.utc) if assigned_to_user_id else None,
                decided_by=ADMIN_ID if decided else None,
                decided_at=datetime.now(timezone.utc) if decided else None,
            )
            session.add(approval)
            session.flush()
            approval_id = approval.id
        return self.db.get(ProjectExternalApproval, approval_id)

    def make_file_object(self, *, mime_type: str = "image/jpeg") -> FileObject:
        """Simulates a `FileObject` U10 already wrote for a downloaded
        WhatsApp attachment - GateEvidenceSessionService never writes bytes
        itself."""
        file_object = FileObject(
            storage_key=f"gate-evidence-session-{uuid.uuid4().hex}.jpg",
            original_filename="photo.jpg",
            mime_type=mime_type,
            size_bytes=1024,
            checksum=uuid.uuid4().hex,
            uploaded_by=INTERNAL_ID,
        )
        self.db.add(file_object)
        self.db.flush()
        return file_object

    @staticmethod
    def _aware(dt: datetime) -> datetime:
        """SQLite round-trips a `DateTime(timezone=True)` column as naive -
        normalises to an aware UTC value so before/after comparisons never
        raise on a naive/aware mismatch."""
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    def stored_session(self, session_id) -> GateEvidenceSession:
        with self.Session() as session:
            return session.get(GateEvidenceSession, session_id)

    def all_sessions(self) -> list[GateEvidenceSession]:
        with self.Session() as session:
            return list(session.scalars(select(GateEvidenceSession)))

    def all_file_objects(self) -> list[FileObject]:
        with self.Session() as session:
            return list(session.scalars(select(FileObject)))

    # ---- open_session -------------------------------------------------------

    def test_opening_a_session_against_an_assigned_gate_succeeds(self):
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.assertIsNotNone(session.id)
        self.assertEqual(session.approval_id, approval.id)
        self.assertEqual(session.employee_id, INTERNAL_ID)
        self.assertIsNone(session.closed_at)
        self.assertIsNone(session.expired_at)

    def test_opening_a_session_against_a_submitted_gate_is_rejected(self):
        """Covers AE6/KTD8."""
        approval = self.make_approval(status="submitted")
        with self.assertRaises(HTTPException) as ctx:
            self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(len(self.all_sessions()), 0)

    def test_opening_a_session_against_an_approved_gate_is_rejected(self):
        approval = self.make_approval(status="approved")
        with self.assertRaises(HTTPException) as ctx:
            self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(len(self.all_sessions()), 0)

    def test_opening_a_session_against_a_rejected_gate_is_rejected(self):
        approval = self.make_approval(status="rejected")
        with self.assertRaises(HTTPException) as ctx:
            self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(len(self.all_sessions()), 0)

    def test_opening_a_session_against_an_unassigned_gate_is_rejected(self):
        approval = self.make_approval(status="unassigned", assigned_to_user_id=None)
        with self.assertRaises(HTTPException):
            self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.assertEqual(len(self.all_sessions()), 0)

    def test_opening_a_session_as_a_non_assignee_is_rejected(self):
        approval = self.make_approval(status="assigned", assigned_to_user_id=INTERNAL_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.open_session(self.project_id, approval.id, self.other_internal_user())
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(len(self.all_sessions()), 0)

    def test_opening_a_second_session_while_one_is_open_is_rejected(self):
        """Covers AE2."""
        approval_a = self.make_approval(status="assigned")
        approval_b = self.make_approval(status="assigned")
        self.service.open_session(self.project_id, approval_a.id, self.internal_user())
        with self.assertRaises(HTTPException) as ctx:
            self.service.open_session(self.project_id, approval_b.id, self.internal_user())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("already have an open evidence session", ctx.exception.detail)
        self.assertEqual(len(self.all_sessions()), 1)

    def test_concurrent_open_session_calls_result_in_exactly_one_session(self):
        """Simulates two `open_session` calls for the same employee both
        passing the proactive check before either commits - the partial
        unique index's `IntegrityError` on the second commit must be
        converted to the same friendly rejection, not an unhandled crash."""
        approval_a = self.make_approval(status="assigned")
        approval_b = self.make_approval(status="assigned")
        with patch.object(GateEvidenceSessionService, "_has_open_session", return_value=False):
            first = self.service.open_session(self.project_id, approval_a.id, self.internal_user())
            with self.assertRaises(HTTPException) as ctx:
                self.service.open_session(self.project_id, approval_b.id, self.internal_user())
        self.assertEqual(ctx.exception.status_code, 409)
        sessions = self.all_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, first.id)

    # ---- append -------------------------------------------------------------

    def test_appending_text_bumps_last_activity_at(self):
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        earlier = self._aware(session.last_activity_at) - timedelta(hours=1)
        session.last_activity_at = earlier
        self.db.add(session)
        self.db.flush()
        self.service.append_text(session, "NOC document attached.")
        self.assertEqual(session.note, "NOC document attached.")
        self.assertGreater(self._aware(session.last_activity_at), earlier)

    def test_appending_text_twice_joins_with_a_newline(self):
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.service.append_text(session, "First line.")
        self.service.append_text(session, "Second line.")
        self.assertEqual(session.note, "First line.\nSecond line.")

    def test_appending_an_attachment_bumps_last_activity_at(self):
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        earlier = self._aware(session.last_activity_at) - timedelta(hours=1)
        session.last_activity_at = earlier
        self.db.add(session)
        self.db.flush()
        file_object = self.make_file_object()
        self.service.append_attachment(session, file_object)
        self.assertGreater(self._aware(session.last_activity_at), earlier)
        # Read via the same still-open session (not a fresh `Session()`) -
        # this session's writes are only flush()ed, not committed, and a
        # second Session on this shared-connection SQLite test harness
        # would roll them back the moment it closes.
        attachments = list(self.db.scalars(
            select(GateEvidenceSessionAttachment).where(GateEvidenceSessionAttachment.session_id == session.id)
        ))
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].file_id, file_object.id)

    # ---- close_session --------------------------------------------------------

    def test_closing_with_a_note_and_no_attachments_succeeds(self):
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.service.append_text(session, "NOC document attached.")
        submission = self.service.close_session(self.project_id, session, self.internal_user())
        self.assertIsNotNone(submission.id)
        self.assertEqual(submission.note, "NOC document attached.")
        self.assertIsNotNone(self.stored_session(session.id).closed_at)

    def test_closing_with_two_attachments_and_no_note_submits_both_and_writes_no_new_file_objects(self):
        """Covers KTD17: confirms the double-write is actually eliminated -
        exactly the session's own `FileObject` rows are linked, and no new
        ones are created."""
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        file_a = self.make_file_object()
        file_b = self.make_file_object()
        self.service.append_attachment(session, file_a)
        self.service.append_attachment(session, file_b)
        # Read via the same still-open self.db (not a fresh `Session()`) -
        # the two FileObjects above are only flush()ed, not committed yet.
        self.assertEqual(len(list(self.db.scalars(select(FileObject)))), 2)

        submission = self.service.close_session(self.project_id, session, self.internal_user())

        self.assertEqual(len(self.all_file_objects()), 2, "no new FileObject rows should be created on close")
        with self.Session() as db_session:
            evidence = list(db_session.scalars(
                select(ProjectExternalApprovalEvidence).where(ProjectExternalApprovalEvidence.submission_id == submission.id)
            ))
            self.assertEqual(len(evidence), 2)
            self.assertEqual({row.file_id for row in evidence}, {file_a.id, file_b.id})
        self.assertIsNotNone(self.stored_session(session.id).closed_at)

    def test_closing_an_empty_session_is_rejected(self):
        """Covers AE7/KTD9."""
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        with self.assertRaises(HTTPException) as ctx:
            self.service.close_session(self.project_id, session, self.internal_user())
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIsNone(self.stored_session(session.id).closed_at)

    def test_closing_as_a_user_no_longer_the_assignee_is_rejected(self):
        """Covers AE8/KTD7."""
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.service.append_text(session, "NOC document attached.")

        # Simulate a mid-session reassignment away from the original assignee.
        row = self.db.get(ProjectExternalApproval, approval.id)
        row.assigned_to_user_id = OTHER_INTERNAL_ID
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            self.service.close_session(self.project_id, session, self.internal_user())
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIsNone(self.stored_session(session.id).closed_at)
        with self.Session() as db_session:
            submissions = list(db_session.scalars(select(ProjectExternalApprovalSubmission)))
            self.assertEqual(len(submissions), 0)

    # ---- expire_stale_sessions ------------------------------------------------

    def test_expire_stale_sessions_expires_a_six_day_stale_session_without_calling_submit(self):
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        self.service.append_text(session, "Buffered, then abandoned.")
        session.last_activity_at = datetime.now(timezone.utc) - timedelta(days=6)
        self.db.add(session)
        self.db.commit()

        now = datetime.now(timezone.utc)
        with patch.object(ProjectGateSubmissionService, "submit") as mock_submit:
            expired = self.service.expire_stale_sessions(now)
            mock_submit.assert_not_called()

        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0].id, session.id)
        stored = self.stored_session(session.id)
        self.assertIsNotNone(stored.expired_at)
        self.assertIsNone(stored.closed_at)
        with self.Session() as db_session:
            submissions = list(db_session.scalars(select(ProjectExternalApprovalSubmission)))
            self.assertEqual(len(submissions), 0)

    def test_expire_stale_sessions_does_not_touch_a_two_day_old_session(self):
        approval = self.make_approval(status="assigned")
        session = self.service.open_session(self.project_id, approval.id, self.internal_user())
        session.last_activity_at = datetime.now(timezone.utc) - timedelta(days=2)
        self.db.add(session)
        self.db.commit()

        expired = self.service.expire_stale_sessions(datetime.now(timezone.utc))

        self.assertEqual(expired, [])
        stored = self.stored_session(session.id)
        self.assertIsNone(stored.expired_at)
        self.assertIsNone(stored.closed_at)

    def test_evidence_session_silence_days_constant_is_five(self):
        """Pins KTD5's concrete number."""
        self.assertEqual(EVIDENCE_SESSION_SILENCE_DAYS, 5)


if __name__ == "__main__":
    unittest.main()
