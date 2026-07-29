from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.routes.projects_v2 import router
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


class DraftProjectCreateApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        # Create only the production tables touched by this capability.
        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2AuditEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ADMIN_ID,
            name="Admin",
            email="admin@example.com",
            role=UserRole.admin,
            active=True,
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID,
                name="Supervisor",
                email="supervisor@example.com",
                role=UserRole.supervisor,
                active=True,
            )
            session.add_all([admin, pm, supervisor])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID,
                    employee_code="SUP-001",
                    designation="Supervisor",
                    availability="available",
                ),
            ])
            template = V2Template(code="WORKVED-45", name="Workved 45 Day")
            session.add(template)
            session.flush()
            published = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="published-hash",
                is_current_published=True,
                created_by=ADMIN_ID,
                published_by=ADMIN_ID,
                published_at=datetime.now(timezone.utc),
            )
            draft = V2TemplateVersion(
                template_id=template.id,
                version_no=2,
                status="draft",
                duration_days=45,
                is_current_published=False,
                created_by=ADMIN_ID,
            )
            session.add_all([published, draft])
            session.flush()
            session.add(
                V2TemplateTask(
                    template_version_id=published.id,
                    code="T001",
                    sequence_no=1,
                    title="Existing template task",
                    schedule_classification="execution",
                    planned_start_day=1,
                    planned_end_day=1,
                    applicability="mandatory",
                    evidence_required=False,
                    duration_days=1,
                )
            )
            self.published_version_id = published.id
            self.draft_version_id = draft.id

    def payload(self, **overrides):
        payload = {
            "project_name": "Futurex Fitout",
            "client": "Example Client",
            "location": "Mumbai",
            "proposed_start_date": "2026-08-01",
            "pm_user_id": str(PM_ID),
            "supervisor_user_id": str(SUPERVISOR_ID),
            "template_version_id": str(self.published_version_id),
        }
        payload.update(overrides)
        return payload


    def test_published_template_reference_endpoint_returns_current_version_for_admin_and_super_admin(self):
        for role in (UserRole.admin, UserRole.super_admin):
            self.app.dependency_overrides[current_user] = lambda role=role: User(
                id=ADMIN_ID, name=role.value, email=f"{role.value}@example.com", role=role, active=True
            )
            response = self.client.get("/api/v2/projects/published-template-versions")
            self.assertEqual(response.status_code, 200, response.text)
            items = response.json()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["version_id"], str(self.published_version_id))
            self.assertEqual(items[0]["status"], "published")
            self.assertTrue(items[0]["is_current_published"])

    def test_published_template_reference_endpoint_rejects_execution_roles(self):
        for role in (UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee):
            self.app.dependency_overrides[current_user] = lambda role=role: User(
                id=uuid.uuid4(), name=role.value, email=f"{role.value}@example.com", role=role, active=True
            )
            response = self.client.get("/api/v2/projects/published-template-versions")
            self.assertEqual(response.status_code, 403, (role, response.text))

    def test_valid_create_is_draft_persists_references_creates_no_tasks_and_audits_once(self):
        response = self.client.post("/api/v2/projects", json=self.payload())
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["template_version_id"], str(self.published_version_id))
        self.assertTrue(body["code"].startswith("PRJ-20260801-"))
        self.assertEqual({item["project_role"] for item in body["memberships"]}, {"project_manager", "site_supervisor"})

        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2Project)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2ProjectMembership)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2AuditEvent)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2TemplateTask)), 1)
            audit = session.scalar(select(V2AuditEvent))
            self.assertEqual(audit.action, "PROJECT_CREATED")
            self.assertEqual(audit.actor_user_id, ADMIN_ID)
            self.assertEqual(audit.after_json["generated_task_count"], 0)

    def test_inactive_or_wrong_role_accountable_users_are_rejected_without_writes(self):
        cases = []
        with self.Session.begin() as session:
            pm = session.get(User, PM_ID)
            pm.active = False
        cases.append(self.payload())

        for payload in cases:
            response = self.client.post("/api/v2/projects", json=payload)
            self.assertEqual(response.status_code, 422)
        with self.Session.begin() as session:
            session.get(User, PM_ID).active = True
            session.get(User, SUPERVISOR_ID).role = UserRole.internal_employee
        response = self.client.post("/api/v2/projects", json=self.payload())
        self.assertEqual(response.status_code, 422)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2Project)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2AuditEvent)), 0)

    def test_draft_template_is_rejected(self):
        response = self.client.post(
            "/api/v2/projects",
            json=self.payload(template_version_id=str(self.draft_version_id)),
        )
        self.assertEqual(response.status_code, 422)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2Project)), 0)

    def test_super_admin_fallback_can_create(self):
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ADMIN_ID, name="Super Admin", email="superadmin@example.com", role=UserRole.super_admin, active=True
        )
        response = self.client.post("/api/v2/projects", json=self.payload())
        self.assertEqual(response.status_code, 201, response.text)

    def test_non_admin_roles_cannot_create(self):
        for role in (UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee):
            self.app.dependency_overrides[current_user] = lambda role=role: User(
                id=uuid.uuid4(), name=role.value, email=f"{role.value}@example.com", role=role, active=True
            )
            response = self.client.post("/api/v2/projects", json=self.payload())
            self.assertEqual(response.status_code, 403, (role, response.text))

    def test_audit_failure_rolls_back_project_and_memberships(self):
        def fail_audit(_mapper, _connection, _target):
            raise RuntimeError("audit write failed")

        event.listen(V2AuditEvent, "before_insert", fail_audit)
        try:
            with self.assertRaises(RuntimeError):
                self.client.post("/api/v2/projects", json=self.payload())
        finally:
            event.remove(V2AuditEvent, "before_insert", fail_audit)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2Project)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2ProjectMembership)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2AuditEvent)), 0)

    def test_unauthenticated_create_is_rejected(self):
        self.app.dependency_overrides.pop(current_user, None)
        response = self.client.post("/api/v2/projects", json=self.payload())
        self.assertEqual(response.status_code, 401, response.text)

    def test_create_accepts_existing_employee_profile_ids_for_selector_compatibility(self):
        with self.Session() as session:
            pm_profile = session.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == PM_ID))
            supervisor_profile = session.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == SUPERVISOR_ID))
            pm_employee_id = pm_profile.id
            supervisor_employee_id = supervisor_profile.id
        response = self.client.post(
            "/api/v2/projects",
            json=self.payload(
                pm_user_id=str(pm_employee_id),
                supervisor_user_id=str(supervisor_employee_id),
            ),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["template_version_id"], str(self.published_version_id))
        with self.Session() as session:
            audit = session.scalar(select(V2AuditEvent))
            self.assertEqual(audit.after_json["project_manager_user_id"], str(PM_ID))
            self.assertEqual(audit.after_json["supervisor_user_id"], str(SUPERVISOR_ID))

    def test_admin_can_attach_published_template_to_existing_draft_without_generating_tasks(self):
        with self.Session.begin() as session:
            project = V2Project(
                code="LEGACY-DRAFT-001",
                name="Existing draft",
                client_name="Client",
                site_address="Mumbai",
                start_date=date(2026, 8, 1),
                status="draft",
                created_by=ADMIN_ID,
            )
            session.add(project)
            session.flush()
            project_id = project.id
        response = self.client.patch(
            f"/api/v2/projects/{project_id}",
            json={
                "template_version_id": str(self.published_version_id),
                "reason": "Attach approved template",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["template_version_id"], str(self.published_version_id))
        self.assertTrue(response.json()["setup"]["has_template"])
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2TemplateTask)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2AuditEvent)), 1)

    def test_existing_draft_rejects_draft_template_attachment(self):
        with self.Session.begin() as session:
            project = V2Project(
                code="LEGACY-DRAFT-002",
                name="Existing draft",
                client_name="Client",
                site_address="Mumbai",
                start_date=date(2026, 8, 1),
                status="draft",
                created_by=ADMIN_ID,
            )
            session.add(project)
            session.flush()
            project_id = project.id
        response = self.client.patch(
            f"/api/v2/projects/{project_id}",
            json={"template_version_id": str(self.draft_version_id), "reason": "Attach template"},
        )
        self.assertEqual(response.status_code, 422, response.text)
        with self.Session() as session:
            self.assertIsNone(session.get(V2Project, project_id).template_version_id)


if __name__ == "__main__":
    unittest.main()
