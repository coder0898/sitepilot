from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import User, UserRole
from app.repositories.template_repository import _task_validation_issues
from app.routes.templates_v2 import router
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)


ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class TemplateListApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def register_postgres_compatibility_functions(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function(
                "btrim",
                1,
                lambda value: value.strip() if value is not None else None,
            )

        for table in (
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
        ):
            table.create(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls._seed()

        cls.app = FastAPI()
        cls.app.include_router(router)

        def override_db():
            with cls.Session() as session:
                yield session

        cls.app.dependency_overrides[get_db] = override_db
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.engine.dispose()

    @classmethod
    def _seed(cls):
        with cls.Session.begin() as session:
            alpha = V2Template(
                code="WORKVED-45",
                name="Alpha Workved Template",
                description="Approved execution baseline.",
            )
            beta = V2Template(code="BETA-02", name="Beta Published Template")
            secret = V2Template(code="SECRET-03", name="Secret Draft Template")
            session.add_all([alpha, beta, secret])
            session.flush()

            now = datetime.now(timezone.utc)
            published = V2TemplateVersion(
                template_id=alpha.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="alpha-published",
                is_current_published=True,
                created_by=ACTOR_ID,
                published_by=ACTOR_ID,
                published_at=now,
            )
            beta_published = V2TemplateVersion(
                template_id=beta.id,
                version_no=2,
                status="published",
                duration_days=30,
                content_hash="beta-published",
                is_current_published=True,
                created_by=ACTOR_ID,
                published_by=ACTOR_ID,
                published_at=now,
            )
            draft = V2TemplateVersion(
                template_id=secret.id,
                version_no=3,
                status="draft",
                duration_days=45,
                content_hash="secret-draft",
                is_current_published=False,
                created_by=ACTOR_ID,
            )
            session.add_all([published, beta_published, draft])
            session.flush()
            cls.published_id = published.id
            cls.draft_id = draft.id

            tasks = [cls._task(published.id, f"T{sequence:03d}", sequence) for sequence in range(1, 100)]
            session.add_all(tasks + [cls._task(draft.id, "D001", 1)])
            session.flush()
            session.add_all(
                [
                    V2TemplateTaskDependency(
                        template_version_id=published.id,
                        predecessor_task_id=tasks[0].id,
                        successor_task_id=tasks[1].id,
                        dependency_type="finish_to_start",
                        blocking=True,
                        sequence_no=1,
                    ),
                    V2TemplateTaskDependency(
                        template_version_id=published.id,
                        predecessor_task_id=tasks[1].id,
                        successor_task_id=tasks[2].id,
                        dependency_type="finish_to_start",
                        blocking=True,
                        sequence_no=2,
                    ),
                ]
            )
            exact_gate = V2TemplateExternalGate(
                template_version_id=published.id,
                code="E001",
                approval_name="Exact approval",
                mapping_classification="exact",
                requires_configuration=False,
                sequence_no=1,
            )
            broad_gate = V2TemplateExternalGate(
                template_version_id=published.id,
                code="E002",
                approval_name="Broad approval",
                mapping_classification="broad_text",
                broad_mapping_text="Relevant execution work",
                requires_configuration=True,
                sequence_no=2,
            )
            session.add_all([exact_gate, broad_gate])
            session.flush()
            session.add(
                V2TemplateExternalGateTask(
                    gate_id=exact_gate.id,
                    template_task_id=tasks[0].id,
                )
            )

    @staticmethod
    def _task(version_id, code, sequence):
        pre_activation = sequence <= 7 or code.startswith("D")
        day = None if pre_activation else min(45, sequence - 7)
        return V2TemplateTask(
            template_version_id=version_id,
            code=code,
            sequence_no=sequence,
            title=f"Template task {code}",
            description=f"Approved description for {code}",
            schedule_classification="pre_activation" if pre_activation else "execution",
            planned_start_day=day,
            planned_end_day=day,
            phase="Pre-Activation" if pre_activation else ("Closeout" if sequence >= 97 else "Execution"),
            category="Approvals" if pre_activation else ("Handover" if sequence >= 97 else "Site Works"),
            applicability="conditional" if code == "T098" else "mandatory",
            task_class="control" if pre_activation else "work",
            task_kind="approval" if pre_activation else "execution",
            evidence_required=not pre_activation,
            duration_days=1,
        )

    def set_role(self, role: UserRole | None):
        self.app.dependency_overrides.pop(current_user, None)
        if role is not None:
            self.app.dependency_overrides[current_user] = lambda: User(
                id=uuid.uuid4(),
                name=f"{role.value} tester",
                email=f"{role.value}@example.com",
                role=role,
                active=True,
            )

    def get(self, role: UserRole | None, params=None):
        self.set_role(role)
        return self.client.get("/api/v2/templates", params=params or {})

    def get_version_response(self, role: UserRole | None, version_id=None):
        self.set_role(role)
        return self.client.get(f"/api/v2/templates/versions/{version_id or self.published_id}")

    def get_tasks_response(self, role: UserRole | None, version_id=None, params=None):
        self.set_role(role)
        return self.client.get(
            f"/api/v2/templates/versions/{version_id or self.published_id}/tasks",
            params=params or {},
        )
    def test_super_admin_sees_draft_and_published(self):
        response = self.get(UserRole.super_admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pagination"]["total"], 3)
        self.assertEqual({row["status"] for row in response.json()["items"]}, {"draft", "published"})

    def test_admin_and_pm_receive_published_only(self):
        for role in (UserRole.admin, UserRole.project_manager):
            response = self.get(role)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["pagination"]["total"], 2)
            self.assertEqual({row["status"] for row in response.json()["items"]}, {"published"})

    def test_unsupported_roles_receive_403(self):
        for role in (UserRole.supervisor, UserRole.internal_employee):
            self.assertEqual(self.get(role).status_code, 403)

    def test_unauthenticated_request_receives_existing_401(self):
        response = self.get(None)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Login required.")

    def test_search_is_trimmed_case_insensitive_and_includes_version(self):
        by_name = self.get(UserRole.super_admin, {"search": "  ALPHA workved  "})
        by_code = self.get(UserRole.super_admin, {"search": "  beta-02 "})
        by_version = self.get(UserRole.super_admin, {"search": " 3 "})
        self.assertEqual([row["template_code"] for row in by_name.json()["items"]], ["WORKVED-45"])
        self.assertEqual([row["template_code"] for row in by_code.json()["items"]], ["BETA-02"])
        self.assertEqual([row["template_code"] for row in by_version.json()["items"]], ["SECRET-03"])

    def test_super_admin_status_filter(self):
        draft = self.get(UserRole.super_admin, {"status": "draft"})
        published = self.get(UserRole.super_admin, {"status": "published"})
        self.assertEqual(draft.json()["pagination"]["total"], 1)
        self.assertEqual({row["status"] for row in draft.json()["items"]}, {"draft"})
        self.assertEqual(published.json()["pagination"]["total"], 2)

    def test_admin_and_pm_status_cannot_expose_drafts(self):
        for role in (UserRole.admin, UserRole.project_manager):
            response = self.get(role, {"status": "draft"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["pagination"]["total"], 2)
            self.assertEqual({row["status"] for row in response.json()["items"]}, {"published"})

    def test_pagination_and_empty_result(self):
        first = self.get(UserRole.super_admin, {"page": 1, "page_size": 1}).json()
        empty = self.get(UserRole.super_admin, {"search": "does-not-exist"}).json()
        self.assertEqual(first["pagination"], {"page": 1, "page_size": 1, "total": 3, "total_pages": 3})
        self.assertEqual(len(first["items"]), 1)
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["pagination"]["total"], 0)
        self.assertEqual(empty["pagination"]["total_pages"], 0)

    def test_persisted_counts_and_current_published_marker(self):
        response = self.get(UserRole.admin, {"search": "WORKVED-45"})
        self.assertEqual(response.status_code, 200)
        row = response.json()["items"][0]
        self.assertEqual(row["task_count"], 99)
        self.assertEqual(row["dependency_count"], 2)
        self.assertEqual(row["gate_count"], 2)
        self.assertTrue(row["is_current_published"])
        self.assertEqual(row["duration_days"], 45)

    def test_version_and_task_access_per_role(self):
        for role in (UserRole.super_admin, UserRole.admin, UserRole.project_manager):
            self.assertEqual(self.get_version_response(role).status_code, 200)
            self.assertEqual(self.get_tasks_response(role).status_code, 200)
        self.assertEqual(self.get_version_response(UserRole.super_admin, self.draft_id).status_code, 200)
        for role in (UserRole.admin, UserRole.project_manager):
            self.assertEqual(self.get_version_response(role, self.draft_id).status_code, 404)
            self.assertEqual(self.get_tasks_response(role, self.draft_id).status_code, 404)
        for role in (UserRole.supervisor, UserRole.internal_employee):
            self.assertEqual(self.get_version_response(role).status_code, 403)
            self.assertEqual(self.get_tasks_response(role).status_code, 403)
        self.assertEqual(self.get_version_response(None).status_code, 401)
        self.assertEqual(self.get_tasks_response(None).status_code, 401)

    def test_version_summary_returns_identity_and_persisted_counts(self):
        payload = self.get_version_response(UserRole.admin).json()
        self.assertEqual(payload["template_code"], "WORKVED-45")
        self.assertEqual(payload["version_id"], str(self.published_id))
        self.assertEqual(payload["version_no"], 1)
        self.assertEqual(payload["status"], "published")
        self.assertTrue(payload["is_current_published"])
        self.assertEqual(payload["duration_days"], 45)
        self.assertEqual(payload["task_count"], 99)
        self.assertEqual(payload["dependency_count"], 2)
        self.assertEqual(payload["gate_count"], 2)
        self.assertIsNotNone(payload["created_at"])
        self.assertIsNotNone(payload["published_at"])

    def test_all_99_tasks_paginate_in_deterministic_schedule_order(self):
        first = self.get_tasks_response(UserRole.admin, params={"page": 1, "page_size": 20}).json()
        last = self.get_tasks_response(UserRole.admin, params={"page": 5, "page_size": 20}).json()
        all_tasks = self.get_tasks_response(UserRole.admin, params={"page_size": 100}).json()
        self.assertEqual(first["pagination"], {"page": 1, "page_size": 20, "total": 99, "total_pages": 5})
        self.assertEqual(len(last["items"]), 19)
        self.assertEqual([item["code"] for item in all_tasks["items"]], [f"T{i:03d}" for i in range(1, 100)])
        self.assertTrue(all(item["schedule_classification"] == "pre_activation" for item in all_tasks["items"][:7]))
        self.assertEqual(all_tasks["items"][7]["code"], "T008")
        self.assertEqual(all_tasks["items"][7]["planned_start_day"], 1)
        self.assertTrue(all(item["planned_start_day"] == 45 for item in all_tasks["items"][96:99]))
        self.assertEqual(all_tasks["items"][97]["applicability"], "conditional")
        self.assertTrue(all(item["validation_state"] == "valid" for item in all_tasks["items"]))

    def test_task_search_and_all_filters(self):
        search = self.get_tasks_response(UserRole.admin, params={"search": " description for t008 "}).json()
        pre_activation = self.get_tasks_response(UserRole.admin, params={"schedule_classification": "pre_activation"}).json()
        phase = self.get_tasks_response(UserRole.admin, params={"phase": " closeout "}).json()
        category = self.get_tasks_response(UserRole.admin, params={"category": " SITE WORKS "}).json()
        conditional = self.get_tasks_response(UserRole.admin, params={"applicability": "conditional"}).json()
        self.assertEqual([item["code"] for item in search["items"]], ["T008"])
        self.assertEqual(pre_activation["pagination"]["total"], 7)
        self.assertEqual(phase["pagination"]["total"], 3)
        self.assertEqual(category["pagination"]["total"], 89)
        self.assertEqual([item["code"] for item in conditional["items"]], ["T098"])

    def test_validation_reporting_lists_every_requested_problem_without_repair(self):
        invalid = SimpleNamespace(
            sequence_no=None,
            title=" ",
            schedule_classification="unsupported",
            planned_start_day=46,
            planned_end_day=2,
            applicability="optional",
        )
        issues = _task_validation_issues(invalid, duplicate_code_count=2, duplicate_sequence_count=2)
        self.assertEqual(
            issues,
            [
                "duplicate_code",
                "duplicate_sequence",
                "missing_sequence",
                "missing_title",
                "invalid_schedule_classification",
                "execution_day_out_of_range",
                "planned_start_after_end",
                "unsupported_applicability",
            ],
        )
        invalid.schedule_classification = "execution"
        invalid.planned_end_day = None
        issues = _task_validation_issues(invalid)
        self.assertIn("missing_execution_day", issues)
        self.assertIn("execution_day_out_of_range", issues)

    def test_task_endpoint_uses_constant_queries_without_n_plus_one(self):
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.get_tasks_response(UserRole.admin, params={"page_size": 100})
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 99)
        self.assertEqual(len(statements), 3)
        self.assertTrue(all("v2_template" in statement for statement in statements))
    def test_list_uses_two_selects_and_never_queries_legacy_templates(self):
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.get(UserRole.super_admin)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(statements), 2)
        self.assertTrue(all("v2_template" in statement for statement in statements))
        self.assertTrue(all("execution_template" not in statement for statement in statements))