from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import BaselineTask, FileObject, OutboxEvent, ProjectBaseline, Task, TaskDependency, TaskEvidence, TaskProgressUpdate
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    ProjectRoleChange,
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.routes.execution_tasks_v2 import router as execution_tasks_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
SECOND_ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
REPLACEMENT_PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb9")
REPLACEMENT_SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc9")


class ProjectRoleChangeApprovalApiTests(unittest.TestCase):
    """U6: two-step (request + approval) PM/Supervisor reassignment
    (BR-007/R7), plus the DB-level partial-unique-index invariant on
    project_memberships. Follows the same SQLite-ATTACHed-schema harness
    pattern as test_task_verification_approval_v2.py.
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
            # V2ProjectExternalGate's broad-text check constraint uses
            # Postgres's btrim(); SQLite has no such builtin, so register
            # an equivalent for this test harness only.
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2ProjectTaskDependency.__table__,
            V2ProjectExternalGate.__table__,
            V2AuditEvent.__table__,
            ProjectRoleChange.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            FileObject.__table__,
            TaskEvidence.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        # The partial unique index on siteops_v2.project_memberships is a
        # raw-SQL migration artifact (202608020005_..._role_changes.sql),
        # not part of the SQLAlchemy model's __table_args__ - so
        # Table.create() above does not create it. SQLite supports the
        # same partial-index syntax as Postgres, so we create the exact
        # index here to exercise the real DB-level constraint the
        # migration adds, independent of any application-level check.
        with self.engine.begin() as conn:
            conn.execute(text(
                "create unique index siteops_v2.uq_v2_project_memberships_one_active_role "
                "on project_memberships(project_id, project_role) "
                "where ends_at is null and project_role in ('project_manager', 'site_supervisor')"
            ))

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(execution_tasks_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = User(
            id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True,
        )
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def act_as(self, user: User) -> None:
        self._current_actor = user

    def act_as_admin(self, admin_id: uuid.UUID = ADMIN_ID, name: str = "Admin") -> None:
        self.act_as(User(id=admin_id, name=name, email=f"{name.lower()}@example.com", role=UserRole.admin, active=True))

    def act_as_pm(self) -> None:
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))

    def act_as_supervisor(self) -> None:
        self.act_as(User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            second_admin = User(id=SECOND_ADMIN_ID, name="Admin Two", email="admin2@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True,
            )
            replacement_pm = User(
                id=REPLACEMENT_PM_ID, name="PM Replacement", email="pm-replacement@example.com",
                role=UserRole.project_manager, active=True,
            )
            replacement_supervisor = User(
                id=REPLACEMENT_SUPERVISOR_ID, name="Supervisor Replacement", email="supervisor-replacement@example.com",
                role=UserRole.supervisor, active=True,
            )
            session.add_all([admin, second_admin, pm, supervisor, replacement_pm, replacement_supervisor])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=REPLACEMENT_PM_ID, employee_code="PM-002", designation="PM", availability="available",
                ),
                EmployeeProfile(
                    user_id=REPLACEMENT_SUPERVISOR_ID, employee_code="SUP-002", designation="Supervisor", availability="available",
                ),
            ])
            template = V2Template(code="WORKVED-45", name="Workved 45 Day")
            session.add(template)
            session.flush()
            published = V2TemplateVersion(
                template_id=template.id, version_no=1, status="published", duration_days=45,
                content_hash="published-hash", is_current_published=True,
                created_by=ADMIN_ID, published_by=ADMIN_ID, published_at=datetime.now(timezone.utc),
            )
            session.add(published)
            session.flush()
            session.add(V2TemplateTask(
                template_version_id=published.id, code="T001", sequence_no=1, title="Task T001",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", task_class="standard", task_kind="work",
                evidence_required=False, duration_days=1, phase="Setup", category="Site",
            ))
            session.flush()
            self.published_version_id = published.id

    def create_draft(self, **overrides):
        payload = {
            "project_name": "Futurex Fitout",
            "client": "Example Client",
            "location": "Mumbai",
            "proposed_start_date": "2026-08-01",
            "target_handover_date": "2026-09-14",
            "pm_user_id": str(PM_ID),
            "supervisor_user_id": str(SUPERVISOR_ID),
            "template_version_id": str(self.published_version_id),
        }
        payload.update(overrides)
        response = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def employee_id_for(self, user_id: uuid.UUID) -> uuid.UUID:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id))

    def request_role_change(self, project_id, role_type, replacement_employee_id, reason="Operational requirement."):
        return self.client.post(
            f"/api/v2/projects/{project_id}/role-changes",
            json={"role_type": role_type, "replacement_employee_id": str(replacement_employee_id), "reason": reason},
        )

    def approve_role_change(self, project_id, change_id):
        return self.client.post(f"/api/v2/projects/{project_id}/role-changes/{change_id}/approve")

    def reject_role_change(self, project_id, change_id, reason="Not appropriate."):
        return self.client.post(f"/api/v2/projects/{project_id}/role-changes/{change_id}/reject", json={"reason": reason})

    def activate(self, project_id):
        generate = self.client.post(f"/api/v2/projects/{project_id}/generate-tasks")
        self.assertEqual(generate.status_code, 200, generate.text)
        response = self.client.post(f"/api/v2/projects/{project_id}/activate", json={"reason": "Go live."})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # ---- happy path: PM replacement request + approval ----------------------

    def test_admin_requests_pm_replacement_and_second_actor_approves(self):
        project = self.create_draft()
        replacement_id = self.employee_id_for(REPLACEMENT_PM_ID)

        self.act_as_admin()
        requested = self.request_role_change(project["id"], "project_manager", replacement_id)
        self.assertEqual(requested.status_code, 200, requested.text)
        change = requested.json()
        self.assertEqual(change["status"], "pending")

        # Pending record does not affect current accountability - original
        # PM's membership row is still active.
        with self.Session() as session:
            active_pm = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "project_manager",
                    V2ProjectMembership.ends_at.is_(None),
                )
            )
            self.assertEqual(active_pm.employee_id, self.employee_id_for(PM_ID))

        # A second authorized actor (a different Admin) approves it.
        self.act_as_admin(admin_id=SECOND_ADMIN_ID, name="Admin Two")
        approved = self.approve_role_change(project["id"], change["id"])
        self.assertEqual(approved.status_code, 200, approved.text)
        new_membership = approved.json()
        self.assertEqual(new_membership["employee_id"], str(replacement_id))

        with self.Session() as session:
            old_pm = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "project_manager",
                    V2ProjectMembership.employee_id == self.employee_id_for(PM_ID),
                )
            )
            self.assertIsNotNone(old_pm.ends_at)

            new_pm = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "project_manager",
                    V2ProjectMembership.employee_id == replacement_id,
                )
            )
            self.assertIsNotNone(new_pm)
            self.assertIsNone(new_pm.ends_at)

            change_row = session.get(ProjectRoleChange, uuid.UUID(change["id"]))
            self.assertEqual(change_row.status, "approved")
            self.assertIsNotNone(change_row.decided_by)
            self.assertIsNotNone(change_row.decided_at)

            audit_actions = {row.action for row in session.scalars(select(V2AuditEvent))}
            self.assertIn("PROJECT_ROLE_CHANGE_REQUESTED", audit_actions)
            self.assertIn("PROJECT_ROLE_CHANGE_APPROVED", audit_actions)

    # ---- happy path: active PM requests Supervisor replacement --------------

    def test_active_pm_requests_supervisor_replacement_admin_approves(self):
        project = self.create_draft()
        replacement_id = self.employee_id_for(REPLACEMENT_SUPERVISOR_ID)

        self.act_as_pm()
        requested = self.request_role_change(project["id"], "site_supervisor", replacement_id)
        self.assertEqual(requested.status_code, 200, requested.text)

        self.act_as_admin()
        approved = self.approve_role_change(project["id"], requested.json()["id"])
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["employee_id"], str(replacement_id))

    # ---- reject -----------------------------------------------------------

    def test_reject_role_change_does_not_alter_membership(self):
        project = self.create_draft()
        replacement_id = self.employee_id_for(REPLACEMENT_PM_ID)

        self.act_as_admin()
        requested = self.request_role_change(project["id"], "project_manager", replacement_id)
        change_id = requested.json()["id"]

        rejected = self.reject_role_change(project["id"], change_id)
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["status"], "rejected")

        with self.Session() as session:
            active_pm = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "project_manager",
                    V2ProjectMembership.ends_at.is_(None),
                )
            )
            self.assertEqual(active_pm.employee_id, self.employee_id_for(PM_ID))

    # ---- error paths ---------------------------------------------------------

    def test_request_without_reason_is_rejected(self):
        project = self.create_draft()
        replacement_id = self.employee_id_for(REPLACEMENT_PM_ID)

        self.act_as_admin()
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/role-changes",
            json={"role_type": "project_manager", "replacement_employee_id": str(replacement_id), "reason": ""},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_actor_outside_hierarchy_cannot_request_own_replacement(self):
        """BR-007: Supervisor replacement must be requested by the PM (or
        Admin fallback) - a Supervisor requesting their own replacement is
        outside the hierarchy and is rejected."""
        project = self.create_draft()
        replacement_id = self.employee_id_for(REPLACEMENT_SUPERVISOR_ID)

        self.act_as_supervisor()
        response = self.request_role_change(project["id"], "site_supervisor", replacement_id)
        self.assertEqual(response.status_code, 403, response.text)

    def test_non_admin_cannot_request_pm_replacement(self):
        project = self.create_draft()
        replacement_id = self.employee_id_for(REPLACEMENT_PM_ID)

        self.act_as_pm()
        response = self.request_role_change(project["id"], "project_manager", replacement_id)
        self.assertEqual(response.status_code, 403, response.text)

    def test_ending_accountable_membership_directly_is_rejected_on_active_project(self):
        """POST /memberships/{id}/end no longer accepts PM/Supervisor
        endings directly on an ACTIVE project - the two-step role-change
        flow is required there. Draft-phase projects keep the pre-U6
        direct-end behavior (see test_ending_accountable_membership_
        directly_still_allowed_while_draft below) - several existing
        tests (test_activate_rejects_when_accountable_role_missing,
        test_activation_without_active_pm_or_supervisor_is_rejected_...)
        rely on freely ending an accountable role before activation."""
        project = self.create_draft()
        self.act_as_admin()
        self.activate(project["id"])
        with self.Session() as session:
            membership = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "project_manager",
                    V2ProjectMembership.ends_at.is_(None),
                )
            )
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships/{membership.id}/end",
            json={"reason": "Trying to end directly."},
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_ending_accountable_membership_directly_still_allowed_while_draft(self):
        """Pre-U6 behavior is preserved for draft projects: ending a PM/
        Supervisor membership directly (without the role-change flow) is
        still allowed before activation."""
        project = self.create_draft()
        with self.Session() as session:
            membership = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "project_manager",
                )
            )
        self.act_as_admin()
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships/{membership.id}/end",
            json={"reason": "Draft-phase team change."},
        )
        self.assertEqual(response.status_code, 200, response.text)

    # ---- reassignment-required surfacing ------------------------------------

    def test_marking_active_supervisor_unavailable_surfaces_reassignment_required(self):
        project = self.create_draft()

        with self.Session.begin() as session:
            profile = session.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == SUPERVISOR_ID))
            profile.availability = "unavailable"

        self.act_as_admin()
        response = self.client.get(f"/api/v2/projects/{project['id']}/role-changes/reassignment-required")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["role_type"], "site_supervisor")
        self.assertEqual(body[0]["employee_id"], str(self.employee_id_for(SUPERVISOR_ID)))

        # Nothing was silently reassigned - the Supervisor membership is
        # still the same, still active.
        with self.Session() as session:
            active_supervisor = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "site_supervisor",
                    V2ProjectMembership.ends_at.is_(None),
                )
            )
            self.assertEqual(active_supervisor.employee_id, self.employee_id_for(SUPERVISOR_ID))

    # ---- DB-level partial unique index -------------------------------------

    def test_db_level_partial_unique_index_rejects_second_active_pm(self):
        """Integration: independent of and in addition to
        ProjectRoleChangeService/assign_membership's own application-level
        checks, a direct second active `project_manager` membership row
        insert at the model/DB level is rejected by the partial unique
        index created in this test's setUp (mirroring
        uq_v2_project_memberships_one_active_role from the U6 migration)."""
        project = self.create_draft()
        other_pm_employee_id = self.employee_id_for(REPLACEMENT_PM_ID)

        with self.Session() as session:
            second_active_pm = V2ProjectMembership(
                project_id=uuid.UUID(project["id"]),
                employee_id=other_pm_employee_id,
                project_role="project_manager",
                assigned_by=ADMIN_ID,
                assignment_reason="Attempting to bypass the application-level check.",
            )
            session.add(second_active_pm)
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

    def test_db_level_partial_unique_index_rejects_second_active_supervisor(self):
        project = self.create_draft()
        other_supervisor_employee_id = self.employee_id_for(REPLACEMENT_SUPERVISOR_ID)

        with self.Session() as session:
            second_active_supervisor = V2ProjectMembership(
                project_id=uuid.UUID(project["id"]),
                employee_id=other_supervisor_employee_id,
                project_role="site_supervisor",
                assigned_by=ADMIN_ID,
                assignment_reason="Attempting to bypass the application-level check.",
            )
            session.add(second_active_supervisor)
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

    def test_db_level_partial_unique_index_allows_ended_plus_new_active(self):
        """Sanity check that the partial index only guards concurrently
        active rows - a project can still accumulate membership history
        (ended rows) without tripping the constraint, matching the real
        assign_membership()/approve_role_change() flow."""
        project = self.create_draft()
        with self.Session.begin() as session:
            membership = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "project_manager",
                )
            )
            membership.ends_at = datetime.now(timezone.utc)

        with self.Session.begin() as session:
            session.add(V2ProjectMembership(
                project_id=uuid.UUID(project["id"]),
                employee_id=self.employee_id_for(REPLACEMENT_PM_ID),
                project_role="project_manager",
                assigned_by=ADMIN_ID,
                assignment_reason="Legitimate replacement after the prior membership ended.",
            ))
        # No exception raised - success is the assertion.


if __name__ == "__main__":
    unittest.main()
