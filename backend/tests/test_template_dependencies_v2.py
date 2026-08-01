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
from app.repositories.template_repository import TemplateRepository, _dependency_validation_issues
from app.routes.templates_v2 import list_template_dependencies
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


def actor(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        name=f"{role.value} tester",
        email=f"{role.value}@example.com",
        role=role,
        active=True,
    )


class TemplateDependencyApiTests(unittest.TestCase):
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
        cls._seed_authoritative_graph()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    @classmethod
    def _seed_authoritative_graph(cls):
        task_fixture = json.loads((FIXTURE_DIR / "workved_45_day_template.json").read_text(encoding="utf-8"))
        dependency_fixture = json.loads((FIXTURE_DIR / "workved_45_day_dependencies.json").read_text(encoding="utf-8"))
        cls.approved_dependencies = dependency_fixture["dependencies"]
        with cls.Session.begin() as session:
            template = V2Template(code=task_fixture["template_code"], name=task_fixture["template_name"])
            draft_template = V2Template(code="draft-dependencies", name="Draft Dependency Template")
            session.add_all([template, draft_template])
            session.flush()
            published = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="approved-dependency-graph",
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
                content_hash="draft-dependency-graph",
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
            for source in cls.approved_dependencies:
                session.add(
                    V2TemplateTaskDependency(
                        template_version_id=published.id,
                        predecessor_task_id=tasks_by_code[source["predecessor_task_code"]].id,
                        successor_task_id=tasks_by_code[source["successor_task_code"]].id,
                        dependency_type=source["dependency_type"],
                        blocking=source["blocking"],
                        rule_text=source.get("rule_text"),
                        sequence_no=source["sequence"],
                    )
                )

    def service(self, session):
        return TemplateQueryService(session)

    @staticmethod
    def assert_acyclic(edges):
        adjacency = {}
        indegree = {}
        for predecessor, successor in edges:
            adjacency.setdefault(predecessor, set()).add(successor)
            indegree.setdefault(predecessor, 0)
            indegree[successor] = indegree.get(successor, 0) + 1
        queue = [node for node, degree in indegree.items() if degree == 0]
        visited = 0
        while queue:
            node = queue.pop()
            visited += 1
            for successor in adjacency.get(node, ()):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    queue.append(successor)
        if visited != len(indegree):
            raise AssertionError("Approved dependency graph contains a cycle.")

    def test_exact_approved_graph_is_resolved_supported_unique_and_acyclic(self):
        with self.Session() as session:
            result = self.service(session).list_dependencies(UserRole.admin, self.published_id, page_size=100)
        self.assertEqual(result.total, 38)
        self.assertEqual(len(result.items), 38)
        self.assertEqual([item.sequence_no for item in result.items], list(range(1, 39)))
        self.assertTrue(all(item.predecessor is not None and item.successor is not None for item in result.items))
        self.assertTrue(all(item.dependency_type in {"finish_to_start", "start_to_start"} for item in result.items))
        self.assertTrue(all(item.validation_state == "valid" and not item.validation_issues for item in result.items))
        edges = [(item.predecessor.code, item.successor.code) for item in result.items]
        self.assertTrue(all(predecessor != successor for predecessor, successor in edges))
        typed_edges = {(item.predecessor.code, item.successor.code, item.dependency_type) for item in result.items}
        self.assertEqual(len(typed_edges), 38)
        self.assertTrue(all(code.startswith("T") for edge in edges for code in edge))
        self.assert_acyclic(edges)

    def test_filters_search_validation_and_pagination(self):
        expected_fs = sum(row["dependency_type"] == "finish_to_start" for row in self.approved_dependencies)
        expected_ss = sum(row["dependency_type"] == "start_to_start" for row in self.approved_dependencies)
        expected_blocking = sum(bool(row["blocking"]) for row in self.approved_dependencies)
        with self.Session() as session:
            service = self.service(session)
            search = service.list_dependencies(UserRole.admin, self.published_id, search="  t001  ", page_size=100)
            finish = service.list_dependencies(UserRole.admin, self.published_id, dependency_type="finish_to_start", page_size=100)
            start = service.list_dependencies(UserRole.admin, self.published_id, dependency_type="start_to_start", page_size=100)
            blocking = service.list_dependencies(UserRole.admin, self.published_id, blocking=True, page_size=100)
            nonblocking = service.list_dependencies(UserRole.admin, self.published_id, blocking=False, page_size=100)
            valid = service.list_dependencies(UserRole.admin, self.published_id, validation_state="valid", page_size=100)
            invalid = service.list_dependencies(UserRole.admin, self.published_id, validation_state="invalid", page_size=100)
            second_page = service.list_dependencies(UserRole.admin, self.published_id, page=2, page_size=10)
        self.assertGreaterEqual(search.total, 1)
        self.assertTrue(all("T001" in {item.predecessor.code, item.successor.code} for item in search.items))
        self.assertEqual(finish.total, expected_fs)
        self.assertEqual(start.total, expected_ss)
        self.assertEqual(blocking.total, expected_blocking)
        self.assertEqual(nonblocking.total, 38 - expected_blocking)
        self.assertEqual(valid.total, 38)
        self.assertEqual(invalid.total, 0)
        self.assertEqual(finish.summary.total, 38)
        self.assertEqual(finish.summary.finish_to_start, expected_fs)
        self.assertEqual(finish.summary.start_to_start, expected_ss)
        self.assertEqual(finish.summary.blocking, expected_blocking)
        self.assertEqual(finish.summary.validation_issues, 0)
        self.assertEqual(search.summary, finish.summary)
        self.assertEqual([item.sequence_no for item in second_page.items], list(range(11, 21)))

    def test_role_access_and_nonrevealing_draft_behavior(self):
        with self.Session() as session:
            service = self.service(session)
            for role in (UserRole.super_admin, UserRole.admin, UserRole.project_manager):
                self.assertEqual(service.list_dependencies(role, self.published_id, page_size=100).total, 38)
            self.assertEqual(service.list_dependencies(UserRole.super_admin, self.draft_id).total, 0)
            for role in (UserRole.admin, UserRole.project_manager):
                with self.assertRaises(HTTPException) as raised:
                    service.list_dependencies(role, self.draft_id)
                self.assertEqual(raised.exception.status_code, 404)
            for role in (UserRole.supervisor, UserRole.internal_employee):
                with self.assertRaises(HTTPException) as raised:
                    service.list_dependencies(role, self.published_id)
                self.assertEqual(raised.exception.status_code, 403)

    def test_route_contract_contains_nested_task_references(self):
        with self.Session() as session:
            response = list_template_dependencies(
                self.published_id,
                search=None,
                dependency_type=None,
                blocking=None,
                validation_state=None,
                page=1,
                page_size=1,
                actor=actor(UserRole.admin),
                db=session,
            )
        payload = response.model_dump(mode="json")
        self.assertEqual(payload["pagination"], {"page": 1, "page_size": 1, "total": 38, "total_pages": 38})
        self.assertEqual(
            payload["summary"],
            {
                "total": 38,
                "finish_to_start": sum(
                    row["dependency_type"] == "finish_to_start"
                    for row in self.approved_dependencies
                ),
                "start_to_start": sum(
                    row["dependency_type"] == "start_to_start"
                    for row in self.approved_dependencies
                ),
                "blocking": sum(bool(row["blocking"]) for row in self.approved_dependencies),
                "validation_issues": 0,
            },
        )
        item = payload["items"][0]
        self.assertEqual(
            set(item),
            {
                "id",
                "sequence_no",
                "dependency_type",
                "blocking",
                "rule_text",
                "predecessor",
                "successor",
                "validation_state",
                "validation_issues",
            },
        )
        self.assertEqual(set(item["predecessor"]), {"id", "code", "title", "phase", "day"})

    def test_validation_reports_all_requested_dependency_problems(self):
        shared_id = uuid.uuid4()
        dependency = SimpleNamespace(
            template_version_id=uuid.uuid4(),
            predecessor_task_id=shared_id,
            successor_task_id=shared_id,
            dependency_type="unsupported",
        )
        other_version = uuid.uuid4()
        predecessor = SimpleNamespace(template_version_id=other_version)
        issues = _dependency_validation_issues(
            dependency,
            predecessor,
            None,
            duplicate_pair_count=2,
        )
        self.assertEqual(
            issues,
            [
                "missing_successor",
                "self_dependency",
                "unsupported_dependency_type",
                "duplicate_pair",
                "cross_version_reference",
            ],
        )
        missing = _dependency_validation_issues(dependency, None, None)
        self.assertIn("missing_predecessor", missing)
        self.assertIn("missing_successor", missing)

    def test_dependency_endpoint_uses_constant_queries_without_n_plus_one(self):
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with self.Session() as session:
                result = self.service(session).list_dependencies(UserRole.admin, self.published_id, page_size=100)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(len(result.items), 38)
        self.assertEqual(len(statements), 4)
        self.assertTrue(all("v2_template" in statement for statement in statements))
        self.assertTrue(all("execution_template" not in statement for statement in statements))


if __name__ == "__main__":
    unittest.main()