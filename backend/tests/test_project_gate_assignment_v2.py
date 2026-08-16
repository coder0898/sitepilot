"""Plan: External Approval Gate Assignment & Evidence Lifecycle (U3).

Pins `ProjectGateAssignmentService`:

- Assignment, reassignment, and unassignment are all Admin-only - no
  PM-fallback tier, a deliberate divergence from the task pattern (R1/R3/R6).
- `assign()` only fires from `unassigned`; `reassign()`/`unassign()` only
  fire from `assigned`/`submitted` - each raises 409 outside its own state.
- The assignee must be an active Internal Employee project member.
- Each write records a `V2AuditEvent` and emits an outbox event.

Tested directly against the service (not through HTTP) since the assign/
reassign/unassign routes are wired in U5, not this unit.
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

from app import template_models  # noqa: F401  - registers v2_template_* tables on Base.metadata so V2Project's (unused, nullable) template_version_id FK can resolve at table.create() time.
from app.execution_models import OutboxEvent, ProjectExternalApproval
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.project_gate_assignment import ProjectGateAssignmentService


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
OTHER_INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
OUTSIDER_INTERNAL_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")


class ProjectGateAssignmentTests(unittest.TestCase):
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
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._sequence = 0
        self._seed()
        self.db = self.Session()
        self.service = ProjectGateAssignmentService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # ---- actors ---------------------------------------------------------

    def admin_user(self) -> User:
        return User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)

    def pm_user(self) -> User:
        return User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)

    def supervisor_user(self) -> User:
        return User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        )

    def internal_user(self) -> User:
        return User(
            id=INTERNAL_ID, name="Internal", email="internal@example.com",
            role=UserRole.internal_employee, active=True,
        )

    # ---- seeding --------------------------------------------------------

    def _seed(self) -> None:
        with self.Session.begin() as session:
            session.add_all([
                self.admin_user(), self.pm_user(), self.supervisor_user(), self.internal_user(),
                User(id=OTHER_INTERNAL_ID, name="Other Internal", email="other@example.com", role=UserRole.internal_employee, active=True),
                User(id=OUTSIDER_INTERNAL_ID, name="Outsider Internal", email="outsider@example.com", role=UserRole.internal_employee, active=True),
            ])
            session.flush()
            profiles = {
                PM_ID: EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                SUPERVISOR_ID: EmployeeProfile(user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available"),
                INTERNAL_ID: EmployeeProfile(user_id=INTERNAL_ID, employee_code="INT-001", designation="Internal Employee", availability="available"),
                OTHER_INTERNAL_ID: EmployeeProfile(user_id=OTHER_INTERNAL_ID, employee_code="INT-002", designation="Internal Employee", availability="available"),
                OUTSIDER_INTERNAL_ID: EmployeeProfile(user_id=OUTSIDER_INTERNAL_ID, employee_code="INT-003", designation="Internal Employee", availability="available"),
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
                (SUPERVISOR_ID, "site_supervisor"),
                (INTERNAL_ID, "internal_employee"),
                (OTHER_INTERNAL_ID, "internal_employee"),
                # OUTSIDER_INTERNAL_ID deliberately NOT a member of the project.
            ):
                session.add(V2ProjectMembership(
                    project_id=self.project_id, employee_id=profiles[user_id].id,
                    project_role=project_role, assigned_by=ADMIN_ID,
                    assignment_reason="Seeded for tests.",
                ))

    def make_approval(self, *, status: str = "unassigned", assigned_to_user_id=None) -> ProjectExternalApproval:
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
                assigned_at=None,
                decided_by=ADMIN_ID if decided else None,
                decided_at=datetime.now(timezone.utc) if decided else None,
            )
            session.add(approval)
            session.flush()
            approval_id = approval.id
        # Read back through the service's own session so the returned
        # instance is attached to it, matching how the service will load it.
        return self.db.get(ProjectExternalApproval, approval_id)

    def stored(self, approval_id) -> ProjectExternalApproval:
        with self.Session() as session:
            return session.get(ProjectExternalApproval, approval_id)

    # ---- assign: who may -------------------------------------------------

    def test_admin_can_assign_an_unassigned_gate(self):
        approval = self.make_approval()
        result = self.service.assign(self.project_id, approval.id, INTERNAL_ID, self.admin_user())
        self.assertEqual(result.status, "assigned")
        self.assertEqual(result.assigned_to_user_id, INTERNAL_ID)
        self.assertEqual(result.assigned_by, ADMIN_ID)
        self.assertIsNotNone(result.assigned_at)

    def test_pm_cannot_assign(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.assign(self.project_id, approval.id, INTERNAL_ID, self.pm_user())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_supervisor_cannot_assign(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.assign(self.project_id, approval.id, INTERNAL_ID, self.supervisor_user())
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- assign: state and assignee validity ------------------------------

    def test_assigning_an_already_assigned_gate_is_refused(self):
        approval = self.make_approval(status="assigned", assigned_to_user_id=INTERNAL_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.assign(self.project_id, approval.id, OTHER_INTERNAL_ID, self.admin_user())
        self.assertEqual(ctx.exception.status_code, 409)

    def test_assigning_to_a_non_internal_employee_is_refused(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.assign(self.project_id, approval.id, PM_ID, self.admin_user())
        self.assertEqual(ctx.exception.status_code, 422)

    def test_assigning_to_an_internal_employee_not_on_this_project_is_refused(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.assign(self.project_id, approval.id, OUTSIDER_INTERNAL_ID, self.admin_user())
        self.assertEqual(ctx.exception.status_code, 422)

    # ---- assign: side effects ---------------------------------------------

    def test_assigning_writes_an_audit_event_and_emits_an_outbox_event(self):
        approval = self.make_approval()
        self.service.assign(self.project_id, approval.id, INTERNAL_ID, self.admin_user())
        with self.Session() as session:
            audit = session.scalars(select(V2AuditEvent).where(V2AuditEvent.entity_id == approval.id)).all()
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit[0].action, "PROJECT_EXTERNAL_APPROVAL_ASSIGNED")
            events = session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == approval.id)).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "project_external_approval.assigned")

    # ---- reassign -----------------------------------------------------------

    def test_admin_can_reassign_a_submitted_gate(self):
        approval = self.make_approval(status="submitted", assigned_to_user_id=INTERNAL_ID)
        result = self.service.reassign(self.project_id, approval.id, OTHER_INTERNAL_ID, self.admin_user())
        self.assertEqual(result.status, "assigned")
        self.assertEqual(result.assigned_to_user_id, OTHER_INTERNAL_ID)

    def test_reassigning_an_unassigned_gate_is_refused(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.reassign(self.project_id, approval.id, OTHER_INTERNAL_ID, self.admin_user())
        self.assertEqual(ctx.exception.status_code, 409)

    def test_reassigning_an_approved_gate_is_refused(self):
        approval = self.make_approval(status="approved", assigned_to_user_id=INTERNAL_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.reassign(self.project_id, approval.id, OTHER_INTERNAL_ID, self.admin_user())
        self.assertEqual(ctx.exception.status_code, 409)

    def test_pm_cannot_reassign(self):
        approval = self.make_approval(status="assigned", assigned_to_user_id=INTERNAL_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.reassign(self.project_id, approval.id, OTHER_INTERNAL_ID, self.pm_user())
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- unassign -----------------------------------------------------------

    def test_admin_can_unassign_an_assigned_gate(self):
        approval = self.make_approval(status="assigned", assigned_to_user_id=INTERNAL_ID)
        result = self.service.unassign(self.project_id, approval.id, self.admin_user())
        self.assertEqual(result.status, "unassigned")
        self.assertIsNone(result.assigned_to_user_id)
        self.assertIsNone(result.assigned_by)
        self.assertIsNone(result.assigned_at)

    def test_unassigning_an_unassigned_gate_is_refused(self):
        approval = self.make_approval()
        with self.assertRaises(HTTPException) as ctx:
            self.service.unassign(self.project_id, approval.id, self.admin_user())
        self.assertEqual(ctx.exception.status_code, 409)

    def test_pm_cannot_unassign(self):
        approval = self.make_approval(status="assigned", assigned_to_user_id=INTERNAL_ID)
        with self.assertRaises(HTTPException) as ctx:
            self.service.unassign(self.project_id, approval.id, self.pm_user())
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
