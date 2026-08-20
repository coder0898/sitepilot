"""Plan Phase 3 (3c): external-approval status-check overlay.

Pins `ProjectGateStatusCheckService`:

- Assignee-exclusive - not even Admin/PM may record a status check on the
  assignee's behalf, mirroring `ProjectGateSubmissionService.
  _require_submitter` exactly.
- Never writes `ProjectExternalApproval.status` - purely additive, mirrors
  `TaskBlocker`'s BLOCKED-overlay decision applied to gates.
- An unknown `health` value is rejected (422).
- Append-only: two status checks for the same approval both persist.
- Each check emits `project_external_approval.status_checked`.

Follows the same lightweight service-level SQLite-ATTACHed-schema harness
pattern as `test_project_gate_submission_v2.py` (no full baseline-activation
flow needed - a `ProjectExternalApproval` row is seeded directly).
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
    ProjectExternalApprovalStatusCheck,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.project_gate_status_check import ProjectGateStatusCheckService


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
OTHER_INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
OUTSIDER_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")


class ProjectGateStatusCheckTests(unittest.TestCase):
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
            ProjectExternalApprovalStatusCheck.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._sequence = 0
        self._seed()
        self.db = self.Session()
        self.service = ProjectGateStatusCheckService(self.db)

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

    # ---- happy path ---------------------------------------------------------

    def test_the_assignee_can_record_a_status_check(self):
        approval = self.make_approval()
        check = self.service.record(self.project_id, approval.id, self.internal_user(), health="on_track", note="On schedule.")
        self.assertIsNotNone(check.id)
        self.assertEqual(check.health, "on_track")
        self.assertEqual(check.note, "On schedule.")
        self.assertEqual(check.recorded_by, INTERNAL_ID)

        # Never touches the approval's own status.
        self.assertEqual(self.stored(approval.id).status, "assigned")

        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == approval.id,
                    OutboxEvent.event_type == "project_external_approval.status_checked",
                )
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "project_external_approval")
            self.assertEqual(events[0].payload["health"], "on_track")

    # ---- access control -------------------------------------------------

    def test_a_different_internal_employee_cannot_record_a_status_check(self):
        approval = self.make_approval(assigned_to_user_id=INTERNAL_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.other_internal_user(), health="blocked")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_cannot_record_on_the_assignees_behalf(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.admin_user(), health="need_help")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_pm_cannot_record_a_status_check(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.pm_user(), health="on_track")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_member_cannot_record_a_status_check(self):
        approval = self.make_approval(assigned_to_user_id=OUTSIDER_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.outsider_user(), health="on_track")
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- validation -----------------------------------------------------

    def test_unknown_health_value_is_rejected(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.record(self.project_id, approval.id, self.internal_user(), health="at_risk")
        self.assertEqual(ctx.exception.status_code, 422)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(ProjectExternalApprovalStatusCheck).limit(1)), None)

    # ---- append-only ------------------------------------------------------

    def test_status_checks_are_append_only(self):
        approval = self.make_approval()
        first = self.service.record(self.project_id, approval.id, self.internal_user(), health="blocked", note="Waiting on inspector.")
        second = self.service.record(self.project_id, approval.id, self.internal_user(), health="on_track", note="Inspector visited.")

        self.assertNotEqual(first.id, second.id)

        with self.Session() as session:
            rows = session.scalars(
                select(ProjectExternalApprovalStatusCheck).where(ProjectExternalApprovalStatusCheck.approval_id == approval.id)
            ).all()
            self.assertEqual(len(rows), 2)
            healths = sorted(row.health for row in rows)
            self.assertEqual(healths, ["blocked", "on_track"])


if __name__ == "__main__":
    unittest.main()
