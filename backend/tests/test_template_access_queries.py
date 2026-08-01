from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.auth import current_user
from app.database import Base
from app.models import UserRole
from app.repositories.template_repository import TemplateRepository
from app.services.template_access import allowed_template_statuses, require_template_module_access
from app.services.template_queries import TEMPLATE_NOT_FOUND_DETAIL, TemplateQueryService
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)


ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class TemplateAccessQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite+pysqlite:///:memory:")

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

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    @classmethod
    def _seed(cls):
        with cls.Session.begin() as session:
            draft_template = V2Template(code="alpha-draft", name="Alpha Secret Draft")
            published_template = V2Template(code="alpha-published", name="Alpha Published")
            beta_template = V2Template(code="beta-published", name="Beta Published")
            session.add_all([draft_template, published_template, beta_template])
            session.flush()

            draft = V2TemplateVersion(
                template_id=draft_template.id,
                version_no=1,
                status="draft",
                duration_days=45,
                content_hash="draft-hash",
                is_current_published=False,
                created_by=ACTOR_ID,
            )
            published = V2TemplateVersion(
                template_id=published_template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="published-hash",
                is_current_published=True,
                created_by=ACTOR_ID,
                published_by=ACTOR_ID,
                published_at=datetime.now(timezone.utc),
            )
            beta = V2TemplateVersion(
                template_id=beta_template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="beta-hash",
                is_current_published=True,
                created_by=ACTOR_ID,
                published_by=ACTOR_ID,
                published_at=datetime.now(timezone.utc),
            )
            session.add_all([draft, published, beta])
            session.flush()
            cls.draft_id = draft.id
            cls.published_id = published.id

            draft_tasks = [
                cls._task(draft.id, "D001", 1),
                cls._task(draft.id, "D002", 2),
            ]
            published_tasks = [
                cls._task(published.id, "P001", 1),
                cls._task(published.id, "P002", 2),
            ]
            session.add_all(draft_tasks + published_tasks)
            session.flush()
            session.add_all(
                [
                    V2TemplateTaskDependency(
                        template_version_id=draft.id,
                        predecessor_task_id=draft_tasks[0].id,
                        successor_task_id=draft_tasks[1].id,
                        dependency_type="finish_to_start",
                        blocking=True,
                        sequence_no=1,
                    ),
                    V2TemplateTaskDependency(
                        template_version_id=published.id,
                        predecessor_task_id=published_tasks[0].id,
                        successor_task_id=published_tasks[1].id,
                        dependency_type="finish_to_start",
                        blocking=True,
                        sequence_no=1,
                    ),
                ]
            )
            draft_gate = V2TemplateExternalGate(
                template_version_id=draft.id,
                code="ED01",
                approval_name="Draft-only approval",
                mapping_classification="broad_text",
                broad_mapping_text="Draft activities",
                requires_configuration=True,
                sequence_no=1,
            )
            published_exact_gate = V2TemplateExternalGate(
                template_version_id=published.id,
                code="EP01",
                approval_name="Published exact approval",
                mapping_classification="exact",
                requires_configuration=False,
                sequence_no=1,
            )
            published_broad_gate = V2TemplateExternalGate(
                template_version_id=published.id,
                code="EP02",
                approval_name="Published broad approval",
                mapping_classification="broad_text",
                broad_mapping_text="Relevant published activities",
                requires_configuration=True,
                sequence_no=2,
            )
            session.add_all([draft_gate, published_exact_gate, published_broad_gate])
            session.flush()
            session.add(
                V2TemplateExternalGateTask(
                    gate_id=published_exact_gate.id,
                    template_task_id=published_tasks[0].id,
                )
            )

    @staticmethod
    def _task(version_id, code, sequence):
        return V2TemplateTask(
            template_version_id=version_id,
            code=code,
            sequence_no=sequence,
            title=code,
            schedule_classification="execution",
            planned_start_day=sequence,
            planned_end_day=sequence,
            applicability="mandatory",
            evidence_required=False,
        )

    def service(self, session: Session):
        return TemplateQueryService(session)

    def test_super_admin_can_query_draft_and_published(self):
        with self.Session() as session:
            page = self.service(session).list_versions(UserRole.super_admin)
            self.assertEqual(3, page.total)
            self.assertEqual({"draft", "published"}, {item.status for item in page.items})

    def test_admin_and_pm_queries_return_published_only(self):
        with self.Session() as session:
            for role in (UserRole.admin, UserRole.project_manager):
                page = self.service(session).list_versions(role)
                self.assertEqual(2, page.total)
                self.assertTrue(all(item.status == "published" for item in page.items))

    def test_supervisor_and_internal_employee_receive_403(self):
        with self.Session() as session:
            for role in (UserRole.supervisor, UserRole.internal_employee):
                with self.assertRaises(HTTPException) as raised:
                    self.service(session).list_versions(role)
                self.assertEqual(403, raised.exception.status_code)

    def test_admin_and_pm_direct_draft_access_returns_nonrevealing_404(self):
        with self.Session() as session:
            for role in (UserRole.admin, UserRole.project_manager):
                with self.assertRaises(HTTPException) as raised:
                    self.service(session).get_version(role, self.draft_id)
                self.assertEqual(404, raised.exception.status_code)
                self.assertEqual(TEMPLATE_NOT_FOUND_DETAIL, raised.exception.detail)

    def test_pagination_total_excludes_drafts_and_order_is_deterministic(self):
        with self.Session() as session:
            first = self.service(session).list_versions(UserRole.admin, page=1, page_size=1)
            second = self.service(session).list_versions(UserRole.admin, page=2, page_size=1)
            self.assertEqual(2, first.total)
            self.assertEqual("alpha-published", first.items[0].template_code)
            self.assertEqual("beta-published", second.items[0].template_code)

    def test_search_and_status_filters_do_not_reveal_drafts(self):
        with self.Session() as session:
            admin_search = self.service(session).list_versions(UserRole.admin, search="Secret Draft")
            admin_draft_filter = self.service(session).list_versions(UserRole.admin, statuses={"draft"})
            super_search = self.service(session).list_versions(UserRole.super_admin, search="Secret Draft")
            self.assertEqual(0, admin_search.total)
            self.assertEqual(0, admin_draft_filter.total)
            self.assertEqual(1, super_search.total)
            self.assertEqual("draft", super_search.items[0].status)

    def test_aggregate_counts_exclude_inaccessible_versions(self):
        with self.Session() as session:
            admin = self.service(session).aggregate_counts(UserRole.admin)
            super_admin = self.service(session).aggregate_counts(UserRole.super_admin)
            self.assertEqual(
                {
                    "version_count": 2,
                    "task_count": 2,
                    "dependency_count": 1,
                    "gate_count": 2,
                    "exact_mapping_count": 1,
                    "broad_text_gate_count": 1,
                },
                admin.to_dict(),
            )
            self.assertEqual(3, super_admin.version_count)
            self.assertEqual(4, super_admin.task_count)
            self.assertEqual(2, super_admin.dependency_count)
            self.assertEqual(3, super_admin.gate_count)

    def test_published_only_and_allowed_status_helpers(self):
        self.assertEqual(frozenset({"draft", "published"}), allowed_template_statuses(UserRole.super_admin))
        self.assertEqual(frozenset({"published"}), allowed_template_statuses(UserRole.admin))
        with self.Session() as session:
            page = TemplateRepository(session).list_versions(UserRole.super_admin, statuses={"published"})
            self.assertEqual(2, page.total)

    def test_unauthenticated_behavior_remains_existing_401(self):
        with self.assertRaises(HTTPException) as raised:
            current_user(credentials=None, db=None)
        self.assertEqual(401, raised.exception.status_code)

    def test_legacy_template_tables_are_never_queried(self):
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with self.Session() as session:
                self.service(session).list_versions(UserRole.super_admin, search="alpha")
                self.service(session).get_version(UserRole.super_admin, self.published_id)
                self.service(session).aggregate_counts(UserRole.super_admin)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        combined = "\n".join(statements)
        self.assertNotIn("execution_templates", combined)
        self.assertNotIn("execution_template_tasks", combined)
        self.assertNotIn("task_templates", combined)
        self.assertIn("v2_template_versions", combined)

    def test_module_role_check_is_reusable(self):
        self.assertEqual(UserRole.admin, require_template_module_access(UserRole.admin))
        with self.assertRaises(HTTPException) as raised:
            require_template_module_access(UserRole.supervisor)
        self.assertEqual(403, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()
