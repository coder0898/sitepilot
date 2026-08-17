"""Plan: External Approval Gate Assignment & Evidence Lifecycle (U4).

Pins `ProjectGateSubmissionService`:

- Only the assignee can submit - not Admin, not PM, no fallback (unlike
  decision authority).
- Submission only fires from `assigned` - covers both a first submission and
  a resubmission after rejection, since decide() (U5) loops rejection back
  to `assigned` rather than ending it there.
- Evidence bytes land on disk under `settings.evidence_upload_dir`, never a
  public URL - `get_evidence_file` re-checks project access AND scopes the
  file through this approval's own submissions, so a file_id from a
  different approval/project can never be substituted (R7, the IDOR fix
  from doc review).
- Each submission writes a `V2AuditEvent` and emits an outbox event.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException
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
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.project_gate_submission import ProjectGateSubmissionService


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
OTHER_INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")

TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


class ProjectGateSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.evidence_dir = tempfile.mkdtemp(prefix="siteops-gate-evidence-test-")
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
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._sequence = 0
        self._seed()
        self.db = self.Session()
        self.service = ProjectGateSubmissionService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        settings.evidence_upload_dir = self._original_evidence_dir
        shutil.rmtree(self.evidence_dir, ignore_errors=True)

    # ---- actors ---------------------------------------------------------

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

    # ---- seeding --------------------------------------------------------

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

    def make_approval(self, *, status: str = "assigned", assigned_to_user_id=INTERNAL_ID, project_id=None) -> ProjectExternalApproval:
        project_id = project_id or self.project_id
        with self.Session.begin() as session:
            self._sequence += 1
            gate = V2ProjectExternalGate(
                id=uuid.uuid4(), project_id=project_id,
                original_code=f"E{self._sequence:03d}", template_sequence=self._sequence,
                approval_name=f"Fire NOC {self._sequence}", mapping_classification="exact",
                applicability_state="applicable", blocking=True,
                accountable_pm_user_id=PM_ID, source_type="project_manual",
            )
            session.add(gate)
            session.flush()
            decided = status in ("approved", "rejected")
            approval = ProjectExternalApproval(
                id=uuid.uuid4(), project_id=project_id, project_gate_id=gate.id,
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

    def stored(self, approval_id) -> ProjectExternalApproval:
        with self.Session() as session:
            return session.get(ProjectExternalApproval, approval_id)

    # ---- who may submit ---------------------------------------------------

    def test_the_assignee_can_submit_a_note(self):
        approval = self.make_approval()
        submission = self.service.submit(
            self.project_id, approval.id, self.internal_user(), note="NOC document attached.", files=[],
        )
        self.assertIsNotNone(submission.id)
        self.assertEqual(self.stored(approval.id).status, "submitted")

    def test_a_different_internal_employee_cannot_submit(self):
        approval = self.make_approval(assigned_to_user_id=INTERNAL_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.submit(self.project_id, approval.id, self.other_internal_user(), note="Not mine.", files=[])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_cannot_submit_on_the_assignees_behalf(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.submit(self.project_id, approval.id, self.admin_user(), note="On their behalf.", files=[])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_pm_cannot_submit(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.submit(self.project_id, approval.id, self.pm_user(), note="Not mine either.", files=[])
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- state ------------------------------------------------------------

    def test_submitting_an_unassigned_gate_is_refused(self):
        approval = self.make_approval(status="unassigned", assigned_to_user_id=None)
        with self.assertRaises(HTTPException) as ctx:
            self.service.submit(self.project_id, approval.id, self.internal_user(), note="Too early.", files=[])
        self.assertEqual(ctx.exception.status_code, 403)  # assignee check fails first (no assignee set)

    def test_submitting_an_already_submitted_gate_is_refused(self):
        approval = self.make_approval(status="submitted")
        with self.assertRaises(HTTPException) as ctx:
            self.service.submit(self.project_id, approval.id, self.internal_user(), note="Again.", files=[])
        self.assertEqual(ctx.exception.status_code, 409)

    def test_a_resubmission_after_rejection_succeeds(self):
        """decide() (U5) loops a rejected gate back to `assigned` - the same
        assignee must be able to submit again from that state."""
        approval = self.make_approval(status="assigned")
        first = self.service.submit(self.project_id, approval.id, self.internal_user(), note="First try.", files=[])
        # Simulate U5's reject transition landing the row back on 'assigned',
        # via the service's own session so its identity map sees the change
        # (a separate session's write wouldn't be visible without a refresh).
        row = self.db.get(ProjectExternalApproval, approval.id)
        row.status = "assigned"
        row.rejection_reason = "Missing signature page."
        self.db.commit()
        second = self.service.submit(self.project_id, approval.id, self.internal_user(), note="Fixed.", files=[])
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(self.stored(approval.id).status, "submitted")
        with self.Session() as session:
            submissions = session.scalars(
                select(ProjectExternalApprovalSubmission).where(ProjectExternalApprovalSubmission.approval_id == approval.id)
            ).all()
            self.assertEqual(len(submissions), 2, "append-only: the first (rejected) submission is retained")

    def test_a_submission_requires_a_note_evidence_or_both(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.submit(self.project_id, approval.id, self.internal_user(), note=None, files=[])
        self.assertEqual(ctx.exception.status_code, 422)

    # ---- evidence -----------------------------------------------------------

    def test_a_valid_image_is_stored_and_linked(self):
        approval = self.make_approval()
        submission = self.service.submit(
            self.project_id, approval.id, self.internal_user(), note=None,
            files=[(TINY_PNG_BYTES, "noc.png", "image/png")],
        )
        with self.Session() as session:
            evidence = session.scalars(
                select(ProjectExternalApprovalEvidence).where(ProjectExternalApprovalEvidence.submission_id == submission.id)
            ).all()
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0].evidence_type, "photo")

    def test_multiple_evidence_files_in_one_submission(self):
        approval = self.make_approval()
        submission = self.service.submit(
            self.project_id, approval.id, self.internal_user(), note="Two files.",
            files=[(TINY_PNG_BYTES, "a.png", "image/png"), (TINY_PNG_BYTES, "b.png", "image/png")],
        )
        with self.Session() as session:
            evidence = session.scalars(
                select(ProjectExternalApprovalEvidence).where(ProjectExternalApprovalEvidence.submission_id == submission.id)
            ).all()
            self.assertEqual(len(evidence), 2)

    def test_a_disallowed_mime_type_is_refused(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.submit(
                self.project_id, approval.id, self.internal_user(), note=None,
                files=[(b"not-a-real-video", "clip.mp4", "video/mp4")],
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_an_oversized_file_is_refused(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.submit(
                self.project_id, approval.id, self.internal_user(), note=None,
                files=[(b"x" * (10 * 1024 * 1024 + 1), "big.png", "image/png")],
            )
        self.assertEqual(ctx.exception.status_code, 422)

    # ---- side effects -------------------------------------------------------

    def test_a_submission_writes_an_audit_event_and_emits_an_outbox_event(self):
        approval = self.make_approval()
        self.service.submit(self.project_id, approval.id, self.internal_user(), note="Attached.", files=[])
        with self.Session() as session:
            audit = session.scalars(select(V2AuditEvent).where(V2AuditEvent.entity_id == approval.id)).all()
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit[0].action, "PROJECT_EXTERNAL_APPROVAL_SUBMITTED")
            events = session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == approval.id)).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "project_external_approval.submitted")

    # ---- evidence download / IDOR scoping ------------------------------------

    def test_get_evidence_file_returns_bytes_for_a_project_member(self):
        approval = self.make_approval()
        self.service.submit(
            self.project_id, approval.id, self.internal_user(), note=None,
            files=[(TINY_PNG_BYTES, "noc.png", "image/png")],
        )
        with self.Session() as session:
            evidence = session.scalars(select(ProjectExternalApprovalEvidence)).all()[0]
        file_object, content = self.service.get_evidence_file(
            self.project_id, approval.id, evidence.file_id, self.pm_user(),
        )
        self.assertEqual(content, TINY_PNG_BYTES)
        self.assertEqual(file_object.original_filename, "noc.png")

    def test_get_evidence_file_refuses_a_file_id_from_a_different_approval(self):
        """IDOR regression: a file attached to one approval must not be
        readable through a different approval_id in the URL, even within
        the same project."""
        approval_a = self.make_approval()
        approval_b = self.make_approval()
        self.service.submit(
            self.project_id, approval_a.id, self.internal_user(), note=None,
            files=[(TINY_PNG_BYTES, "a-noc.png", "image/png")],
        )
        with self.Session() as session:
            evidence = session.scalars(select(ProjectExternalApprovalEvidence)).all()[0]
        with self.assertRaises(HTTPException) as ctx:
            self.service.get_evidence_file(self.project_id, approval_b.id, evidence.file_id, self.pm_user())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_evidence_file_refuses_a_non_member(self):
        approval = self.make_approval()
        self.service.submit(
            self.project_id, approval.id, self.internal_user(), note=None,
            files=[(TINY_PNG_BYTES, "noc.png", "image/png")],
        )
        with self.Session() as session:
            evidence = session.scalars(select(ProjectExternalApprovalEvidence)).all()[0]
        outsider = User(id=uuid.uuid4(), name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True)
        with self.assertRaises(HTTPException) as ctx:
            self.service.get_evidence_file(self.project_id, approval.id, evidence.file_id, outsider)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
