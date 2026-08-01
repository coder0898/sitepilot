from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.models import UserRole
from app.routes.execution_v2 import serialize_legacy_execution_templates


class LegacyExecutionTemplateLeakageTests(unittest.TestCase):
    def setUp(self):
        self.active_id = uuid.uuid4()
        self.archived_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        self.templates = [
            SimpleNamespace(
                id=self.active_id,
                name="Active legacy blueprint",
                project_type="Interior",
                duration_days=3,
                active=True,
                created_at=now,
                updated_at=now,
            ),
            SimpleNamespace(
                id=self.archived_id,
                name="Archived legacy blueprint",
                project_type="Interior",
                duration_days=3,
                active=False,
                created_at=now,
                updated_at=now,
            ),
        ]
        self.tasks = {
            self.active_id: [self._task()],
            self.archived_id: [self._task()],
        }
        self.counts = {self.active_id: 2, self.archived_id: 1}

    @staticmethod
    def _task():
        return SimpleNamespace(
            id=uuid.uuid4(),
            day_no=1,
            title="Legacy task",
            category="Civil",
            category_id=None,
            subcategory_id=None,
            priority="normal",
            instructions=None,
            materials_required=None,
            material_reminder=False,
            reminder_lead_days=1,
        )

    def test_super_admin_keeps_allowed_legacy_management_behavior(self):
        result = serialize_legacy_execution_templates(
            self.templates, self.tasks, self.counts, UserRole.super_admin
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["used_project_count"], 2)
        self.assertIn("can_delete", result[0])
        self.assertIn("created_at", result[0])

    def test_admin_and_pm_receive_only_active_legacy_project_creation_data(self):
        for role in (UserRole.admin, UserRole.project_manager):
            with self.subTest(role=role):
                result = serialize_legacy_execution_templates(
                    self.templates, self.tasks, self.counts, role
                )
                self.assertEqual([item["id"] for item in result], [str(self.active_id)])
                self.assertEqual(len(result[0]["tasks"]), 1)
                for sensitive_key in ("used_project_count", "can_delete", "created_at", "updated_at"):
                    self.assertNotIn(sensitive_key, result[0])

    def test_supervisor_and_internal_employee_receive_no_template_payload(self):
        for role in (UserRole.supervisor, UserRole.internal_employee):
            with self.subTest(role=role):
                self.assertEqual(
                    serialize_legacy_execution_templates(self.templates, self.tasks, self.counts, role),
                    [],
                )

    def test_legacy_route_does_not_import_or_query_governed_v2_template_models(self):
        source = (
            Path(__file__).resolve().parents[1] / "app" / "routes" / "execution_v2.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "V2Template",
            "V2TemplateVersion",
            "V2TemplateTask",
            "V2TemplateTaskDependency",
            "V2TemplateExternalGate",
            "v2_template_versions",
            "v2_template_tasks",
            "/api/v2/templates",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
