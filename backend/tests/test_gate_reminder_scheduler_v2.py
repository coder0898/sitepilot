"""Plan: WhatsApp Gate Workflow (U11).

Pins `run_gate_reminder_pass`'s fourth sweep, `expire_stale_evidence_sessions`
(`GateEvidenceSessionService.expire_stale_sessions`, U8): a stale evidence
session actually gets expired when the pass runs, a fresh one is left alone,
and this new sweep failing does not stop the three pre-existing approval
sweeps (`emit_gate_due_reminders`, `sweep_approval_followups`,
`sweep_approval_escalations`) from completing in the same pass - the same
per-call isolation `gate_reminder_scheduler.py`'s own docstring already
promises for those three.

Harness mirrors `test_gate_evidence_session_v2.py`'s table set (this pass's
new sweep touches the same tables that service's own tests already cover)
plus `EscalationTracking`, which the three pre-existing sweeps need to exist
even when empty.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.gate_reminder_scheduler as gate_reminder_scheduler
from app import template_models  # noqa: F401  - registers v2_template_* tables for V2Project's nullable FK.
from app.execution_models import (
    EscalationTracking,
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
from app.services.escalation import EscalationService
from app.services.project_gate_evidence_session import GateEvidenceSessionService


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class GateReminderPassEvidenceSweepTests(unittest.TestCase):
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
            EscalationTracking.__table__,
            GateEvidenceSession.__table__,
            GateEvidenceSessionAttachment.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        # `run_gate_reminder_pass` opens its own session from the app's
        # SessionLocal by design (see outbox_scheduler.py's own rationale) -
        # the harness swaps in its own sessionmaker rather than passing a
        # session in, matching `test_meeting_reminder_scheduler_v2.py`'s
        # identical patch.
        self._session_patch = patch.object(gate_reminder_scheduler, "SessionLocal", self.Session)
        self._session_patch.start()
        self.addCleanup(self._session_patch.stop)

        self._sequence = 0
        self._seed()

    def tearDown(self):
        self.engine.dispose()

    # ---- seeding ------------------------------------------------------------

    def _seed(self) -> None:
        with self.Session.begin() as session:
            session.add_all([
                User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True),
                User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True),
                User(
                    id=INTERNAL_ID, name="Internal", email="internal@example.com",
                    role=UserRole.internal_employee, active=True,
                ),
            ])
            session.flush()
            profiles = {
                PM_ID: EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                INTERNAL_ID: EmployeeProfile(
                    user_id=INTERNAL_ID, employee_code="INT-001", designation="Internal Employee",
                    availability="available",
                ),
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
            ):
                session.add(V2ProjectMembership(
                    project_id=self.project_id, employee_id=profiles[user_id].id,
                    project_role=project_role, assigned_by=ADMIN_ID,
                    assignment_reason="Seeded for tests.",
                ))

    def internal_user(self) -> User:
        return User(
            id=INTERNAL_ID, name="Internal", email="internal@example.com",
            role=UserRole.internal_employee, active=True,
        )

    def make_approval(self) -> ProjectExternalApproval:
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
            approval = ProjectExternalApproval(
                id=uuid.uuid4(), project_id=self.project_id, project_gate_id=gate.id,
                status="assigned",
                assigned_to_user_id=INTERNAL_ID,
                assigned_by=ADMIN_ID,
                assigned_at=datetime.now(timezone.utc),
            )
            session.add(approval)
            session.flush()
            approval_id = approval.id
        with self.Session() as session:
            return session.get(ProjectExternalApproval, approval_id)

    def make_session(self, approval_id, *, last_activity_at: datetime) -> uuid.UUID:
        """Inserts a `GateEvidenceSession` row directly, bypassing
        `open_session`'s access checks, so `last_activity_at` can be
        back-dated precisely - the same shortcut
        `test_gate_evidence_session_v2.py`'s own expiry tests use."""
        with self.Session.begin() as session:
            evidence_session = GateEvidenceSession(
                approval_id=approval_id, employee_id=INTERNAL_ID,
                note="Buffered, then abandoned.", last_activity_at=last_activity_at,
            )
            session.add(evidence_session)
            session.flush()
            return evidence_session.id

    def stored_session(self, session_id) -> GateEvidenceSession:
        with self.Session() as session:
            return session.get(GateEvidenceSession, session_id)

    # ---- a stale session is expired, freeing the employee's slot -----------

    def test_a_stale_session_is_expired_and_the_employee_can_open_a_new_one(self):
        """Covers AE3."""
        approval = self.make_approval()
        session_id = self.make_session(
            approval.id, last_activity_at=datetime.now(timezone.utc) - timedelta(days=6),
        )

        gate_reminder_scheduler.run_gate_reminder_pass()

        stored = self.stored_session(session_id)
        self.assertIsNotNone(stored.expired_at)
        self.assertIsNone(stored.closed_at)

        # The one-open-session slot is free again: opening a session for a
        # second gate now succeeds.
        second_approval = self.make_approval()
        with self.Session() as session:
            new_session = GateEvidenceSessionService(session).open_session(
                self.project_id, second_approval.id, self.internal_user(),
            )
            self.assertIsNotNone(new_session.id)
            self.assertIsNone(new_session.expired_at)

    # ---- a fresh session is left alone --------------------------------------

    def test_a_fresh_session_is_untouched(self):
        approval = self.make_approval()
        session_id = self.make_session(
            approval.id, last_activity_at=datetime.now(timezone.utc) - timedelta(days=2),
        )

        gate_reminder_scheduler.run_gate_reminder_pass()

        stored = self.stored_session(session_id)
        self.assertIsNone(stored.expired_at)
        self.assertIsNone(stored.closed_at)

    # ---- the new sweep failing does not block the other three ---------------

    def test_the_evidence_sweep_raising_does_not_stop_the_other_three_sweeps(self):
        with patch.object(
            GateEvidenceSessionService, "expire_stale_sessions", side_effect=RuntimeError("boom"),
        ), patch.object(
            EscalationService, "emit_gate_due_reminders", return_value=[],
        ) as due_reminders, patch.object(
            EscalationService, "sweep_approval_followups", return_value=[],
        ) as followups, patch.object(
            EscalationService, "sweep_approval_escalations", return_value=[],
        ) as escalations:
            # Must not raise: the failing fourth call is isolated the same
            # way the three pre-existing calls already isolate each other.
            gate_reminder_scheduler.run_gate_reminder_pass()

        due_reminders.assert_called_once()
        followups.assert_called_once()
        escalations.assert_called_once()


if __name__ == "__main__":
    unittest.main()
