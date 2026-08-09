from __future__ import annotations

import unittest
import uuid
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import (
    BaselineTask,
    OutboxEvent,
    ProjectBaseline,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDelayEvent,
    TaskDependency,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    ProjectRoleChange,
    V2AuditEvent,
    V2Project,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.routes.project_dashboard_v2 import router as dashboard_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class ProjectDashboardRouteTests(unittest.TestCase):
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
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2ProjectTaskDependency.__table__,
            ProjectRoleChange.__table__,
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            TaskVerification.__table__,
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            TaskApprovalDecision.__table__,
            TaskSupportAssignment.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.project_id = uuid.uuid4()

        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            outsider = User(
                id=OUTSIDER_ID, name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True,
            )
            session.add_all([admin, pm, outsider])
            session.flush()
            pm_profile = EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available")
            session.add(pm_profile)
            session.add(EmployeeProfile(user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available"))
            session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Project 1", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))
            session.flush()
            session.add(V2ProjectMembership(
                project_id=self.project_id, employee_id=pm_profile.id, project_role="project_manager",
                assigned_by=ADMIN_ID, assignment_reason="Initial assignment.",
            ))
            session.add(Task(
                id=uuid.uuid4(), project_id=self.project_id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Task T001",
                schedule_classification="execution", applicability="mandatory", lifecycle_status="in_progress",
            ))

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(dashboard_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def act_as_pm(self):
        self._current_actor = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)

    def act_as_outsider(self):
        self._current_actor = User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True,
        )

    def test_authorized_member_sees_all_summary_categories(self):
        self.act_as_pm()
        response = self.client.get(f"/api/v2/projects/{self.project_id}/dashboard")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["summary"]["total_count"], 1)
        self.assertIn("blocked_tasks", body["summary"])
        self.assertIn("overdue_tasks", body["summary"])
        self.assertIn("reassignment_required", body["summary"])
        self.assertEqual(body["vendor_risks"], [])

    def test_dashboard_with_no_vendor_data_succeeds_with_empty_vendor_risks(self):
        response = self.client.get(f"/api/v2/projects/{self.project_id}/dashboard")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["vendor_risks"], [])

    def test_non_member_non_admin_cannot_retrieve_dashboard(self):
        self.act_as_outsider()
        response = self.client.get(f"/api/v2/projects/{self.project_id}/dashboard")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
