from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership, V2ProjectTask
from app.routes.projects_v2 import router
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
OTHER_PM_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
SUPERVISOR_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")

# code, template class, template kind
TEMPLATE_TASKS = [
    ("T001", "class_a", None),
    ("T002", None, None),
    ("T003", "standard", None),
    ("T004", None, "approval_gate"),
    ("T005", None, "milestone"),
]


class ProjectTaskClassificationApiTests(unittest.TestCase):
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
            User.__table__, EmployeeProfile.__table__, V2Template.__table__,
            V2TemplateVersion.__table__, V2TemplateTask.__table__, V2Project.__table__,
            V2ProjectMembership.__table__, V2ProjectTask.__table__, V2AuditEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.users = self._seed()
        self.actor = self.users["admin"]
        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: self.actor
        self.client = TestClient(self.app)
        # Same copy the create-project flow runs (generate_task_snapshot).
        response = self.client.post(f"/api/v2/projects/{self.project_id}/generate-tasks")
        self.assertEqual(response.status_code, 200, response.text)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        users = {
            "admin": User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True),
            "pm": User(id=PM_ID, name="Assigned PM", email="pm@example.com", role=UserRole.project_manager, active=True),
            "other_pm": User(id=OTHER_PM_ID, name="Other PM", email="other@example.com", role=UserRole.project_manager, active=True),
            "supervisor": User(id=SUPERVISOR_ID, name="Supervisor", email="sup@example.com", role=UserRole.supervisor, active=True),
        }
        with self.Session.begin() as session:
            session.add_all(users.values())
            pm_profile = EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available")
            session.add(pm_profile)
            session.flush()
            template = V2Template(code="WORKVED-45", name="Workved 45 Day")
            session.add(template)
            session.flush()
            version = V2TemplateVersion(
                template_id=template.id, version_no=2, status="published", duration_days=45,
                content_hash="classification-test", is_current_published=True, created_by=ADMIN_ID,
                published_by=ADMIN_ID, published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            session.flush()
            for index, (code, task_class, task_kind) in enumerate(TEMPLATE_TASKS, start=1):
                session.add(V2TemplateTask(
                    template_version_id=version.id, code=code, sequence_no=index, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=index, planned_end_day=index,
                    applicability="mandatory", task_class=task_class, task_kind=task_kind,
                    evidence_required=False, duration_days=1,
                ))
            project = V2Project(
                code="PRJ-CLS-001", name="Classification Project", client_name="Client", site_address="Mumbai",
                start_date=date(2026, 10, 1), template_version_id=version.id, status="draft", created_by=ADMIN_ID,
            )
            session.add(project)
            session.flush()
            session.add(V2ProjectMembership(
                project_id=project.id, employee_id=pm_profile.id, project_role="project_manager",
                assigned_by=ADMIN_ID, assignment_reason="Assigned",
            ))
            self.project_id = project.id
        return users

    def task_ids(self):
        with self.Session() as session:
            rows = session.scalars(select(V2ProjectTask).where(V2ProjectTask.project_id == self.project_id)).all()
            return {task.original_code: task.id for task in rows}

    def project_classes(self):
        with self.Session() as session:
            rows = session.scalars(select(V2ProjectTask).where(V2ProjectTask.project_id == self.project_id)).all()
            return {task.original_code: task.task_class for task in rows}

    def template_classes(self):
        with self.Session() as session:
            return {task.code: task.task_class for task in session.scalars(select(V2TemplateTask)).all()}

    def put(self, items):
        return self.client.put(f"/api/v2/projects/{self.project_id}/task-classification", json={"items": items})

    def test_copied_tasks_default_to_the_template_class(self):
        self.assertEqual(
            self.project_classes(),
            {"T001": "class_a", "T002": None, "T003": "standard", "T004": None, "T005": None},
        )
        body = self.client.get(f"/api/v2/projects/{self.project_id}/task-classification").json()
        self.assertTrue(body["editable"])
        by_code = {item["code"]: item for item in body["items"]}
        self.assertEqual([item["code"] for item in body["items"]], ["T001", "T002", "T003", "T004", "T005"])
        self.assertEqual(by_code["T001"]["template_task_class"], "class_a")
        self.assertTrue(by_code["T001"]["classifiable"])
        self.assertFalse(by_code["T004"]["classifiable"])
        self.assertEqual(by_code["T004"]["task_kind"], "approval_gate")
        self.assertFalse(by_code["T005"]["classifiable"])

    def test_assigned_pm_override_is_stored_on_the_project_task_only(self):
        self.actor = self.users["pm"]
        ids = self.task_ids()
        response = self.put([
            {"task_id": str(ids["T001"]), "task_class": "standard"},
            {"task_id": str(ids["T002"]), "task_class": "class_a"},
            {"task_id": str(ids["T003"]), "task_class": "standard"},  # unchanged - no audit row
        ])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.project_classes()["T001"], "standard")
        self.assertEqual(self.project_classes()["T002"], "class_a")
        # The template is never touched.
        self.assertEqual(
            self.template_classes(),
            {"T001": "class_a", "T002": None, "T003": "standard", "T004": None, "T005": None},
        )
        with self.Session() as session:
            audits = session.scalars(
                select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_TASK_CLASSIFICATION_CHANGED")
            ).all()
        self.assertEqual(sorted(audit.after_json["code"] for audit in audits), ["T001", "T002"])
        self.assertTrue(all(audit.actor_user_id == PM_ID for audit in audits))

    def test_invalid_class_is_rejected(self):
        ids = self.task_ids()
        for bad in ("classA", "approval_gate", "", None):
            response = self.put([{"task_id": str(ids["T002"]), "task_class": bad}])
            self.assertEqual(response.status_code, 422, bad)
        self.assertIsNone(self.project_classes()["T002"])

    def test_approval_gates_and_milestones_cannot_be_classified(self):
        ids = self.task_ids()
        for code in ("T004", "T005"):
            response = self.put([
                {"task_id": str(ids["T002"]), "task_class": "class_a"},
                {"task_id": str(ids[code]), "task_class": "standard"},
            ])
            self.assertEqual(response.status_code, 422, code)
        # All-or-nothing: the valid row in the same request was not saved.
        self.assertEqual(self.project_classes(), {"T001": "class_a", "T002": None, "T003": "standard", "T004": None, "T005": None})
        with self.Session() as session:
            kinds = {t.original_code: t.task_kind for t in session.scalars(select(V2ProjectTask)).all()}
        self.assertEqual(kinds["T004"], "approval_gate")

    def test_non_draft_projects_cannot_be_changed(self):
        ids = self.task_ids()
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "active"
        response = self.put([{"task_id": str(ids["T001"]), "task_class": "standard"}])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.project_classes()["T001"], "class_a")
        body = self.client.get(f"/api/v2/projects/{self.project_id}/task-classification").json()
        self.assertFalse(body["editable"])

    def test_only_admin_and_the_assigned_pm_have_access(self):
        ids = self.task_ids()
        for role in ("other_pm", "supervisor"):
            self.actor = self.users[role]
            self.assertEqual(self.client.get(f"/api/v2/projects/{self.project_id}/task-classification").status_code, 403)
            self.assertEqual(self.put([{"task_id": str(ids["T002"]), "task_class": "class_a"}]).status_code, 403)
        self.assertIsNone(self.project_classes()["T002"])

    def test_unknown_or_duplicate_tasks_are_rejected(self):
        ids = self.task_ids()
        self.assertEqual(self.put([{"task_id": str(uuid.uuid4()), "task_class": "class_a"}]).status_code, 404)
        duplicate = self.put([
            {"task_id": str(ids["T002"]), "task_class": "class_a"},
            {"task_id": str(ids["T002"]), "task_class": "standard"},
        ])
        self.assertEqual(duplicate.status_code, 422)
        self.assertIsNone(self.project_classes()["T002"])


if __name__ == "__main__":
    unittest.main()
