from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import User, UserRole
from app.repositories.template_task_repository import TemplateTaskRepository
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


class TemplateTaskCommandApiTests(unittest.TestCase):
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
                # Authentication reads auto-start the shared request transaction.
                session.scalar(select(V2Template.id).limit(1))
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)
        self.audit_patch = patch(
            "app.services.template_task_commands.write_template_audit_event"
        )
        self.audit_writer = self.audit_patch.start()
        self.set_role(UserRole.super_admin)

    def tearDown(self):
        self.audit_patch.stop()
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            template = V2Template(
                code="AUTHOR-60",
                name="Authoring Template",
                description="Draft mutation fixture.",
            )
            session.add(template)
            session.flush()
            draft = V2TemplateVersion(
                template_id=template.id,
                version_no=2,
                status="draft",
                duration_days=60,
                change_note="Authoring",
                is_current_published=False,
                created_by=ACTOR_ID,
                updated_at=datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc),
            )
            published = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=60,
                change_note="Published",
                content_hash="immutable",
                is_current_published=True,
                created_by=ACTOR_ID,
                published_by=ACTOR_ID,
                published_at=datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc),
            )
            session.add_all([draft, published])
            session.flush()
            task_one = V2TemplateTask(
                template_version_id=draft.id,
                code="T001",
                sequence_no=1,
                title="Pre-activation control",
                schedule_classification="pre_activation",
                applicability="mandatory",
                evidence_required=True,
                duration_days=1,
            )
            task_two = V2TemplateTask(
                template_version_id=draft.id,
                code="T002",
                sequence_no=2,
                title="Execution task",
                description="Existing execution task.",
                schedule_classification="execution",
                planned_start_day=1,
                planned_end_day=2,
                phase="Execution",
                category="Site",
                applicability="mandatory",
                task_class="work",
                task_kind="execution",
                evidence_required=False,
                duration_days=2,
            )
            task_three = V2TemplateTask(
                template_version_id=draft.id,
                code="T003",
                sequence_no=3,
                title="Unreferenced task",
                schedule_classification="execution",
                planned_start_day=3,
                planned_end_day=3,
                applicability="conditional",
                evidence_required=False,
                duration_days=1,
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
            session.add_all([task_one, task_two, task_three, published_task])
            session.flush()
            dependency = V2TemplateTaskDependency(
                template_version_id=draft.id,
                predecessor_task_id=task_one.id,
                successor_task_id=task_two.id,
                dependency_type="finish_to_start",
                blocking=True,
                rule_text="Control before work.",
                sequence_no=1,
            )
            gate = V2TemplateExternalGate(
                template_version_id=draft.id,
                code="E001",
                approval_name="Mapped approval",
                external_party="Client",
                required_by_type="task",
                required_by_value="T002",
                mapping_classification="exact",
                requires_configuration=False,
                sequence_no=1,
            )
            session.add_all([dependency, gate])
            session.flush()
            session.add(
                V2TemplateExternalGateTask(
                    gate_id=gate.id,
                    template_task_id=task_two.id,
                )
            )
            self.template_id = template.id
            self.draft_id = draft.id
            self.published_id = published.id
            self.task_one_id = task_one.id
            self.task_two_id = task_two.id
            self.task_three_id = task_three.id
            self.published_task_id = published_task.id

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

    def create_payload(self, **overrides):
        payload = {
            "code": "T004",
            "sequence_no": 4,
            "title": "Late configurable task",
            "description": None,
            "schedule_classification": "execution",
            "planned_start_day": 55,
            "planned_end_day": 60,
            "phase": "Closeout",
            "category": None,
            "applicability": "mandatory",
            "task_class": None,
            "task_kind": None,
            "evidence_required": False,
            "duration_days": 6,
            "revision_token": self.revision(),
        }
        payload.update(overrides)
        return payload

    def test_draft_detail_exposes_revision_token_for_safe_mutations(self):
        response = self.client.get(
            f"/api/v2/templates/versions/{self.draft_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision_token"], self.revision())

        self.set_role(UserRole.admin)
        hidden = self.client.get(
            f"/api/v2/templates/versions/{self.draft_id}"
        )
        self.assertEqual(hidden.status_code, 404)
        self.set_role(UserRole.super_admin)

    def test_create_valid_task_with_configured_duration_and_audit(self):
        response = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/tasks",
            json=self.create_payload(),
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["task"]["code"], "T004")
        self.assertEqual(body["task"]["planned_end_day"], 60)
        self.assertNotEqual(body["revision_token"], self.revision(self.published_id))
        with self.Session() as session:
            task = session.get(V2TemplateTask, uuid.UUID(body["task"]["id"]))
            self.assertEqual(task.template_version_id, self.draft_id)
        audit = self.audit_writer.call_args.args[1]
        self.assertEqual(audit.action, TemplateAuditAction.TEMPLATE_TASK_CREATED)
        self.assertEqual(audit.entity_id, uuid.UUID(body["task"]["id"]))
        self.assertEqual(audit.actor_user_id, ACTOR_ID)
        self.assertIsNone(audit.before_json)
        self.assertEqual(audit.after_json["code"], "T004")

    def test_duplicate_code_and_sequence_are_structured_conflicts(self):
        duplicate_code = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/tasks",
            json=self.create_payload(code=" t001 ", sequence_no=4),
        )
        self.assertEqual(duplicate_code.status_code, 409)
        self.assertEqual(
            duplicate_code.json()["detail"]["code"], "template_task_code_exists"
        )

        duplicate_sequence = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/tasks",
            json=self.create_payload(code="T004", sequence_no=1),
        )
        self.assertEqual(duplicate_sequence.status_code, 409)
        self.assertEqual(
            duplicate_sequence.json()["detail"]["code"],
            "template_task_sequence_exists",
        )

    def test_invalid_schedule_is_rejected_without_writes(self):
        cases = [
            {
                "schedule_classification": "execution",
                "planned_start_day": 1,
                "planned_end_day": 61,
            },
            {
                "schedule_classification": "execution",
                "planned_start_day": 5,
                "planned_end_day": 4,
            },
            {
                "schedule_classification": "pre_activation",
                "planned_start_day": 1,
                "planned_end_day": 1,
            },
        ]
        for index, changes in enumerate(cases, start=1):
            with self.subTest(changes=changes):
                response = self.client.post(
                    f"/api/v2/templates/versions/{self.draft_id}/tasks",
                    json=self.create_payload(
                        code=f"T10{index}",
                        sequence_no=3 + index,
                        **changes,
                    ),
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["detail"]["code"], "invalid_template_task"
                )
        with self.Session() as session:
            codes = set(
                session.scalars(
                    select(V2TemplateTask.code).where(
                        V2TemplateTask.template_version_id == self.draft_id
                    )
                )
            )
            self.assertEqual(codes, {"T001", "T002", "T003"})
        self.audit_writer.assert_not_called()

    def test_update_allowed_fields_and_reject_stale_revision(self):
        old_revision = self.revision()
        response = self.client.patch(
            f"/api/v2/templates/versions/{self.draft_id}/tasks/{self.task_two_id}",
            json={
                "revision_token": old_revision,
                "title": "Updated execution task",
                "description": "Preserved approved edit.",
                "planned_end_day": 4,
                "applicability": "conditional",
                "evidence_required": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["task"]["title"], "Updated execution task")
        self.assertEqual(body["task"]["planned_start_day"], 1)
        self.assertEqual(body["task"]["planned_end_day"], 4)
        self.assertEqual(body["task"]["category"], "Site")
        self.assertEqual(body["task"]["applicability"], "conditional")
        self.assertTrue(body["task"]["evidence_required"])
        self.assertNotEqual(body["revision_token"], old_revision)
        audit = self.audit_writer.call_args.args[1]
        self.assertEqual(audit.action, TemplateAuditAction.TEMPLATE_TASK_UPDATED)
        self.assertEqual(audit.before_json["title"], "Execution task")
        self.assertEqual(audit.after_json["title"], "Updated execution task")

        stale = self.client.patch(
            f"/api/v2/templates/versions/{self.draft_id}/tasks/{self.task_two_id}",
            json={"revision_token": old_revision, "title": "Stale edit"},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            stale.json()["detail"]["code"], "stale_template_version"
        )
        self.assertEqual(self.audit_writer.call_count, 1)

    def test_published_update_is_rejected_and_roles_remain_restricted(self):
        published = self.client.patch(
            f"/api/v2/templates/versions/{self.published_id}/tasks/{self.published_task_id}",
            json={
                "revision_token": self.revision(self.published_id),
                "title": "Forbidden",
            },
        )
        self.assertEqual(published.status_code, 409)
        self.assertEqual(
            published.json()["detail"]["code"], "template_version_immutable"
        )

        for role in (
            UserRole.admin,
            UserRole.project_manager,
            UserRole.supervisor,
            UserRole.internal_employee,
        ):
            with self.subTest(role=role):
                self.set_role(role)
                response = self.client.post(
                    f"/api/v2/templates/versions/{self.draft_id}/tasks",
                    json=self.create_payload(),
                )
                self.assertEqual(response.status_code, 403)
        self.set_role(None)
        self.assertEqual(
            self.client.post(
                f"/api/v2/templates/versions/{self.draft_id}/tasks",
                json=self.create_payload(),
            ).status_code,
            401,
        )

    def test_delete_unreferenced_succeeds_but_referenced_task_conflicts(self):
        delete = self.client.delete(
            f"/api/v2/templates/versions/{self.draft_id}/tasks/{self.task_three_id}",
            params={"revision_token": self.revision()},
        )
        self.assertEqual(delete.status_code, 200)
        body = delete.json()
        self.assertTrue(body["deleted"])
        with self.Session() as session:
            self.assertIsNone(session.get(V2TemplateTask, self.task_three_id))
        delete_audit = self.audit_writer.call_args.args[1]
        self.assertEqual(delete_audit.action, TemplateAuditAction.TEMPLATE_TASK_DELETED)
        self.assertEqual(delete_audit.before_json["code"], "T003")

        self.audit_writer.reset_mock()
        conflict = self.client.delete(
            f"/api/v2/templates/versions/{self.draft_id}/tasks/{self.task_two_id}",
            params={"revision_token": body["revision_token"]},
        )
        self.assertEqual(conflict.status_code, 409)
        detail = conflict.json()["detail"]
        self.assertEqual(detail["code"], "template_task_referenced")
        self.assertEqual(len(detail["dependencies"]), 1)
        self.assertEqual(detail["dependencies"][0]["relationship"], "successor")
        self.assertEqual(len(detail["gate_mappings"]), 1)
        self.assertEqual(detail["gate_mappings"][0]["gate_code"], "E001")
        with self.Session() as session:
            self.assertIsNotNone(session.get(V2TemplateTask, self.task_two_id))
        self.audit_writer.assert_not_called()

    def test_complete_reorder_is_atomic_and_audited(self):
        original_revision = self.revision()
        response = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/tasks/reorder",
            json={
                "revision_token": original_revision,
                "items": [
                    {"task_id": str(self.task_one_id), "sequence_no": 3},
                    {"task_id": str(self.task_two_id), "sequence_no": 1},
                    {"task_id": str(self.task_three_id), "sequence_no": 2},
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [(item["task_id"], item["sequence_no"]) for item in body["items"]],
            [
                (str(self.task_two_id), 1),
                (str(self.task_three_id), 2),
                (str(self.task_one_id), 3),
            ],
        )
        self.assertNotEqual(body["revision_token"], original_revision)
        audit = self.audit_writer.call_args.args[1]
        self.assertEqual(audit.action, TemplateAuditAction.TEMPLATE_TASKS_REORDERED)
        self.assertEqual(
            [item["sequence_no"] for item in audit.after_json["tasks"]],
            [1, 2, 3],
        )

        current_revision = body["revision_token"]
        self.audit_writer.reset_mock()
        invalid = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/tasks/reorder",
            json={
                "revision_token": current_revision,
                "items": [
                    {"task_id": str(self.task_one_id), "sequence_no": 1},
                    {"task_id": str(self.task_two_id), "sequence_no": 2},
                ],
            },
        )
        self.assertEqual(invalid.status_code, 422)
        duplicate_sequence = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/tasks/reorder",
            json={
                "revision_token": current_revision,
                "items": [
                    {"task_id": str(self.task_one_id), "sequence_no": 1},
                    {"task_id": str(self.task_two_id), "sequence_no": 1},
                    {"task_id": str(self.task_three_id), "sequence_no": 3},
                ],
            },
        )
        self.assertEqual(duplicate_sequence.status_code, 422)
        self.assertEqual(
            duplicate_sequence.json()["detail"]["code"],
            "invalid_template_task",
        )
        with self.Session() as session:
            stored = list(
                session.scalars(
                    select(V2TemplateTask)
                    .where(V2TemplateTask.template_version_id == self.draft_id)
                    .order_by(V2TemplateTask.sequence_no)
                )
            )
            self.assertEqual(
                [(task.id, task.sequence_no) for task in stored],
                [
                    (self.task_two_id, 1),
                    (self.task_three_id, 2),
                    (self.task_one_id, 3),
                ],
            )
        self.audit_writer.assert_not_called()


    def test_reorder_failure_rolls_back_every_sequence_and_audit(self):
        def fail_after_temporary_write(repository, tasks, _sequence_by_id):
            for offset, task in enumerate(tasks, start=1):
                task.sequence_no = 100 + offset
            repository.db.flush()
            raise RuntimeError("forced reorder failure")

        with patch.object(
            TemplateTaskRepository,
            "reorder_complete",
            autospec=True,
            side_effect=fail_after_temporary_write,
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    f"/api/v2/templates/versions/{self.draft_id}/tasks/reorder",
                    json={
                        "revision_token": self.revision(),
                        "items": [
                            {"task_id": str(self.task_one_id), "sequence_no": 3},
                            {"task_id": str(self.task_two_id), "sequence_no": 1},
                            {"task_id": str(self.task_three_id), "sequence_no": 2},
                        ],
                    },
                )

        with self.Session() as session:
            stored = list(
                session.scalars(
                    select(V2TemplateTask)
                    .where(V2TemplateTask.template_version_id == self.draft_id)
                    .order_by(V2TemplateTask.sequence_no)
                )
            )
            self.assertEqual(
                [(task.id, task.sequence_no) for task in stored],
                [
                    (self.task_one_id, 1),
                    (self.task_two_id, 2),
                    (self.task_three_id, 3),
                ],
            )
        self.audit_writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()