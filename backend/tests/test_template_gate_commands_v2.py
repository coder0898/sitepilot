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


class TemplateGateCommandApiTests(unittest.TestCase):
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
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ACTOR_ID,
            name="Super Admin",
            email="super@example.com",
            role=UserRole.super_admin,
            active=True,
        )
        self.client = TestClient(self.app)
        self.audit_patch = patch("app.services.template_gate_commands.write_template_audit_event")
        self.audit_writer = self.audit_patch.start()

    def tearDown(self):
        self.audit_patch.stop()
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            template = V2Template(code="GATE", name="Gates")
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
            for idx in range(1, 4):
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
            session.add_all([*tasks, other_task])
            session.flush()
            broad = V2TemplateExternalGate(
                template_version_id=draft.id,
                code="E001",
                approval_name="Broad gate",
                mapping_classification="broad_text",
                broad_mapping_text="Relevant procurement tasks",
                requires_configuration=True,
                sequence_no=1,
            )
            exact = V2TemplateExternalGate(
                template_version_id=draft.id,
                code="E002",
                approval_name="Exact gate",
                mapping_classification="exact",
                broad_mapping_text=None,
                requires_configuration=False,
                sequence_no=2,
            )
            session.add_all([broad, exact])
            session.flush()
            session.add(
                V2TemplateExternalGateTask(gate_id=exact.id, template_task_id=tasks[0].id)
            )
            self.draft_id = draft.id
            self.published_id = published.id
            self.other_id = other.id
            self.task_ids = [t.id for t in tasks]
            self.other_task_id = other_task.id
            self.broad_id = broad.id
            self.exact_id = exact.id

    def revision(self, version_id=None):
        with self.Session() as session:
            return concurrency_token(session.get(V2TemplateVersion, version_id or self.draft_id))

    def base(self, **overrides):
        data = {
            "code": "E010",
            "approval_name": "New approval",
            "description": "Description",
            "external_party": "Building",
            "required_by_type": "project_day",
            "required_by_value": "Day 5",
            "impact": "Full",
            "sequence_no": 10,
            "revision_token": self.revision(),
        }
        data.update(overrides)
        return data

    def test_create_exact_broad_and_unmapped_gates(self):
        exact = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/gates",
            json=self.base(mapping_classification="exact", task_ids=[str(self.task_ids[0])]),
        )
        self.assertEqual(exact.status_code, 201)
        self.assertEqual(exact.json()["gate"]["task_ids"], [str(self.task_ids[0])])
        broad = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/gates",
            json=self.base(
                code="E011",
                sequence_no=11,
                revision_token=exact.json()["revision_token"],
                mapping_classification="broad_text",
                broad_mapping_text="Affected activities",
                task_ids=[],
            ),
        )
        self.assertEqual(broad.status_code, 201)
        self.assertEqual(broad.json()["gate"]["task_ids"], [])
        self.assertTrue(broad.json()["gate"]["requires_configuration"])
        unmapped = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/gates",
            json=self.base(
                code="E012",
                sequence_no=12,
                revision_token=broad.json()["revision_token"],
                mapping_classification="unmapped",
                task_ids=[],
            ),
        )
        self.assertEqual(unmapped.status_code, 201)
        self.assertEqual(unmapped.json()["gate"]["mapping_classification"], "unmapped")
        self.assertTrue(unmapped.json()["gate"]["requires_configuration"])

    def test_configure_exact_mapping_and_reject_invalid_tasks(self):
        response = self.client.put(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
            json={
                "mapping_classification": "exact",
                "task_ids": [str(self.task_ids[0]), str(self.task_ids[1])],
                "revision_token": self.revision(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()["gate"]["task_ids"]), {str(self.task_ids[0]), str(self.task_ids[1])})
        missing = self.client.put(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
            json={
                "mapping_classification": "exact",
                "task_ids": [str(uuid.uuid4())],
                "revision_token": response.json()["revision_token"],
            },
        )
        self.assertEqual(missing.status_code, 422)
        cross = self.client.put(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
            json={
                "mapping_classification": "exact",
                "task_ids": [str(self.other_task_id)],
                "revision_token": response.json()["revision_token"],
            },
        )
        self.assertEqual(cross.status_code, 422)

    def test_reject_duplicate_mapping_and_broad_has_zero_rows(self):
        duplicate = self.client.put(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
            json={
                "mapping_classification": "exact",
                "task_ids": [str(self.task_ids[0]), str(self.task_ids[0])],
                "revision_token": self.revision(),
            },
        )
        self.assertEqual(duplicate.status_code, 422)
        with self.Session() as session:
            count = session.scalar(
                select(func.count()).select_from(V2TemplateExternalGateTask).where(
                    V2TemplateExternalGateTask.gate_id == self.broad_id
                )
            )
            self.assertEqual(count, 0)

    def test_transition_broad_to_exact_and_exact_to_broad(self):
        to_exact = self.client.put(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
            json={
                "mapping_classification": "exact",
                "task_ids": [str(self.task_ids[1])],
                "revision_token": self.revision(),
            },
        )
        self.assertEqual(to_exact.status_code, 200)
        self.assertIsNone(to_exact.json()["gate"]["broad_mapping_text"])
        to_broad = self.client.put(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
            json={
                "mapping_classification": "broad_text",
                "broad_mapping_text": "Relevant work only",
                "task_ids": [],
                "revision_token": to_exact.json()["revision_token"],
            },
        )
        self.assertEqual(to_broad.status_code, 200)
        self.assertEqual(to_broad.json()["gate"]["task_ids"], [])
        with self.Session() as session:
            count = session.scalar(
                select(func.count()).select_from(V2TemplateExternalGateTask).where(
                    V2TemplateExternalGateTask.gate_id == self.broad_id
                )
            )
            self.assertEqual(count, 0)

    def test_update_and_delete_only_gate_and_own_mappings(self):
        updated = self.client.patch(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.exact_id}",
            json={"revision_token": self.revision(), "approval_name": "Updated approval"},
        )
        self.assertEqual(updated.status_code, 200)
        deleted = self.client.delete(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.exact_id}",
            params={"revision_token": updated.json()["revision_token"]},
        )
        self.assertEqual(deleted.status_code, 200)
        with self.Session() as session:
            self.assertIsNone(session.get(V2TemplateExternalGate, self.exact_id))
            self.assertEqual(session.scalar(select(func.count()).select_from(V2TemplateTask)), 4)
        audit = self.audit_writer.call_args.args[1]
        self.assertEqual(audit.action, TemplateAuditAction.TEMPLATE_GATE_DELETED)

    def test_published_version_immutable(self):
        response = self.client.post(
            f"/api/v2/templates/versions/{self.published_id}/gates",
            json=self.base(
                mapping_classification="unmapped",
                task_ids=[],
                revision_token=self.revision(self.published_id),
            ),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "template_version_immutable")

    def test_transaction_rollback_and_no_audit_on_failure(self):
        self.audit_writer.side_effect = RuntimeError("audit failed")
        with self.assertRaises(RuntimeError):
            self.client.post(
                f"/api/v2/templates/versions/{self.draft_id}/gates",
                json=self.base(mapping_classification="unmapped", task_ids=[]),
            )
        with self.Session() as session:
            self.assertIsNone(
                session.scalar(
                    select(V2TemplateExternalGate).where(V2TemplateExternalGate.code == "E010")
                )
            )
        self.assertEqual(self.audit_writer.call_count, 1)

    def test_stale_revision_rejected_without_write_or_audit(self):
        stale = self.revision()
        with self.Session.begin() as session:
            session.get(V2TemplateVersion, self.draft_id).updated_at = datetime(
                2026, 7, 28, 7, 0, tzinfo=timezone.utc
            )
        response = self.client.post(
            f"/api/v2/templates/versions/{self.draft_id}/gates",
            json=self.base(
                mapping_classification="unmapped", task_ids=[], revision_token=stale
            ),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "stale_template_version")
        self.audit_writer.assert_not_called()

    def test_mapping_transitions_are_atomic_and_audited_with_complete_snapshots(self):
        to_exact = self.client.put(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
            json={
                "mapping_classification": "exact",
                "task_ids": [str(self.task_ids[0]), str(self.task_ids[1])],
                "revision_token": self.revision(),
            },
        )
        self.assertEqual(to_exact.status_code, 200)
        exact_audit = self.audit_writer.call_args.args[1]
        self.assertEqual(
            exact_audit.action, TemplateAuditAction.TEMPLATE_GATE_MAPPING_CHANGED
        )
        self.assertEqual(exact_audit.before_json["mapping_classification"], "broad_text")
        self.assertEqual(exact_audit.before_json["broad_mapping_text"], "Relevant procurement tasks")
        self.assertEqual(exact_audit.before_json["task_ids"], [])
        self.assertEqual(exact_audit.after_json["mapping_classification"], "exact")
        self.assertIsNone(exact_audit.after_json["broad_mapping_text"])
        self.assertEqual(
            set(exact_audit.after_json["task_ids"]),
            {str(self.task_ids[0]), str(self.task_ids[1])},
        )

        to_broad = self.client.put(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
            json={
                "mapping_classification": "broad_text",
                "broad_mapping_text": "Original affected activities wording",
                "task_ids": [],
                "revision_token": to_exact.json()["revision_token"],
            },
        )
        self.assertEqual(to_broad.status_code, 200)
        broad_audit = self.audit_writer.call_args.args[1]
        self.assertEqual(
            broad_audit.action, TemplateAuditAction.TEMPLATE_GATE_MAPPING_CHANGED
        )
        self.assertEqual(broad_audit.before_json["mapping_classification"], "exact")
        self.assertEqual(
            set(broad_audit.before_json["task_ids"]),
            {str(self.task_ids[0]), str(self.task_ids[1])},
        )
        self.assertEqual(broad_audit.after_json["mapping_classification"], "broad_text")
        self.assertEqual(
            broad_audit.after_json["broad_mapping_text"],
            "Original affected activities wording",
        )
        self.assertEqual(broad_audit.after_json["task_ids"], [])
        with self.Session() as session:
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(V2TemplateExternalGateTask)
                    .where(V2TemplateExternalGateTask.gate_id == self.broad_id)
                ),
                0,
            )

    def test_mapping_transition_rolls_back_gate_and_rows_when_audit_fails(self):
        before_revision = self.revision()
        self.audit_writer.side_effect = RuntimeError("audit failed")
        with self.assertRaises(RuntimeError):
            self.client.put(
                f"/api/v2/templates/versions/{self.draft_id}/gates/{self.broad_id}/mappings",
                json={
                    "mapping_classification": "exact",
                    "task_ids": [str(self.task_ids[0])],
                    "revision_token": before_revision,
                },
            )
        with self.Session() as session:
            gate = session.get(V2TemplateExternalGate, self.broad_id)
            self.assertEqual(gate.mapping_classification, "broad_text")
            self.assertEqual(gate.broad_mapping_text, "Relevant procurement tasks")
            self.assertTrue(gate.requires_configuration)
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(V2TemplateExternalGateTask)
                    .where(V2TemplateExternalGateTask.gate_id == self.broad_id)
                ),
                0,
            )
            self.assertEqual(
                concurrency_token(session.get(V2TemplateVersion, self.draft_id)),
                before_revision,
            )


if __name__ == "__main__":
    unittest.main()
