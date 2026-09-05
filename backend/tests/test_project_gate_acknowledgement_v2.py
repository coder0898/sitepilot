"""Plan (U5): gate acknowledgement overlay.

Pins `ProjectGateAcknowledgementService`:

- Assignee-exclusive - not even Admin/PM may record an acknowledgement on
  the assignee's behalf, mirroring `ProjectGateSubmissionService.
  _require_submitter` exactly.
- Never writes `ProjectExternalApproval.status` - purely additive, mirrors
  `ProjectExternalApprovalStatusCheck`'s non-lifecycle overlay decision
  applied to gates.
- An unknown `response` value is rejected (422).
- Append-only: two acknowledgements for the same approval both persist,
  mirroring `VendorAcknowledgement`'s own precedent.
- Each recording emits `project_external_approval.accepted` or
  `project_external_approval.declined`.

Follows the same lightweight service-level SQLite-ATTACHed-schema harness
pattern as `test_project_gate_status_check_v2.py` (no full baseline-
activation flow needed - a `ProjectExternalApproval` row is seeded
directly).
"""

from __future__ import annotations

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
from app.execution_models import (
    OutboxEvent,
    ProjectExternalApproval,
    ProjectGateAcknowledgement,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.project_gate_acknowledgement import ProjectGateAcknowledgementService

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
OTHER_INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
OUTSIDER_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")


class ProjectGateAcknowledgementTests(unittest.TestCase):
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
            ProjectGateAcknowledgement.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._sequence = 0
        self._seed()
        self.db = self.Session()
        self.service = ProjectGateAcknowledgementService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

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

    def outsider_user(self) -> User:
        return User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
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

    # ---- happy path -------------------------------------------------------

    def test_the_assignee_can_record_an_accepted_acknowledgement(self):
        approval = self.make_approval()
        ack = self.service.record(self.project_id, approval.id, self.internal_user(), response="accepted", note="Confirmed.")
        self.assertIsNotNone(ack.id)
        self.assertEqual(ack.response, "accepted")
        self.assertEqual(ack.note, "Confirmed.")
        self.assertEqual(ack.recorded_by, INTERNAL_ID)

        # Never touches the approval's own status.
        self.assertEqual(self.stored(approval.id).status, "assigned")

        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == approval.id,
                    OutboxEvent.event_type == "project_external_approval.accepted",
                )
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "project_external_approval")
            self.assertEqual(events[0].payload["response"], "accepted")

    def test_the_assignee_can_record_a_declined_acknowledgement(self):
        approval = self.make_approval()
        ack = self.service.record(self.project_id, approval.id, self.internal_user(), response="declined", note="Not ready.")
        self.assertEqual(ack.response, "declined")

        # Never touches the approval's own status.
        self.assertEqual(self.stored(approval.id).status, "assigned")

        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == approval.id,
                    OutboxEvent.event_type == "project_external_approval.declined",
                )
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].payload["response"], "declined")

    # ---- access control -----------------------------------------------------

    def test_a_different_internal_employee_cannot_record_an_acknowledgement(self):
        approval = self.make_approval(assigned_to_user_id=INTERNAL_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.other_internal_user(), response="accepted")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_cannot_record_on_the_assignees_behalf(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.admin_user(), response="accepted")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_pm_cannot_record_an_acknowledgement(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.pm_user(), response="declined")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_member_cannot_record_an_acknowledgement(self):
        approval = self.make_approval(assigned_to_user_id=OUTSIDER_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.outsider_user(), response="accepted")
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- validation ---------------------------------------------------------

    def test_unknown_response_value_is_rejected(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.internal_user(), response="maybe")
        self.assertEqual(ctx.exception.status_code, 422)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(ProjectGateAcknowledgement).limit(1)), None)

    # ---- append-only ----------------------------------------------------

    def test_acknowledgements_are_append_only(self):
        approval = self.make_approval()
        first = self.service.record(self.project_id, approval.id, self.internal_user(), response="declined", note="Need more time.")
        second = self.service.record(self.project_id, approval.id, self.internal_user(), response="accepted", note="Ready now.")

        self.assertNotEqual(first.id, second.id)

        with self.Session() as session:
            rows = session.scalars(
                select(ProjectGateAcknowledgement).where(ProjectGateAcknowledgement.approval_id == approval.id)
            ).all()
            self.assertEqual(len(rows), 2)
            responses = sorted(row.response for row in rows)
            self.assertEqual(responses, ["accepted", "declined"])

        # Never touches the approval's own status, across either response.
        self.assertEqual(self.stored(approval.id).status, "assigned")


if __name__ == "__main__":
    unittest.main()
