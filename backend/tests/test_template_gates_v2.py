from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import User, UserRole
from app.repositories.template_repository import _gate_validation_issues
from app.routes.templates_v2 import list_template_gates
from app.services.template_queries import TemplateQueryService
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "app" / "fixtures" / "v2_templates"
ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
KNOWN_BROAD_GATES = {"E005", "E006", "E008", "E009", "E011", "E026"}


def actor(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        name=f"{role.value} tester",
        email=f"{role.value}@example.com",
        role=role,
        active=True,
    )


class TemplateGateApiTests(unittest.TestCase):
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
        cls._seed_authoritative_gates()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    @classmethod
    def _seed_authoritative_gates(cls):
        task_fixture = json.loads(
            (FIXTURE_DIR / "workved_45_day_template.json").read_text(encoding="utf-8")
        )
        gate_fixture = json.loads(
            (FIXTURE_DIR / "workved_45_day_external_gates.json").read_text(encoding="utf-8")
        )
        cls.approved_gates = gate_fixture["external_gates"]
        with cls.Session.begin() as session:
            template = V2Template(code=task_fixture["template_code"], name=task_fixture["template_name"])
            draft_template = V2Template(code="draft-gates", name="Draft Gate Template")
            session.add_all([template, draft_template])
            session.flush()
            published = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="approved-external-gates",
                is_current_published=True,
                created_by=ACTOR_ID,
                published_by=ACTOR_ID,
                published_at=datetime.now(timezone.utc),
            )
            draft = V2TemplateVersion(
                template_id=draft_template.id,
                version_no=1,
                status="draft",
                duration_days=45,
                content_hash="draft-external-gates",
                is_current_published=False,
                created_by=ACTOR_ID,
            )
            session.add_all([published, draft])
            session.flush()
            cls.published_id = published.id
            cls.draft_id = draft.id
            tasks_by_code = {}
            for source in task_fixture["tasks"]:
                task = V2TemplateTask(
                    template_version_id=published.id,
                    code=source["code"],
                    sequence_no=source["sequence"],
                    title=source["title"],
                    description=source.get("description"),
                    schedule_classification=source["schedule_classification"],
                    planned_start_day=source.get("planned_start_day"),
                    planned_end_day=source.get("planned_end_day"),
                    phase=source.get("phase"),
                    category=source.get("category"),
                    applicability=source["applicability"],
                    task_class=source.get("task_class"),
                    task_kind=source.get("task_kind"),
                    evidence_required=bool(source.get("evidence_required")),
                    duration_days=source.get("duration_days"),
                )
                session.add(task)
                tasks_by_code[source["code"]] = task
            session.flush()
            for source in cls.approved_gates:
                gate = V2TemplateExternalGate(
                    template_version_id=published.id,
                    code=source["code"],
                    approval_name=source["approval_name"],
                    description=source.get("description"),
                    external_party=source.get("external_party"),
                    required_by_type=source.get("required_by_type"),
                    required_by_value=source.get("required_by_value"),
                    impact=source.get("impact"),
                    mapping_classification=source["mapping_classification"],
                    broad_mapping_text=source.get("broad_mapping_text"),
                    requires_configuration=source["requires_configuration"],
                    sequence_no=source["sequence"],
                )
                session.add(gate)
                session.flush()
                if source["mapping_classification"] == "exact":
                    for task_code in source["task_codes"]:
                        session.add(
                            V2TemplateExternalGateTask(
                                gate_id=gate.id,
                                template_task_id=tasks_by_code[task_code].id,
                            )
                        )

    def service(self, session):
        return TemplateQueryService(session)

    def test_approved_gates_preserve_exact_and_broad_mappings(self):
        with self.Session() as session:
            result = self.service(session).list_gates(UserRole.admin, self.published_id, page_size=100)
        self.assertEqual(result.total, 32)
        self.assertEqual(len(result.items), 32)
        self.assertEqual([item.sequence_no for item in result.items], list(range(1, 33)))
        self.assertTrue(all(item.validation_state == "valid" for item in result.items))
        source_by_code = {row["code"]: row for row in self.approved_gates}
        returned_by_code = {item.code: item for item in result.items}
        self.assertEqual(
            {code for code, item in returned_by_code.items() if item.mapping_classification == "broad_text"},
            KNOWN_BROAD_GATES,
        )
        for code, item in returned_by_code.items():
            source = source_by_code[code]
            self.assertEqual(item.mapping_classification, source["mapping_classification"])
            self.assertEqual(item.broad_mapping_text, source.get("broad_mapping_text"))
            if item.mapping_classification == "exact":
                self.assertEqual([task.code for task in item.affected_tasks], source["task_codes"])
            else:
                self.assertEqual(item.affected_tasks, [])
                self.assertTrue(item.requires_configuration)
        self.assertEqual(returned_by_code["E006"].broad_mapping_text, "T008 onwards")
        self.assertEqual(returned_by_code["E006"].affected_tasks, [])
        self.assertEqual(
            sum(len(item.affected_tasks) for item in result.items),
            sum(len(row["task_codes"]) for row in self.approved_gates if row["mapping_classification"] == "exact"),
        )

    def test_filters_search_validation_and_pagination(self):
        first_party = self.approved_gates[0]["external_party"]
        expected_party = sum(row["external_party"].lower() == first_party.lower() for row in self.approved_gates)
        with self.Session() as session:
            service = self.service(session)
            by_code = service.list_gates(UserRole.admin, self.published_id, search="  e006  ", page_size=100)
            by_text = service.list_gates(UserRole.admin, self.published_id, search="t008 onwards", page_size=100)
            exact = service.list_gates(UserRole.admin, self.published_id, mapping_classification="exact", page_size=100)
            broad = service.list_gates(UserRole.admin, self.published_id, mapping_classification="broad_text", page_size=100)
            configured = service.list_gates(UserRole.admin, self.published_id, requires_configuration=True, page_size=100)
            ready = service.list_gates(UserRole.admin, self.published_id, requires_configuration=False, page_size=100)
            party = service.list_gates(UserRole.admin, self.published_id, external_party=f"  {first_party.upper()}  ", page_size=100)
            valid = service.list_gates(UserRole.admin, self.published_id, validation_state="valid", page_size=100)
            invalid = service.list_gates(UserRole.admin, self.published_id, validation_state="invalid", page_size=100)
            second_page = service.list_gates(UserRole.admin, self.published_id, page=2, page_size=10)
        self.assertEqual([item.code for item in by_code.items], ["E006"])
        self.assertEqual([item.code for item in by_text.items], ["E006"])
        self.assertEqual(exact.total, 26)
        self.assertEqual(broad.total, 6)
        self.assertEqual(configured.total, 6)
        self.assertEqual(ready.total, 26)
        self.assertEqual(party.total, expected_party)
        self.assertEqual(valid.total, 32)
        self.assertEqual(invalid.total, 0)
        self.assertEqual([item.sequence_no for item in second_page.items], list(range(11, 21)))

    def test_role_access_and_nonrevealing_draft_behavior(self):
        with self.Session() as session:
            service = self.service(session)
            for role in (UserRole.super_admin, UserRole.admin, UserRole.project_manager):
                self.assertEqual(service.list_gates(role, self.published_id, page_size=100).total, 32)
            self.assertEqual(service.list_gates(UserRole.super_admin, self.draft_id).total, 0)
            for role in (UserRole.admin, UserRole.project_manager):
                with self.assertRaises(HTTPException) as raised:
                    service.list_gates(role, self.draft_id)
                self.assertEqual(raised.exception.status_code, 404)
            for role in (UserRole.supervisor, UserRole.internal_employee):
                with self.assertRaises(HTTPException) as raised:
                    service.list_gates(role, self.published_id)
                self.assertEqual(raised.exception.status_code, 403)

    def test_route_contract_contains_exact_task_summaries(self):
        with self.Session() as session:
            response = list_template_gates(
                self.published_id,
                search="E001",
                mapping_classification=None,
                requires_configuration=None,
                external_party=None,
                validation_state=None,
                page=1,
                page_size=20,
                actor=actor(UserRole.admin),
                db=session,
            )
        payload = response.model_dump(mode="json")
        self.assertEqual(payload["pagination"], {"page": 1, "page_size": 20, "total": 1, "total_pages": 1})
        item = payload["items"][0]
        self.assertEqual(
            set(item),
            {
                "id", "code", "sequence_no", "approval_name", "description",
                "external_party", "required_by_type", "required_by_value", "impact",
                "mapping_classification", "requires_configuration", "broad_mapping_text",
                "affected_tasks", "validation_state", "validation_issues",
            },
        )
        self.assertEqual(set(item["affected_tasks"][0]), {"id", "code", "title", "phase", "day"})
        self.assertEqual(item["affected_tasks"][0]["code"], "T008")

    def test_validation_reports_all_requested_gate_problems(self):
        version_id = uuid.uuid4()
        other_version_id = uuid.uuid4()
        gate = SimpleNamespace(
            approval_name=" ",
            external_party=None,
            required_by_type="",
            required_by_value=None,
            mapping_classification="unsupported",
            broad_mapping_text=None,
            requires_configuration=False,
            template_version_id=version_id,
        )
        repeated_task_id = uuid.uuid4()
        repeated_task = SimpleNamespace(id=repeated_task_id, template_version_id=other_version_id)
        issues = _gate_validation_issues(
            gate,
            [
                (SimpleNamespace(template_task_id=repeated_task_id), repeated_task),
                (SimpleNamespace(template_task_id=repeated_task_id), repeated_task),
                (SimpleNamespace(template_task_id=uuid.uuid4()), None),
            ],
        )
        for issue in (
            "missing_name",
            "missing_external_party",
            "invalid_required_by",
            "unsupported_mapping_classification",
            "cross_version_mapping",
            "duplicate_mapping",
            "missing_exact_task",
        ):
            self.assertIn(issue, issues)

        exact = SimpleNamespace(**{**gate.__dict__, "approval_name": "Name", "external_party": "Party", "required_by_type": "source_text", "required_by_value": "Before Day 1", "mapping_classification": "exact"})
        self.assertIn("exact_gate_without_tasks", _gate_validation_issues(exact, []))
        broad = SimpleNamespace(**{**exact.__dict__, "mapping_classification": "broad_text", "broad_mapping_text": " ", "requires_configuration": False})
        broad_issues = _gate_validation_issues(broad, [(SimpleNamespace(template_task_id=repeated_task_id), repeated_task)])
        self.assertIn("broad_gate_has_exact_mappings", broad_issues)
        self.assertIn("missing_broad_mapping_text", broad_issues)
        self.assertIn("requires_configuration_missing", broad_issues)
        unmapped = SimpleNamespace(**{**exact.__dict__, "mapping_classification": "unmapped", "requires_configuration": True})
        self.assertIn("unmapped_gate", _gate_validation_issues(unmapped, []))

    def test_gate_endpoint_uses_constant_queries_without_n_plus_one(self):
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with self.Session() as session:
                result = self.service(session).list_gates(UserRole.admin, self.published_id, page_size=100)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(len(result.items), 32)
        self.assertEqual(len(statements), 4)
        self.assertTrue(all("v2_template" in statement for statement in statements))
        self.assertTrue(all("execution_template" not in statement for statement in statements))


if __name__ == "__main__":
    unittest.main()