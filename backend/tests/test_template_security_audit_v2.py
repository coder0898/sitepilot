from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import current_user
from app.database import get_db
from app.models import User, UserRole
from app.routes.templates_v2 import router
from app.services.template_audit import (
    TemplateAuditAction,
    TemplateAuditWrite,
    write_template_audit_event,
)
from app.template_dependency_mutation_schemas import TemplateDependencyCreateRequest
from app.template_gate_mutation_schemas import TemplateGateCreateRequest
from app.template_mutation_schemas import TemplateCreateRequest
from app.template_publish_schemas import TemplatePublishRequest
from app.template_task_mutation_schemas import TemplateTaskCreateRequest


VERSION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
ENTITY_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
TASK_A = uuid.UUID("33333333-3333-4333-8333-333333333333")
TASK_B = uuid.UUID("44444444-4444-4444-8444-444444444444")


class MutationRouteAuthorizationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: Mock()
        cls.app = app
        cls.client = TestClient(app)

        token = "2026-07-28T10:00:00Z"
        cls.mutation_requests = [
            ("post", "/api/v2/templates", {
                "code": "SEC", "name": "Security", "duration_days": 45,
                "change_note": "Create",
            }),
            ("post", f"/api/v2/templates/versions/{VERSION_ID}/clone", {
                "change_note": "Clone",
            }),
            ("post", f"/api/v2/templates/versions/{VERSION_ID}/tasks", {
                "code": "T001", "sequence_no": 1, "title": "Task",
                "schedule_classification": "execution", "planned_start_day": 1,
                "planned_end_day": 1, "applicability": "mandatory",
                "evidence_required": False, "duration_days": 1,
                "revision_token": token,
            }),
            ("patch", f"/api/v2/templates/versions/{VERSION_ID}/tasks/{ENTITY_ID}", {
                "title": "Updated", "revision_token": token,
            }),
            ("post", f"/api/v2/templates/versions/{VERSION_ID}/tasks/reorder", {
                "revision_token": token,
                "items": [{"task_id": str(ENTITY_ID), "sequence_no": 1}],
            }),
            ("delete", f"/api/v2/templates/versions/{VERSION_ID}/tasks/{ENTITY_ID}?revision_token={token}", None),
            ("post", f"/api/v2/templates/versions/{VERSION_ID}/dependencies", {
                "predecessor_task_id": str(TASK_A), "successor_task_id": str(TASK_B),
                "dependency_type": "finish_to_start", "blocking": True,
                "rule_text": "Complete first", "sequence_no": 1,
                "revision_token": token,
            }),
            ("patch", f"/api/v2/templates/versions/{VERSION_ID}/dependencies/{ENTITY_ID}", {
                "blocking": False, "revision_token": token,
            }),
            ("delete", f"/api/v2/templates/versions/{VERSION_ID}/dependencies/{ENTITY_ID}?revision_token={token}", None),
            ("post", f"/api/v2/templates/versions/{VERSION_ID}/gates", {
                "code": "E001", "approval_name": "Approval", "sequence_no": 1,
                "mapping_classification": "unmapped", "task_ids": [],
                "revision_token": token,
            }),
            ("patch", f"/api/v2/templates/versions/{VERSION_ID}/gates/{ENTITY_ID}", {
                "approval_name": "Updated", "revision_token": token,
            }),
            ("put", f"/api/v2/templates/versions/{VERSION_ID}/gates/{ENTITY_ID}/mappings", {
                "mapping_classification": "exact", "task_ids": [str(TASK_A)],
                "revision_token": token,
            }),
            ("delete", f"/api/v2/templates/versions/{VERSION_ID}/gates/{ENTITY_ID}?revision_token={token}", None),
            ("post", f"/api/v2/templates/versions/{VERSION_ID}/validate", None),
            ("post", f"/api/v2/templates/versions/{VERSION_ID}/publish", {
                "revision_token": token, "change_note": "Publish",
            }),
        ]

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def set_role(self, role: UserRole | None):
        self.app.dependency_overrides.pop(current_user, None)
        if role is not None:
            self.app.dependency_overrides[current_user] = lambda: User(
                id=uuid.uuid4(), name="Security actor", email="security@example.com",
                role=role, active=True,
            )

    def send(self, method: str, url: str, payload: dict | None):
        call = getattr(self.client, method)
        return call(url, json=payload) if payload is not None else call(url)

    def test_every_mutation_route_rejects_every_non_super_admin_role(self):
        for role in (
            UserRole.admin,
            UserRole.project_manager,
            UserRole.supervisor,
            UserRole.internal_employee,
        ):
            self.set_role(role)
            for method, url, payload in self.mutation_requests:
                with self.subTest(role=role, method=method, url=url):
                    response = self.send(method, url, payload)
                    self.assertEqual(response.status_code, 403, response.text)

    def test_every_mutation_route_keeps_unauthenticated_401(self):
        self.set_role(None)
        for method, url, payload in self.mutation_requests:
            with self.subTest(method=method, url=url):
                response = self.send(method, url, payload)
                self.assertEqual(response.status_code, 401, response.text)


class MassAssignmentSecurityTests(unittest.TestCase):
    def assert_forbidden_extra(self, model, payload):
        for protected in (
            {"status": "published"},
            {"published_by": str(uuid.uuid4())},
            {"content_hash": "forged"},
            {"actor_user_id": str(uuid.uuid4())},
            {"action": "template_version_published"},
            {"before_json": {"forged": True}},
        ):
            with self.subTest(model=model.__name__, protected=protected):
                with self.assertRaises(ValidationError) as raised:
                    model.model_validate({**payload, **protected})
                errors = raised.exception.errors()
                self.assertTrue(any(error["type"] == "extra_forbidden" for error in errors))

    def test_all_mutation_request_models_reject_protected_extra_fields(self):
        token = "2026-07-28T10:00:00Z"
        cases = [
            (TemplateCreateRequest, {
                "code": "SEC", "name": "Security", "duration_days": 45,
            }),
            (TemplateTaskCreateRequest, {
                "code": "T001", "sequence_no": 1, "title": "Task",
                "schedule_classification": "execution", "planned_start_day": 1,
                "planned_end_day": 1, "applicability": "mandatory",
                "evidence_required": False, "duration_days": 1,
                "revision_token": token,
            }),
            (TemplateDependencyCreateRequest, {
                "predecessor_task_id": TASK_A, "successor_task_id": TASK_B,
                "dependency_type": "finish_to_start", "blocking": True,
                "rule_text": "Complete first", "sequence_no": 1,
                "revision_token": token,
            }),
            (TemplateGateCreateRequest, {
                "code": "E001", "approval_name": "Approval", "sequence_no": 1,
                "mapping_classification": "unmapped", "task_ids": [],
                "revision_token": token,
            }),
            (TemplatePublishRequest, {
                "revision_token": token, "change_note": "Publish",
            }),
        ]
        for model, payload in cases:
            self.assert_forbidden_extra(model, payload)

    def test_audit_writer_uses_server_supplied_actor_and_action(self):
        db = Mock()
        actor_id = uuid.uuid4()
        write = TemplateAuditWrite(
            action=TemplateAuditAction.TEMPLATE_TASK_CREATED,
            entity_type="template_task",
            entity_id=uuid.uuid4(),
            actor_user_id=actor_id,
            reason="Server-created audit event.",
            after_json={"title": "Task"},
        )
        event = write_template_audit_event(db, write)
        self.assertEqual(event.actor_user_id, actor_id)
        self.assertEqual(event.action, TemplateAuditAction.TEMPLATE_TASK_CREATED)
        db.add.assert_called_once_with(event)


class BrowserAndLegacyBoundaryTests(unittest.TestCase):
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def test_supabase_browser_roles_have_no_v2_template_table_privileges(self):
        migration = (self.repo_root() / "supabase/migrations/20260725083225_v2_template_schema.sql").read_text()
        tables = (
            "v2_templates",
            "v2_template_versions",
            "v2_template_tasks",
            "v2_template_task_dependencies",
            "v2_template_external_gates",
            "v2_template_external_gate_tasks",
        )
        for table in tables:
            self.assertIn(
                f"revoke all on table siteops_v2.{table} from anon, authenticated;",
                migration,
            )

    def test_frontend_uses_supabase_only_for_auth_not_v2_template_writes(self):
        frontend = self.repo_root() / "frontend/src"
        offenders = []
        for path in frontend.rglob("*.js*"):
            text = path.read_text(encoding="utf-8")
            if ".from(" in text and "v2_template" in text:
                offenders.append(str(path.relative_to(self.repo_root())))
        self.assertEqual(offenders, [])

    # The legacy template workspace (routes/execution_v2.py) used to be
    # guarded here against importing or mutating governed V2 template
    # models. That module and its /api/v2/execution router were deleted
    # once the legacy execution tables were confirmed empty and orphaned
    # from the UI, so the boundary it policed no longer exists.


if __name__ == "__main__":
    unittest.main()
