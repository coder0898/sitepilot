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
SUPER_ADMIN_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")


class ProjectTaskApplicabilityApiTests(unittest.TestCase):
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

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        users = {
            "admin": User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True),
            "pm": User(id=PM_ID, name="Assigned PM", email="pm@example.com", role=UserRole.project_manager, active=True),
            "other_pm": User(id=OTHER_PM_ID, name="Other PM", email="other@example.com", role=UserRole.project_manager, active=True),
            "supervisor": User(id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True),
            "super_admin": User(id=SUPER_ADMIN_ID, name="Super Admin", email="super@example.com", role=UserRole.super_admin, active=True),
        }
        with self.Session.begin() as session:
            session.add_all(users.values())
            pm_profile = EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available")
            other_pm_profile = EmployeeProfile(user_id=OTHER_PM_ID, employee_code="PM-002", designation="PM", availability="available")
            session.add_all([pm_profile, other_pm_profile])
            session.flush()
            template = V2Template(code="WORKVED-45", name="Workved 45 Day")
            session.add(template)
            session.flush()
            version = V2TemplateVersion(
                template_id=template.id, version_no=1, status="published", duration_days=45,
                content_hash="applicability-test", is_current_published=True, created_by=ADMIN_ID,
                published_by=ADMIN_ID, published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            session.flush()
            mandatory_source = V2TemplateTask(
                template_version_id=version.id, code="T001", sequence_no=1, title="Mandatory task",
                schedule_classification="pre_activation", applicability="mandatory", evidence_required=False,
            )
            conditional_source = V2TemplateTask(
                template_version_id=version.id, code="T098", sequence_no=98, title="Conditional task",
                schedule_classification="execution", planned_start_day=45, planned_end_day=45,
                applicability="conditional", evidence_required=False, duration_days=1,
            )
            session.add_all([mandatory_source, conditional_source])
            session.flush()
            project = V2Project(
                code="PRJ-APP-001", name="Applicability Project", client_name="Client", site_address="Mumbai",
                start_date=date(2026, 8, 1), template_version_id=version.id, status="draft", created_by=ADMIN_ID,
            )
            session.add(project)
            session.flush()
            session.add(V2ProjectMembership(
                project_id=project.id, employee_id=pm_profile.id, project_role="project_manager",
                assigned_by=ADMIN_ID, assignment_reason="Assigned for review",
            ))
            mandatory = V2ProjectTask(
                project_id=project.id, template_version_id=version.id, template_task_id=mandatory_source.id,
                original_code="T001", template_sequence=1, title="Mandatory task",
                schedule_classification="pre_activation", applicability="mandatory", source_type="template",
                lifecycle_status="draft", included=True, decision_state="pending_review",
            )
            conditional = V2ProjectTask(
                project_id=project.id, template_version_id=version.id, template_task_id=conditional_source.id,
                original_code="T098", template_sequence=98, title="Conditional task",
                schedule_classification="execution", planned_start_day=45, planned_end_day=45,
                applicability="conditional", source_type="template", lifecycle_status="draft",
                included=True, decision_state="pending_review",
            )
            session.add_all([mandatory, conditional])
            session.flush()
            self.project_id = project.id
            self.mandatory_id = mandatory.id
            self.conditional_id = conditional.id
        return users

    def decide(self, task_id, decision, reason=None):
        payload = {"decision": decision}
        if reason is not None:
            payload["reason"] = reason
        return self.client.post(
            f"/api/v2/projects/{self.project_id}/tasks/{task_id}/applicability-decisions",
            json=payload,
        )

    def test_exclude_conditional_requires_reason_and_preserves_template(self):
        missing = self.decide(self.conditional_id, "excluded", "   ")
        self.assertEqual(missing.status_code, 422, missing.text)
        response = self.decide(self.conditional_id, "excluded", "Client does not require this scope.")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["included"])
        self.assertEqual(body["decision_state"], "excluded")
        self.assertEqual(body["actor_user_id"], str(ADMIN_ID))
        self.assertTrue(body["decided_at"])
        with self.Session() as session:
            project_task = session.get(V2ProjectTask, self.conditional_id)
            template_task = session.get(V2TemplateTask, project_task.template_task_id)
            self.assertFalse(project_task.included)
            self.assertEqual(template_task.applicability, "conditional")

    def test_mandatory_task_is_locked_included(self):
        response = self.decide(self.mandatory_id, "excluded", "Attempted exclusion")
        self.assertEqual(response.status_code, 409, response.text)
        with self.Session() as session:
            task = session.get(V2ProjectTask, self.mandatory_id)
            self.assertTrue(task.included)
            self.assertEqual(task.decision_state, "pending_review")
            self.assertIsNone(session.scalar(select(V2AuditEvent).where(V2AuditEvent.entity_id == task.id)))

    def test_reinclude_appends_history_with_actor_reason_and_time(self):
        self.assertEqual(self.decide(self.conditional_id, "excluded", "Scope removed").status_code, 200)
        response = self.decide(self.conditional_id, "included", "Scope restored")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["included"])
        with self.Session() as session:
            events = list(session.scalars(
                select(V2AuditEvent)
                .where(V2AuditEvent.entity_id == self.conditional_id)
                .order_by(V2AuditEvent.occurred_at, V2AuditEvent.id)
            ).all())
            self.assertEqual(len(events), 2)
            self.assertEqual([event.actor_user_id for event in events], [ADMIN_ID, ADMIN_ID])
            self.assertEqual([event.reason for event in events], ["Scope removed", "Scope restored"])
            self.assertEqual(events[0].after_json["decision_state"], "excluded")
            self.assertEqual(events[1].before_json["decision_state"], "excluded")
            self.assertEqual(events[1].after_json["decision_state"], "included")
            self.assertTrue(all(event.occurred_at for event in events))

    def test_history_endpoint_returns_complete_newest_first_actor_timeline(self):
        self.assertEqual(self.decide(self.conditional_id, "excluded", "Scope removed").status_code, 200)
        self.assertEqual(self.decide(self.conditional_id, "included", "Scope restored").status_code, 200)

        response = self.client.get(
            f"/api/v2/projects/{self.project_id}/tasks/{self.conditional_id}/applicability-decisions"
        )
        self.assertEqual(response.status_code, 200, response.text)
        history = response.json()
        self.assertEqual(len(history), 2)
        self.assertEqual([item["decision_state"] for item in history], ["included", "excluded"])
        self.assertEqual([item["reason"] for item in history], ["Scope restored", "Scope removed"])
        self.assertEqual(history[0]["previous_decision_state"], "excluded")
        self.assertEqual(history[0]["actor_user_id"], str(ADMIN_ID))
        self.assertEqual(history[0]["actor_name"], "Admin")
        self.assertTrue(all(item["decided_at"] for item in history))

    def test_summary_counts_follow_decisions_and_template_source_is_unchanged(self):
        initial = self.client.get(f"/api/v2/projects/{self.project_id}/template-review/summary")
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual((initial.json()["included"], initial.json()["excluded"]), (2, 0))

        self.assertEqual(self.decide(self.conditional_id, "excluded", "Scope removed").status_code, 200)
        excluded = self.client.get(f"/api/v2/projects/{self.project_id}/template-review/summary").json()
        self.assertEqual((excluded["included"], excluded["excluded"]), (1, 1))

        self.assertEqual(self.decide(self.conditional_id, "included", "Scope restored").status_code, 200)
        included = self.client.get(f"/api/v2/projects/{self.project_id}/template-review/summary").json()
        self.assertEqual((included["included"], included["excluded"]), (2, 0))

        with self.Session() as session:
            project_task = session.get(V2ProjectTask, self.conditional_id)
            source_task = session.get(V2TemplateTask, project_task.template_task_id)
            source_version = session.get(V2TemplateVersion, project_task.template_version_id)
            self.assertEqual(source_task.code, "T098")
            self.assertEqual(source_task.applicability, "conditional")
            self.assertEqual((source_task.planned_start_day, source_task.planned_end_day), (45, 45))
            self.assertEqual(source_version.content_hash, "applicability-test")
            self.assertEqual(source_version.status, "published")

    def test_assigned_pm_can_read_decisions_but_not_make_them(self):
        """Scope decisions are Admin's. The assigned PM keeps read access so
        they can see what was excluded from their project and why."""
        history_url = f"/api/v2/projects/{self.project_id}/tasks/{self.conditional_id}/applicability-decisions"
        self.actor = self.users["pm"]
        response = self.decide(self.conditional_id, "excluded", "PM decision")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("Only Admin", response.json()["detail"])
        self.assertEqual(self.client.get(history_url).status_code, 200)

    def test_unrelated_roles_can_neither_read_nor_decide(self):
        history_url = f"/api/v2/projects/{self.project_id}/tasks/{self.conditional_id}/applicability-decisions"
        for key in ("other_pm", "supervisor", "super_admin"):
            with self.subTest(role=key):
                self.actor = self.users[key]
                response = self.decide(self.conditional_id, "included", "Not permitted")
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(self.client.get(history_url).status_code, 403)

    def test_task_from_another_project_is_not_exposed(self):
        response = self.client.post(
            f"/api/v2/projects/{self.project_id}/tasks/{uuid.uuid4()}/applicability-decisions",
            json={"decision": "excluded", "reason": "Not found"},
        )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
