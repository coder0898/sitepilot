from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import User, UserRole
from app.routes.templates_v2 import router
from app.services.template_audit import TemplateAuditAction
from app.services.template_mutation_access import concurrency_token
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)

ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class TemplateDependencyCommandApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

        for table in (
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                session.scalar(select(V2Template.id).limit(1))
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)
        self.audit_patch = patch(
            "app.services.template_dependency_commands.write_template_audit_event"
        )
        self.audit_writer = self.audit_patch.start()
        self.set_role(UserRole.super_admin)

    def tearDown(self):
        self.audit_patch.stop()
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            template = V2Template(code="DEP", name="Dependencies")
            other_template = V2Template(code="OTHER", name="Other")
            session.add_all([template, other_template])
            session.flush()
            draft = V2TemplateVersion(
                template_id=template.id,
                version_no=2,
                status="draft",
                duration_days=45,
                is_current_published=False,
                created_by=ACTOR_ID,
                updated_at=datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc),
            )
            published = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="published",
                is_current_published=True,
                created_by=ACTOR_ID,
                published_by=ACTOR_ID,
                published_at=datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc),
            )
            other = V2TemplateVersion(
                template_id=other_template.id,
                version_no=1,
                status="draft",
                duration_days=45,
                is_current_published=False,
                created_by=ACTOR_ID,
            )
            session.add_all([draft, published, other])
            session.flush()

            tasks = []
            for idx in range(1, 5):
                tasks.append(
                    V2TemplateTask(
                        template_version_id=draft.id,
                        code=f"T{idx:03d}",
                        sequence_no=idx,
                        title=f"Task {idx}",
                        schedule_classification="execution",
                        planned_start_day=idx,
                        planned_end_day=idx,
                        applicability="mandatory",
                        evidence_required=False,
                        duration_days=1,
                    )
                )
            published_task = V2TemplateTask(
                template_version_id=published.id,
                code="T001",
                sequence_no=1,
                title="Published task",
                schedule_classification="execution",
                planned_start_day=1,
                planned_end_day=1,
                applicability="mandatory",
                evidence_required=False,
                duration_days=1,
            )
            other_task = V2TemplateTask(
                template_version_id=other.id,
                code="T001",
                sequence_no=1,
                title="Other task",
                schedule_classification="execution",
                planned_start_day=1,
                planned_end_day=1,
                applicability="mandatory",
                evidence_required=False,
                duration_days=1,
            )
            session.add_all([*tasks, published_task, other_task])
            session.flush()
            existing = V2TemplateTaskDependency(
                template_version_id=draft.id,
                predecessor_task_id=tasks[0].id,
                successor_task_id=tasks[1].id,
                dependency_type="finish_to_start",
                blocking=True,
                rule_text="Task 1 before Task 2.",
                sequence_no=1,
            )
            session.add(existing)
            session.flush()

            self.draft_id = draft.id
            self.published_id = published.id
            self.other_id = other.id
            self.task_ids = [task.id for task in tasks]
            self.published_task_id = published_task.id
            self.other_task_id = other_task.id
            self.existing_id = existing.id

    def set_role(self, role: UserRole | None):
        self.app.dependency_overrides.pop(current_user, None)
        if role is not None:
            self.app.dependency_overrides[current_user] = lambda: User(
                id=ACTOR_ID,
                name=f"{role.value} tester",
                email=f"{role.value}@example.com",
                role=role,
                active=True,
            )

    def revision(self, version_id=None):
        with self.Session() as session:
            return concurrency_token(
                session.get(V2TemplateVersion, version_id or self.draft_id)
            )

    def payload(self, **overrides):
        payload = {
            "predecessor_task_id": str(self.task_ids[1]),
            "successor_task_id": str(self.task_ids[2]),
            "dependency_type": "finish_to_start",
            "blocking": True,
            "rule_text": "Task 2 before Task 3.",
            "sequence_no": 2,
            "revision_token": self.revision(),
        }
        payload.update(overrides)
        return payload

    def test_create_each_supported_type(self):
        first = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(),
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["dependency"]["dependency_type"], "finish_to_start")
        second = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(
                predecessor_task_id=str(self.task_ids[2]),
                successor_task_id=str(self.task_ids[3]),
                dependency_type="start_to_start",
                blocking=False,
                rule_text="Task 4 may start after Task 3 starts.",
                sequence_no=3,
                revision_token=first.json()["revision_token"],
            ),
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["dependency"]["dependency_type"], "start_to_start")
        self.assertFalse(second.json()["dependency"]["blocking"])

    def test_reject_missing_and_cross_version_tasks(self):
        missing = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(successor_task_id=str(uuid.uuid4())),
        )
        self.assertEqual(missing.status_code, 422)
        self.assertIn("does not exist", missing.json()["detail"]["message"])
        cross = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(successor_task_id=str(self.other_task_id)),
        )
        self.assertEqual(cross.status_code, 422)
        self.assertIn("another template version", cross.json()["detail"]["message"])
        self.audit_writer.assert_not_called()

    def test_reject_self_duplicate_and_unsupported_type(self):
        self_dep = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(
                predecessor_task_id=str(self.task_ids[2]),
                successor_task_id=str(self.task_ids[2]),
            ),
        )
        self.assertEqual(self_dep.status_code, 422)
        duplicate = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(
                predecessor_task_id=str(self.task_ids[0]),
                successor_task_id=str(self.task_ids[1]),
                sequence_no=8,
            ),
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["detail"]["code"], "template_dependency_exists")
        unsupported = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(dependency_type="finish_to_finish"),
        )
        self.assertEqual(unsupported.status_code, 422)

    def test_reject_cycle(self):
        response = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(
                predecessor_task_id=str(self.task_ids[1]),
                successor_task_id=str(self.task_ids[0]),
            ),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "template_dependency_cycle")

    def test_update_relationship_safely_and_audit(self):
        response = self.client.patch(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies/{self.existing_id}",
            json={
                "revision_token": self.revision(),
                "successor_task_id": str(self.task_ids[2]),
                "dependency_type": "start_to_start",
                "blocking": False,
                "rule_text": "Task 3 may start after Task 1 starts.",
                "sequence_no": 4,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()["dependency"]
        self.assertEqual(body["successor_task_id"], str(self.task_ids[2]))
        self.assertEqual(body["dependency_type"], "start_to_start")
        self.assertFalse(body["blocking"])
        audit = self.audit_writer.call_args.args[1]
        self.assertEqual(audit.action, TemplateAuditAction.TEMPLATE_DEPENDENCY_UPDATED)
        self.assertIsNotNone(audit.before_json)
        self.assertEqual(audit.after_json["dependency_type"], "start_to_start")

    def test_delete_succeeds(self):
        response = self.client.delete(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies/{self.existing_id}",
            params={"revision_token": self.revision()},
        )
        self.assertEqual(response.status_code, 200)
        with self.Session() as session:
            self.assertIsNone(session.get(V2TemplateTaskDependency, self.existing_id))
        audit = self.audit_writer.call_args.args[1]
        self.assertEqual(audit.action, TemplateAuditAction.TEMPLATE_DEPENDENCY_DELETED)

    def test_published_version_rejects_all_mutations(self):
        create = self.client.post(
            f"/api/v2/templates/versions/{self.published_id}/dependencies",
            json=self.payload(
                predecessor_task_id=str(self.published_task_id),
                successor_task_id=str(self.published_task_id),
                revision_token=self.revision(self.published_id),
            ),
        )
        self.assertEqual(create.status_code, 409)
        self.assertEqual(create.json()["detail"]["code"], "template_version_immutable")
        patch_response = self.client.patch(
            f"/api/v2/templates/versions/{self.published_id}/dependencies/{self.existing_id}",
            json={"revision_token": self.revision(self.published_id), "blocking": False},
        )
        self.assertEqual(patch_response.status_code, 409)
        delete = self.client.delete(
            f"/api/v2/templates/versions/{self.published_id}/dependencies/{self.existing_id}",
            params={"revision_token": self.revision(self.published_id)},
        )
        self.assertEqual(delete.status_code, 409)

    def test_stale_revision_rejected_without_write_or_audit(self):
        stale = self.revision()
        with self.Session.begin() as session:
            version = session.get(V2TemplateVersion, self.draft_id)
            version.updated_at = datetime(2026, 7, 28, 7, 0, tzinfo=timezone.utc)
        response = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/dependencies",
            json=self.payload(revision_token=stale),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "stale_template_version")
        with self.Session() as session:
            count = session.scalar(
                select(func.count()).select_from(V2TemplateTaskDependency).where(
                    V2TemplateTaskDependency.template_version_id == self.draft_id
                )
            )
            self.assertEqual(count, 1)
        self.audit_writer.assert_not_called()

    def test_non_super_admin_roles_forbidden(self):
        for role in (
            UserRole.admin,
            UserRole.project_manager,
            UserRole.supervisor,
            UserRole.internal_employee,
        ):
            with self.subTest(role=role):
                self.set_role(role)
                response = self.client.post(
                    f"/api/v2/templates/versions/{self.draft_id}/dependencies",
                    json=self.payload(),
                )
                self.assertEqual(response.status_code, 403)
        self.set_role(UserRole.super_admin)


if __name__ == "__main__":
    unittest.main()
