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
from app.routes.admin_visibility_v2 import router as admin_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion

ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class AdminVisibilityRollupTests(unittest.TestCase):
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

        with self.Session.begin() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.add(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))
            session.flush()
            session.add(EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"))

        self.app = FastAPI()
        self.app.include_router(admin_router)

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

    def add_project(self, code="PRJ-1", name="Project 1", with_task=True):
        project_id = uuid.uuid4()
        with self.Session.begin() as session:
            session.add(V2Project(
                id=project_id, code=code, name=name, client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))
            if with_task:
                session.add(Task(
                    id=uuid.uuid4(), project_id=project_id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                    original_code="T001", template_sequence=1, title="Task T001",
                    schedule_classification="execution", applicability="mandatory", lifecycle_status="in_progress",
                ))
        return project_id

    # ---- happy paths -------------------------------------------------------

    def test_admin_retrieves_rollup_across_multiple_projects(self):
        self.add_project("PRJ-1", "Project 1")
        self.add_project("PRJ-2", "Project 2")

        response = self.client.get("/api/v2/admin/projects-overview")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 2)
        self.assertEqual({row["code"] for row in body}, {"PRJ-1", "PRJ-2"})
        self.assertEqual(next(row for row in body if row["code"] == "PRJ-1")["total_count"], 1)

    def test_admin_retrieves_cross_project_activity(self):
        response = self.client.get("/api/v2/admin/activity")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    # ---- edge case -----------------------------------------------------

    def test_rollup_with_zero_projects_returns_empty_list(self):
        response = self.client.get("/api/v2/admin/projects-overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    # ---- error path ------------------------------------------------------

    def test_non_admin_cannot_access_either_endpoint(self):
        self.add_project()
        self.act_as_pm()
        overview = self.client.get("/api/v2/admin/projects-overview")
        self.assertEqual(overview.status_code, 403)
        activity = self.client.get("/api/v2/admin/activity")
        self.assertEqual(activity.status_code, 403)


if __name__ == "__main__":
    unittest.main()
