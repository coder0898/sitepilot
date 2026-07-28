from __future__ import annotations

import copy
from dataclasses import replace
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import User, UserRole
from app.repositories.template_validation_repository import TemplateValidationAggregate
from app.routes.templates_v2 import router
from app.services.template_draft_validator import validate_aggregate
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)

ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def obj(**kw):
    return SimpleNamespace(**kw)


def valid_aggregate(status="draft"):
    template_id, version_id = uuid.uuid4(), uuid.uuid4()
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    gate_id = uuid.uuid4()
    template = obj(id=template_id, code="VALID", name="Valid Template")
    version = obj(
        id=version_id, template_id=template_id, version_no=1, status=status,
        duration_days=45, updated_at=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)
    )
    tasks = [
        obj(id=t1, code="T001", sequence_no=1, title="Pre", schedule_classification="pre_activation",
            planned_start_day=None, planned_end_day=None, applicability="mandatory", duration_days=None),
        obj(id=t2, code="T002", sequence_no=2, title="Execute", schedule_classification="execution",
            planned_start_day=1, planned_end_day=2, applicability="conditional", duration_days=2),
    ]
    dependencies = [obj(id=uuid.uuid4(), predecessor_task_id=t1, successor_task_id=t2,
                        dependency_type="finish_to_start")]
    gates = [obj(id=gate_id, code="E001", approval_name="Approval", sequence_no=1,
                 mapping_classification="exact", broad_mapping_text=None, requires_configuration=False)]
    mappings = [obj(id=uuid.uuid4(), gate_id=gate_id, template_task_id=t2)]
    return TemplateValidationAggregate(template, version, tasks, dependencies, gates, mappings)


class TemplateValidationPureTests(unittest.TestCase):
    def codes(self, aggregate):
        return [issue.code for issue in validate_aggregate(aggregate, validated_at=datetime(2026, 7, 28, tzinfo=timezone.utc)).issues]

    def test_valid_draft_passes_and_result_is_deterministic(self):
        aggregate = valid_aggregate()
        first = validate_aggregate(aggregate, validated_at=datetime(2026, 7, 28, tzinfo=timezone.utc)).model_dump()
        second = validate_aggregate(aggregate, validated_at=datetime(2026, 7, 28, tzinfo=timezone.utc)).model_dump()
        self.assertEqual(first, second)
        self.assertTrue(first["is_valid"])
        self.assertEqual(first["severity_counts"]["errors"], 0)

    def test_blocking_task_and_schedule_defects(self):
        a = valid_aggregate()
        a.tasks[1].code = a.tasks[0].code
        a.tasks[1].sequence_no = a.tasks[0].sequence_no
        a.tasks[1].applicability = "other"
        a.tasks[1].planned_end_day = 46
        codes = self.codes(a)
        for code in ("task_code_duplicate", "task_sequence_duplicate", "task_applicability_invalid", "task_exceeds_version_duration"):
            self.assertIn(code, codes)

    def test_dependency_defects_are_reported(self):
        a = valid_aggregate()
        a.dependencies.append(obj(id=uuid.uuid4(), predecessor_task_id=a.tasks[1].id,
                                  successor_task_id=a.tasks[0].id, dependency_type="finish_to_start"))
        a.dependencies.append(obj(id=uuid.uuid4(), predecessor_task_id=a.tasks[0].id,
                                  successor_task_id=a.tasks[1].id, dependency_type="finish_to_start"))
        a.dependencies.append(obj(id=uuid.uuid4(), predecessor_task_id=uuid.uuid4(),
                                  successor_task_id=a.tasks[1].id, dependency_type="unsupported"))
        codes = self.codes(a)
        self.assertIn("dependency_cycle", codes)
        self.assertIn("dependency_duplicate", codes)
        self.assertIn("dependency_task_reference_invalid", codes)

    def test_gate_and_mapping_defects_are_reported(self):
        a = valid_aggregate()
        a.gates[0].mapping_classification = "broad_text"
        a.gates[0].broad_mapping_text = "Affected activities"
        a.gates[0].requires_configuration = False
        a.mappings.append(obj(id=uuid.uuid4(), gate_id=a.gates[0].id, template_task_id=uuid.uuid4()))
        codes = self.codes(a)
        self.assertIn("broad_gate_has_exact_rows", codes)
        self.assertIn("broad_gate_configuration_flag_required", codes)
        self.assertIn("mapping_task_reference_invalid", codes)

    def test_configuration_warnings_do_not_repair_or_block(self):
        a = valid_aggregate()
        a.gates[0].mapping_classification = "broad_text"
        a.gates[0].broad_mapping_text = "Relevant tasks"
        a.gates[0].requires_configuration = True
        a.mappings.clear()
        before = copy.deepcopy(a.gates[0].__dict__)
        result = validate_aggregate(a)
        self.assertTrue(result.is_valid)
        self.assertIn("broad_gate_requires_configuration", [i.code for i in result.issues])
        self.assertEqual(before, a.gates[0].__dict__)

    def test_empty_template_is_blocking(self):
        a = replace(valid_aggregate(), tasks=[], dependencies=[], mappings=[])
        self.assertIn("template_requires_task", self.codes(a))


class TemplateValidationApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def attach(dbapi_connection, _):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)
        for table in (V2Template.__table__, V2TemplateVersion.__table__, V2TemplateTask.__table__, V2TemplateTaskDependency.__table__, V2TemplateExternalGate.__table__, V2TemplateExternalGateTask.__table__):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session.begin() as s:
            template=V2Template(code="VAL", name="Validation"); s.add(template); s.flush()
            draft=V2TemplateVersion(template_id=template.id, version_no=2, status="draft", duration_days=45, created_by=ACTOR_ID, updated_at=datetime(2026,7,28,tzinfo=timezone.utc))
            published=V2TemplateVersion(template_id=template.id, version_no=1, status="published", duration_days=45, content_hash="x", is_current_published=True, created_by=ACTOR_ID, published_by=ACTOR_ID, published_at=datetime(2026,7,27,tzinfo=timezone.utc))
            s.add_all([draft,published]); s.flush()
            for version in (draft,published):
                task=V2TemplateTask(template_version_id=version.id, code="T001", sequence_no=1, title="Task", schedule_classification="execution", planned_start_day=1, planned_end_day=1, applicability="mandatory", evidence_required=False, duration_days=1)
                s.add(task)
            self.draft_id=draft.id; self.published_id=published.id
        self.app=FastAPI(); self.app.include_router(router)
        def db_override():
            with self.Session() as s: yield s
        self.app.dependency_overrides[get_db]=db_override
        self.role=UserRole.super_admin
        self.app.dependency_overrides[current_user]=lambda: User(id=ACTOR_ID,name="Actor",email="a@example.com",role=self.role,active=True)
        self.client=TestClient(self.app)

    def tearDown(self): self.client.close(); self.engine.dispose()

    def test_super_admin_validates_draft_and_published_without_mutation(self):
        with self.Session() as s:
            before=(s.scalar(select(func.count()).select_from(V2TemplateTask)), s.get(V2TemplateVersion,self.draft_id).updated_at)
        draft=self.client.post(f"/api/v2/templates/versions/{self.draft_id}/validate")
        published=self.client.post(f"/api/v2/templates/versions/{self.published_id}/validate")
        self.assertEqual(draft.status_code,200); self.assertEqual(published.status_code,200)
        self.assertEqual(published.json()["version_status"],"published")
        with self.Session() as s:
            after=(s.scalar(select(func.count()).select_from(V2TemplateTask)), s.get(V2TemplateVersion,self.draft_id).updated_at)
        self.assertEqual(before,after)

    def test_only_super_admin_can_validate_drafts(self):
        for role in (UserRole.admin, UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee):
            with self.subTest(role=role):
                self.role=role
                response=self.client.post(f"/api/v2/templates/versions/{self.draft_id}/validate")
                self.assertEqual(response.status_code,403)

    def test_missing_version_is_stable_404(self):
        response=self.client.post(f"/api/v2/templates/versions/{uuid.uuid4()}/validate")
        self.assertEqual(response.status_code,404)
        self.assertEqual(response.json()["detail"],"Template version not found.")
