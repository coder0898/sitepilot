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
from app.repositories.template_mutation_repository import TemplateMutationRepository
from app.routes.templates_v2 import router
from app.services.template_audit import TemplateAuditAction
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)


ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class TemplateCommandApiTests(unittest.TestCase):
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
        self._seed_source()

        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                # Mirror current_user: its lookup auto-starts the shared request transaction.
                session.scalar(select(func.count()).select_from(V2Template))
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)
        self.audit_patch = patch("app.services.template_commands.write_template_audit_event")
        self.audit_writer = self.audit_patch.start()

    def tearDown(self):
        self.audit_patch.stop()
        self.client.close()
        self.engine.dispose()

    def _seed_source(self):
        with self.Session.begin() as session:
            template = V2Template(
                code="WORKVED-45",
                name="Workved 45 Day",
                description="Published source.",
            )
            session.add(template)
            session.flush()
            version = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=45,
                change_note="Approved baseline.",
                content_hash="published-content-hash",
                is_current_published=True,
                created_by=ACTOR_ID,
                published_by=ACTOR_ID,
                published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            session.flush()
            task_one = V2TemplateTask(
                template_version_id=version.id,
                code="T001",
                sequence_no=1,
                title="Pre-activation approval",
                description="Approval task.",
                schedule_classification="pre_activation",
                planned_start_day=None,
                planned_end_day=None,
                phase="Pre-Activation",
                category="Approvals",
                applicability="mandatory",
                task_class="control",
                task_kind="approval",
                evidence_required=True,
                duration_days=1,
            )
            task_two = V2TemplateTask(
                template_version_id=version.id,
                code="T008",
                sequence_no=8,
                title="Execution starts",
                description="Day one task.",
                schedule_classification="execution",
                planned_start_day=1,
                planned_end_day=1,
                phase="Execution",
                category="Site Works",
                applicability="mandatory",
                task_class="work",
                task_kind="execution",
                evidence_required=False,
                duration_days=1,
            )
            session.add_all([task_one, task_two])
            session.flush()
            session.add(
                V2TemplateTaskDependency(
                    template_version_id=version.id,
                    predecessor_task_id=task_one.id,
                    successor_task_id=task_two.id,
                    dependency_type="finish_to_start",
                    blocking=True,
                    rule_text="Approval before execution.",
                    sequence_no=1,
                )
            )
            exact = V2TemplateExternalGate(
                template_version_id=version.id,
                code="E001",
                approval_name="Exact gate",
                external_party="Client",
                required_by_type="task",
                required_by_value="T008",
                mapping_classification="exact",
                broad_mapping_text=None,
                requires_configuration=False,
                sequence_no=1,
            )
            broad = V2TemplateExternalGate(
                template_version_id=version.id,
                code="E006",
                approval_name="Broad gate",
                external_party="Client",
                required_by_type="broad_text",
                required_by_value="T008 onwards",
                mapping_classification="broad_text",
                broad_mapping_text="T008 onwards",
                requires_configuration=True,
                sequence_no=2,
            )
            session.add_all([exact, broad])
            session.flush()
            session.add_all(
                [
                    V2TemplateExternalGateTask(gate_id=exact.id, template_task_id=task_two.id),
                    # Deliberately malformed source link: clone must not guess broad mappings.
                    V2TemplateExternalGateTask(gate_id=broad.id, template_task_id=task_two.id),
                ]
            )
            self.template_id = template.id
            self.source_version_id = version.id
            self.source_task_ids = {task_one.id, task_two.id}

            archived = V2TemplateVersion(
                template_id=template.id,
                version_no=9,
                status="archived",
                duration_days=45,
                is_current_published=False,
                created_by=ACTOR_ID,
            )
            session.add(archived)
            session.flush()
            self.archived_version_id = archived.id

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

    def post(self, path: str, payload: dict, role: UserRole | None = UserRole.super_admin):
        self.set_role(role)
        return self.client.post(path, json=payload)

    def test_new_template_and_initial_draft_created_without_seed_tasks(self):
        response = self.post(
            "/api/v2/templates",
            {
                "code": "  fitout 45  ",
                "name": "Fitout Standard",
                "description": "New stable identity.",
                "duration_days": 45,
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["template_code"], "FITOUT-45")
        self.assertEqual(payload["version_no"], 1)
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["task_count"], 0)
        fetched = self.client.get(f"/api/v2/templates/versions/{payload['version_id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["version_id"], payload["version_id"])
        for role in (UserRole.admin, UserRole.project_manager):
            self.set_role(role)
            hidden = self.client.get(f"/api/v2/templates/versions/{payload['version_id']}")
            self.assertEqual(hidden.status_code, 404)
        self.set_role(UserRole.super_admin)
        with self.Session() as session:
            template = session.get(V2Template, uuid.UUID(payload["template_id"]))
            version = session.get(V2TemplateVersion, uuid.UUID(payload["version_id"]))
            self.assertEqual(template.code, "FITOUT-45")
            self.assertEqual(version.template_id, template.id)
            self.assertIsNone(version.published_at)
            self.assertFalse(version.is_current_published)
        self.audit_writer.assert_called_once()
        audit = self.audit_writer.call_args.args[1]
        self.assertEqual(audit.action, TemplateAuditAction.TEMPLATE_CREATED)
        self.assertEqual(audit.entity_type, "template")
        self.assertEqual(audit.entity_id, uuid.UUID(payload["template_id"]))
        self.assertEqual(audit.actor_user_id, ACTOR_ID)
        self.assertEqual(audit.source, "portal")
        self.assertIsNone(audit.before_json)
        self.assertEqual(
            audit.after_json,
            {
                "template_code": "FITOUT-45",
                "template_name": "Fitout Standard",
                "version_id": payload["version_id"],
                "version_no": 1,
                "status": "draft",
                "duration_days": 45,
            },
        )

    def test_duplicate_normalized_template_code_is_rejected(self):
        response = self.post(
            "/api/v2/templates",
            {"code": " workved-45 ", "name": "Duplicate", "duration_days": 45},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "template_code_exists")
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2Template)), 1)

    def test_only_super_admin_can_create_or_clone(self):
        create_payload = {"code": "SECURE-01", "name": "Secure", "duration_days": 5}
        for role in (
            UserRole.admin,
            UserRole.project_manager,
            UserRole.supervisor,
            UserRole.internal_employee,
        ):
            with self.subTest(role=role):
                self.assertEqual(self.post("/api/v2/templates", create_payload, role).status_code, 403)
                self.assertEqual(
                    self.post(
                        f"/api/v2/templates/versions/{self.source_version_id}/clone", {}, role
                    ).status_code,
                    403,
                )
        self.assertEqual(self.post("/api/v2/templates", create_payload, None).status_code, 401)

    def test_clone_reproduces_records_and_re_resolves_all_foreign_keys(self):
        response = self.post(
            f"/api/v2/templates/versions/{self.source_version_id}/clone",
            {"change_note": "Prepare next controlled revision."},
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["version_no"], 10)
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["task_count"], 2)
        self.assertEqual(payload["dependency_count"], 1)
        self.assertEqual(payload["gate_count"], 2)
        self.assertEqual(payload["exact_mapping_count"], 1)
        self.assertEqual(payload["source_version_id"], str(self.source_version_id))
        self.assertNotEqual(payload["version_id"], payload["source_version_id"])
        fetched = self.client.get(f"/api/v2/templates/versions/{payload['version_id']}")
        self.assertEqual(fetched.status_code, 200)

        target_id = uuid.UUID(payload["version_id"])
        with self.Session() as session:
            source = session.get(V2TemplateVersion, self.source_version_id)
            target = session.get(V2TemplateVersion, target_id)
            self.assertEqual(source.status, "published")
            self.assertTrue(source.is_current_published)
            self.assertEqual(source.content_hash, "published-content-hash")
            self.assertEqual(target.status, "draft")
            self.assertFalse(target.is_current_published)
            self.assertIsNone(target.published_at)
            self.assertIsNone(target.published_by)
            self.assertIsNone(target.content_hash)
            self.assertEqual(target.created_by, ACTOR_ID)

            source_tasks = list(
                session.scalars(
                    select(V2TemplateTask).where(
                        V2TemplateTask.template_version_id == self.source_version_id
                    )
                )
            )
            target_tasks = list(
                session.scalars(
                    select(V2TemplateTask).where(V2TemplateTask.template_version_id == target_id)
                )
            )
            source_tasks_by_code = {task.code: task for task in source_tasks}
            target_tasks_by_code = {task.code: task for task in target_tasks}
            target_task_ids = {task.id for task in target_tasks}
            self.assertTrue(target_task_ids.isdisjoint(self.source_task_ids))
            self.assertEqual(set(target_tasks_by_code), set(source_tasks_by_code))
            task_fields = (
                "sequence_no", "title", "description", "schedule_classification",
                "planned_start_day", "planned_end_day", "phase", "category",
                "applicability", "task_class", "task_kind", "evidence_required",
                "duration_days",
            )
            for code, source_task in source_tasks_by_code.items():
                self.assertEqual(
                    tuple(getattr(target_tasks_by_code[code], field) for field in task_fields),
                    tuple(getattr(source_task, field) for field in task_fields),
                )

            source_dependency = session.scalar(
                select(V2TemplateTaskDependency).where(
                    V2TemplateTaskDependency.template_version_id == self.source_version_id
                )
            )
            dependency = session.scalar(
                select(V2TemplateTaskDependency).where(
                    V2TemplateTaskDependency.template_version_id == target_id
                )
            )
            self.assertIn(dependency.predecessor_task_id, target_task_ids)
            self.assertIn(dependency.successor_task_id, target_task_ids)
            source_task_by_id = {task.id: task for task in source_tasks}
            target_task_by_id = {task.id: task for task in target_tasks}
            self.assertEqual(
                (
                    target_task_by_id[dependency.predecessor_task_id].code,
                    target_task_by_id[dependency.successor_task_id].code,
                    dependency.dependency_type,
                    dependency.blocking,
                    dependency.rule_text,
                    dependency.sequence_no,
                ),
                (
                    source_task_by_id[source_dependency.predecessor_task_id].code,
                    source_task_by_id[source_dependency.successor_task_id].code,
                    source_dependency.dependency_type,
                    source_dependency.blocking,
                    source_dependency.rule_text,
                    source_dependency.sequence_no,
                ),
            )

            source_gates = list(
                session.scalars(
                    select(V2TemplateExternalGate).where(
                        V2TemplateExternalGate.template_version_id == self.source_version_id
                    )
                )
            )
            gates = list(
                session.scalars(
                    select(V2TemplateExternalGate).where(
                        V2TemplateExternalGate.template_version_id == target_id
                    )
                )
            )
            source_gate_by_code = {gate.code: gate for gate in source_gates}
            gate_by_code = {gate.code: gate for gate in gates}
            self.assertEqual(set(gate_by_code), set(source_gate_by_code))
            gate_fields = (
                "approval_name", "description", "external_party", "required_by_type",
                "required_by_value", "impact", "mapping_classification",
                "broad_mapping_text", "requires_configuration", "sequence_no",
            )
            for code, source_gate in source_gate_by_code.items():
                self.assertEqual(
                    tuple(getattr(gate_by_code[code], field) for field in gate_fields),
                    tuple(getattr(source_gate, field) for field in gate_fields),
                )
            self.assertEqual(gate_by_code["E006"].broad_mapping_text, "T008 onwards")
            exact_links = list(
                session.scalars(
                    select(V2TemplateExternalGateTask).where(
                        V2TemplateExternalGateTask.gate_id == gate_by_code["E001"].id
                    )
                )
            )
            broad_links = list(
                session.scalars(
                    select(V2TemplateExternalGateTask).where(
                        V2TemplateExternalGateTask.gate_id == gate_by_code["E006"].id
                    )
                )
            )
            self.assertEqual(len(exact_links), 1)
            self.assertIn(exact_links[0].template_task_id, target_task_ids)
            self.assertEqual(broad_links, [])
        self.audit_writer.assert_called_once()
        audit = self.audit_writer.call_args.args[1]
        self.assertEqual(audit.action, TemplateAuditAction.TEMPLATE_VERSION_CLONED)
        self.assertEqual(audit.entity_type, "template_version")
        self.assertEqual(audit.entity_id, target_id)
        self.assertEqual(audit.actor_user_id, ACTOR_ID)
        self.assertEqual(audit.source, "portal")
        self.assertEqual(
            audit.before_json,
            {
                "source_version_id": str(self.source_version_id),
                "source_version_no": 1,
                "source_status": "published",
            },
        )
        self.assertEqual(
            audit.after_json,
            {
                "template_id": str(self.template_id),
                "version_id": str(target_id),
                "version_no": 10,
                "status": "draft",
                "task_count": 2,
                "dependency_count": 1,
                "gate_count": 2,
                "exact_mapping_count": 1,
            },
        )

    def test_archived_source_is_not_cloneable(self):
        response = self.post(
            f"/api/v2/templates/versions/{self.archived_version_id}/clone", {}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Template version not found.")

    def test_create_failure_rolls_back_template_and_version(self):
        with patch.object(
            TemplateMutationRepository,
            "create_draft_version",
            side_effect=RuntimeError("forced create failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.post(
                    "/api/v2/templates",
                    {"code": "ROLLBACK-01", "name": "Rollback", "duration_days": 5},
                )
        with self.Session() as session:
            self.assertIsNone(
                session.scalar(select(V2Template).where(V2Template.code == "ROLLBACK-01"))
            )
        self.audit_writer.assert_not_called()

    def test_clone_failure_rolls_back_new_version_and_children(self):
        with patch.object(
            TemplateMutationRepository,
            "clone_dependencies",
            side_effect=RuntimeError("forced clone failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.post(
                    f"/api/v2/templates/versions/{self.source_version_id}/clone", {}
                )
        with self.Session() as session:
            versions = session.scalar(
                select(func.count()).select_from(V2TemplateVersion).where(
                    V2TemplateVersion.template_id == self.template_id
                )
            )
            tasks = session.scalar(select(func.count()).select_from(V2TemplateTask))
            self.assertEqual(versions, 2)
            self.assertEqual(tasks, 2)
        self.audit_writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()