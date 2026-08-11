from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

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
from app.routes.project_read_models_v2 import router as read_models_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion

ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
PM_EMPLOYEE_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class ProjectReadModelTests(unittest.TestCase):
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
            User.__table__, EmployeeProfile.__table__,
            V2Template.__table__, V2TemplateVersion.__table__, V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2Project.__table__, V2ProjectMembership.__table__, V2ProjectTask.__table__,
            V2ProjectTaskDependency.__table__, ProjectRoleChange.__table__, V2AuditEvent.__table__,
            ProjectBaseline.__table__, BaselineTask.__table__, Task.__table__, TaskDependency.__table__,
            TaskProgressUpdate.__table__, TaskVerification.__table__, TaskBlocker.__table__,
            TaskDelayEvent.__table__, TaskApprovalDecision.__table__, TaskSupportAssignment.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        with self.Session.begin() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.add(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))
            session.flush()
            session.add(EmployeeProfile(
                id=PM_EMPLOYEE_ID, user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available",
            ))

        self.app = FastAPI()
        # Registered in the same order as app.main so the route-precedence
        # guarantee this module depends on is what the tests exercise.
        self.app.include_router(read_models_router)
        self.app.include_router(projects_router)

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

    def add_project(self, code="PRJ-1", name="Project 1", status="active", handover=date(2026, 9, 22), pm_member=False):
        project_id = uuid.uuid4()
        with self.Session.begin() as session:
            session.add(V2Project(
                id=project_id, code=code, name=name, client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), target_handover_date=handover, status=status, created_by=ADMIN_ID,
            ))
            if pm_member:
                session.add(V2ProjectMembership(
                    project_id=project_id, employee_id=PM_EMPLOYEE_ID, project_role="project_manager",
                    assigned_by=ADMIN_ID, assignment_reason="Initial.",
                ))
        return project_id

    def add_task(self, project_id, code, sequence, phase, status="planned", **kwargs):
        with self.Session.begin() as session:
            session.add(Task(
                id=kwargs.pop("task_id", uuid.uuid4()), project_id=project_id,
                baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code=code, template_sequence=sequence, title=f"Task {code}", phase=phase,
                schedule_classification="execution", applicability="mandatory", lifecycle_status=status,
                **kwargs,
            ))

    # ---- route precedence ------------------------------------------------

    def test_collection_routes_are_not_swallowed_by_the_project_id_route(self):
        """projects_v2 defines GET /{project_id}; if this router were
        registered after it, these paths would 422 as invalid UUIDs."""
        for path in ("/api/v2/projects/summaries", "/api/v2/projects/attention"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, f"{path} -> {response.text}")
            self.assertIsInstance(response.json(), list)

    # ---- summaries -------------------------------------------------------

    def test_summary_reports_progress_and_phase_rollup_in_schedule_order(self):
        project_id = self.add_project()
        self.add_task(project_id, "T001", 1, "Planning & Approvals", "completed")
        self.add_task(project_id, "T002", 2, "Planning & Approvals", "completed")
        self.add_task(project_id, "T003", 3, "Civil Work", "completed")
        self.add_task(project_id, "T004", 4, "Civil Work", "in_progress")

        response = self.client.get("/api/v2/projects/summaries")
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()[0]

        self.assertEqual(row["total_count"], 4)
        self.assertEqual(row["completed_count"], 3)
        self.assertEqual(row["progress_pct"], 75)
        self.assertEqual(
            [(phase["phase"], phase["pct"]) for phase in row["phases"]],
            [("Planning & Approvals", 100), ("Civil Work", 50)],
        )

    def test_summary_labels_unphased_tasks_rather_than_dropping_them(self):
        project_id = self.add_project()
        self.add_task(project_id, "T001", 1, None, "completed")

        row = self.client.get("/api/v2/projects/summaries").json()[0]
        self.assertEqual([phase["phase"] for phase in row["phases"]], ["Unphased"])
        self.assertEqual(row["progress_pct"], 100)

    def test_summary_reports_last_activity_from_the_audit_trail(self):
        project_id = self.add_project()
        older = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 8, 9, 17, 30, tzinfo=timezone.utc)
        with self.Session.begin() as session:
            for occurred_at, action in ((older, "PROJECT_CREATED"), (newer, "PROJECT_ACTIVATED")):
                session.add(V2AuditEvent(
                    actor_user_id=ADMIN_ID, action=action, entity_type="project", entity_id=project_id,
                    project_id=project_id, reason="Change.", occurred_at=occurred_at,
                ))

        row = self.client.get("/api/v2/projects/summaries").json()[0]
        self.assertTrue(row["last_activity_at"].startswith("2026-08-09T17:30"))

    def test_summary_of_a_project_with_no_tasks_reports_zero_not_an_error(self):
        self.add_project()
        row = self.client.get("/api/v2/projects/summaries").json()[0]
        self.assertEqual(row["progress_pct"], 0)
        self.assertEqual(row["total_count"], 0)
        self.assertEqual(row["phases"], [])
        self.assertIsNone(row["last_activity_at"])

    # ---- scoping ---------------------------------------------------------

    def test_a_pm_sees_only_projects_they_are_a_member_of(self):
        self.add_project("PRJ-1", "Mine", pm_member=True)
        self.add_project("PRJ-2", "Not mine")
        self.act_as_pm()

        rows = self.client.get("/api/v2/projects/summaries").json()
        self.assertEqual(len(rows), 1)
        detail = self.client.get(f"/api/v2/projects/{rows[0]['project_id']}")
        self.assertEqual(detail.json()["name"], "Mine")

    def test_a_pm_with_no_memberships_gets_empty_read_models_not_a_403(self):
        self.add_project("PRJ-1", "Not mine")
        self.act_as_pm()
        self.assertEqual(self.client.get("/api/v2/projects/summaries").json(), [])
        self.assertEqual(self.client.get("/api/v2/projects/attention").json(), [])

    def test_archived_projects_are_excluded_from_both_read_models(self):
        self.add_project("PRJ-1", "Archived", status="archived", handover=None)
        self.assertEqual(self.client.get("/api/v2/projects/summaries").json(), [])
        self.assertEqual(self.client.get("/api/v2/projects/attention").json(), [])

    # ---- attention -------------------------------------------------------

    def test_attention_flags_a_draft_with_no_generated_tasks(self):
        self.add_project("PRJ-1", "Fresh draft", status="draft")
        items = self.client.get("/api/v2/projects/attention").json()
        titles = {item["title"] for item in items}
        self.assertIn("Tasks not generated", titles)
        self.assertEqual({item["group"] for item in items}, {"Setup incomplete"})

    def test_attention_flags_a_draft_missing_its_handover_date(self):
        self.add_project("PRJ-1", "No handover", status="draft", handover=None)
        titles = {item["title"] for item in self.client.get("/api/v2/projects/attention").json()}
        self.assertIn("Target handover date missing", titles)

    def test_attention_ranks_overdue_above_decisions(self):
        project_id = self.add_project()
        past = datetime.now(timezone.utc) - timedelta(days=3)
        self.add_task(project_id, "T001", 1, "Civil Work", "in_progress", due_at=past)
        self.add_task(project_id, "T002", 2, "Civil Work", "approval_pending")

        items = self.client.get("/api/v2/projects/attention").json()
        self.assertEqual(items[0]["severity"], "critical")
        self.assertIn("overdue", items[0]["title"])
        self.assertEqual(items[0]["pane"], "dashboard")
        self.assertIn("decision", {item["severity"] for item in items})

    def test_attention_pluralises_a_single_blocked_task_correctly(self):
        project_id = self.add_project()
        task_id = uuid.uuid4()
        self.add_task(project_id, "T001", 1, "Civil Work", "in_progress", task_id=task_id)
        with self.Session.begin() as session:
            session.add(TaskBlocker(
                task_id=task_id, project_id=project_id, type="access",
                description="Shaft not released.",
            ))

        titles = {item["title"] for item in self.client.get("/api/v2/projects/attention").json()}
        self.assertIn("1 task blocked", titles)

    def test_a_healthy_active_project_produces_no_attention_items(self):
        project_id = self.add_project()
        self.add_task(project_id, "T001", 1, "Civil Work", "completed")
        self.assertEqual(self.client.get("/api/v2/projects/attention").json(), [])


def test_read_model_routes_outrank_the_project_id_route_on_the_production_app():
    """The class-based tests build their own app in the correct order, which
    proves the ordering works but not that app.main uses it. This asserts
    against the real application object: both collection paths must appear
    before `/{project_id}`, or FastAPI resolves them as UUIDs and 422s."""
    from app.main import create_app

    app = create_app()
    paths = [route.path for route in app.routes if getattr(route, "methods", None) and "GET" in route.methods]

    catch_all = paths.index("/api/v2/projects/{project_id}")
    for path in ("/api/v2/projects/summaries", "/api/v2/projects/attention"):
        assert path in paths, f"{path} is not registered on the production app"
        assert paths.index(path) < catch_all, f"{path} is registered after /{{project_id}} and will never match"


if __name__ == "__main__":
    unittest.main()
