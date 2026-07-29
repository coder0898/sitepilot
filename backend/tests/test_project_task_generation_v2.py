from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectTask
from app.routes.projects_v2 import router
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")


class ProjectTaskGenerationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2Project.__table__,
            V2ProjectTask.__table__,
            V2AuditEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ADMIN_ID,
            name="Admin",
            email="admin@example.com",
            role=UserRole.admin,
            active=True,
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            template = V2Template(code="WORKVED-45", name="Workved 45 Day")
            session.add(template)
            session.flush()
            version = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="approved-template-hash",
                is_current_published=True,
                created_by=ADMIN_ID,
                published_by=ADMIN_ID,
                published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            session.flush()
            tasks = []
            for sequence in range(1, 100):
                code = f"T{sequence:03d}"
                pre_activation = sequence <= 7
                start_day = None if pre_activation else min(sequence - 7, 45)
                tasks.append(
                    V2TemplateTask(
                        template_version_id=version.id,
                        code=code,
                        sequence_no=sequence,
                        title=f"Task {code}",
                        description=f"Description {code}",
                        schedule_classification="pre_activation" if pre_activation else "execution",
                        planned_start_day=start_day,
                        planned_end_day=start_day,
                        phase="Pre-Activation" if pre_activation else "Execution",
                        category="General",
                        applicability="conditional" if sequence == 98 else "mandatory",
                        evidence_required=sequence % 2 == 0,
                        duration_days=None if pre_activation else 1,
                    )
                )
            session.add_all(tasks)
            project = V2Project(
                code="PRJ-GENERATE-001",
                name="Generation Test",
                client_name="Client",
                site_address="Mumbai",
                start_date=date(2026, 8, 1),
                template_version_id=version.id,
                status="draft",
                created_by=ADMIN_ID,
            )
            session.add(project)
            session.flush()
            self.project_id = project.id
            self.version_id = version.id

    def _post(self, project_id=None):
        return self.client.post(f"/api/v2/projects/{project_id or self.project_id}/generate-tasks")

    @staticmethod
    def _template_task_snapshot(task):
        return tuple(getattr(task, column.name) for column in V2TemplateTask.__table__.columns)

    def test_generates_99_tasks_in_t001_to_t099_order_and_preserves_fields(self):
        response = self._post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["generated_task_count"], 99)
        self.assertEqual(response.json()["created_task_count"], 99)
        self.assertFalse(response.json()["no_op"])
        self.assertEqual(response.json()["status"], "draft")

        with self.Session() as session:
            rows = list(session.scalars(select(V2ProjectTask).order_by(V2ProjectTask.template_sequence)).all())
            self.assertEqual(len(rows), 99)
            self.assertEqual([row.original_code for row in rows], [f"T{i:03d}" for i in range(1, 100)])
            self.assertEqual(rows[0].schedule_classification, "pre_activation")
            self.assertIsNone(rows[0].planned_start_day)
            self.assertEqual(rows[6].original_code, "T007")
            self.assertEqual(rows[7].original_code, "T008")
            self.assertEqual(rows[7].schedule_classification, "execution")
            self.assertEqual(rows[7].planned_start_day, 1)
            self.assertEqual(rows[97].applicability, "conditional")
            self.assertTrue(all(row.template_version_id == self.version_id for row in rows))
            self.assertTrue(all(row.source_type == "template" for row in rows))
            self.assertTrue(all(row.lifecycle_status == "draft" for row in rows))
            self.assertTrue(all(row.included is True for row in rows))
            self.assertTrue(all(row.decision_state == "pending_review" for row in rows))
            project = session.get(V2Project, self.project_id)
            self.assertEqual(project.status, "draft")
            audit = session.scalar(select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_TASKS_GENERATED"))
            self.assertIsNotNone(audit)
            self.assertEqual(audit.after_json["generated_task_count"], 99)

    def test_retry_is_no_op_and_creates_no_duplicates_or_second_audit(self):
        first = self._post()
        second = self._post()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["no_op"])
        self.assertEqual(second.json()["created_task_count"], 0)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2ProjectTask)), 99)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_TASKS_GENERATED")),
                1,
            )


    def test_generation_preserves_source_template_and_does_not_activate_or_baseline(self):
        with self.Session() as session:
            version_before = session.get(V2TemplateVersion, self.version_id)
            version_snapshot = tuple(
                getattr(version_before, column.name)
                for column in V2TemplateVersion.__table__.columns
            )
            source_before = [
                self._template_task_snapshot(task)
                for task in session.scalars(
                    select(V2TemplateTask)
                    .where(V2TemplateTask.template_version_id == self.version_id)
                    .order_by(V2TemplateTask.sequence_no, V2TemplateTask.code, V2TemplateTask.id)
                )
            ]

        response = self._post()
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            version_after = session.get(V2TemplateVersion, self.version_id)
            self.assertEqual(
                tuple(getattr(version_after, column.name) for column in V2TemplateVersion.__table__.columns),
                version_snapshot,
            )
            source_tasks = list(session.scalars(
                select(V2TemplateTask)
                .where(V2TemplateTask.template_version_id == self.version_id)
                .order_by(V2TemplateTask.sequence_no, V2TemplateTask.code, V2TemplateTask.id)
            ))
            self.assertEqual(
                [self._template_task_snapshot(task) for task in source_tasks],
                source_before,
            )

            generated = list(session.scalars(
                select(V2ProjectTask)
                .where(V2ProjectTask.project_id == self.project_id)
                .order_by(V2ProjectTask.template_sequence, V2ProjectTask.original_code)
            ))
            self.assertEqual(len(generated), len(source_tasks))
            self.assertEqual(len(generated), 99)
            for source, project_task in zip(source_tasks, generated, strict=True):
                self.assertEqual(project_task.template_version_id, source.template_version_id)
                self.assertEqual(project_task.template_task_id, source.id)
                self.assertEqual(project_task.original_code, source.code)
                self.assertEqual(project_task.template_sequence, source.sequence_no)
                for field in (
                    "title", "description", "schedule_classification",
                    "planned_start_day", "planned_end_day", "phase", "category",
                    "applicability", "task_class", "task_kind",
                    "evidence_required", "duration_days",
                ):
                    self.assertEqual(getattr(project_task, field), getattr(source, field), field)

            project = session.get(V2Project, self.project_id)
            self.assertEqual(project.status, "draft")
            self.assertIsNone(project.activated_at)
            self.assertIsNone(project.activated_by)
            self.assertIsNone(project.target_handover_date)
            self.assertTrue(all(task.lifecycle_status == "draft" for task in generated))

    def test_two_projects_receive_isolated_snapshots_from_the_same_template(self):
        with self.Session.begin() as session:
            second_project = V2Project(
                code="PRJ-GENERATE-002",
                name="Second Generation Test",
                client_name="Second Client",
                site_address="Pune",
                start_date=date(2026, 9, 1),
                template_version_id=self.version_id,
                status="draft",
                created_by=ADMIN_ID,
            )
            session.add(second_project)
            session.flush()
            second_project_id = second_project.id

        first = self._post(self.project_id)
        second = self._post(second_project_id)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)

        with self.Session() as session:
            first_rows = list(session.scalars(
                select(V2ProjectTask)
                .where(V2ProjectTask.project_id == self.project_id)
                .order_by(V2ProjectTask.template_sequence)
            ))
            second_rows = list(session.scalars(
                select(V2ProjectTask)
                .where(V2ProjectTask.project_id == second_project_id)
                .order_by(V2ProjectTask.template_sequence)
            ))
            self.assertEqual(len(first_rows), 99)
            self.assertEqual(len(second_rows), 99)
            self.assertEqual(
                [task.template_task_id for task in first_rows],
                [task.template_task_id for task in second_rows],
            )
            self.assertTrue(
                {task.id for task in first_rows}.isdisjoint({task.id for task in second_rows})
            )
            self.assertTrue(all(task.project_id == self.project_id for task in first_rows))
            self.assertTrue(all(task.project_id == second_project_id for task in second_rows))

    def test_active_project_is_rejected_without_writes(self):
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "active"
        response = self._post()
        self.assertEqual(response.status_code, 409, response.text)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2ProjectTask)), 0)

    def test_failure_rolls_back_every_task_and_audit(self):
        counter = {"value": 0}

        def fail_during_generation(_mapper, _connection, _target):
            counter["value"] += 1
            if counter["value"] == 50:
                raise RuntimeError("simulated task write failure")

        event.listen(V2ProjectTask, "before_insert", fail_during_generation)
        try:
            with self.assertRaises(RuntimeError):
                self._post()
        finally:
            event.remove(V2ProjectTask, "before_insert", fail_during_generation)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2ProjectTask)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2AuditEvent)), 0)
            self.assertEqual(session.get(V2Project, self.project_id).status, "draft")

    def test_non_admin_roles_are_rejected(self):
        for role in (UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee):
            self.app.dependency_overrides[current_user] = lambda role=role: User(
                id=uuid.uuid4(), name=role.value, email=f"{role.value}@example.com", role=role, active=True
            )
            response = self._post()
            self.assertEqual(response.status_code, 403, (role, response.text))


if __name__ == "__main__":
    unittest.main()


def test_generate_tasks_route_is_registered_on_production_app():
    from app.main import create_app

    app = create_app()
    registered = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert ("/api/v2/projects/{project_id}/generate-tasks", "POST") in registered
