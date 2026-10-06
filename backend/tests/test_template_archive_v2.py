"""Archiving a template version (2026-09-29 fix): an archived version leaves
the working list and the new-project choices, but stays readable as history.

Before the fix the archive itself succeeded, but the archived version then
vanished from template management entirely - not listed, and its detail
page answered 404 - so the archive looked broken and its history was lost
to the UI.
"""

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
from app.routes.projects_v2 import router as projects_router
from app.routes.templates_v2 import router as templates_router
from app.services.template_mutation_access import concurrency_token
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)

SUPER_ADMIN = User(id=uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"), name="Super Admin",
                   email="super@example.com", role=UserRole.super_admin, active=True)
ADMIN = User(id=uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"), name="Admin",
             email="admin@example.com", role=UserRole.admin, active=True)


class TemplateArchiveTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            V2Template.__table__, V2TemplateVersion.__table__, V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__, V2TemplateExternalGate.__table__, V2TemplateExternalGateTask.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.versions = self._seed()

        app = FastAPI()
        app.include_router(templates_router)
        app.include_router(projects_router)

        def override_db():
            with self.Session() as session:
                session.scalar(select(func.count()).select_from(V2Template))
                yield session

        self.actor = SUPER_ADMIN
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[current_user] = lambda: self.actor
        self.client = TestClient(app)
        self.audit = patch("app.services.template_lifecycle_service.write_template_audit_event")
        self.audit.start()

    def tearDown(self):
        self.audit.stop()
        self.client.close()
        self.engine.dispose()

    def _seed(self) -> dict[int, uuid.UUID]:
        ids = {}
        with self.Session.begin() as session:
            template = V2Template(code="WORKVED-45", name="Workved 45 Day", description="Template.")
            session.add(template)
            session.flush()
            for no, current in ((1, False), (2, True)):
                version = V2TemplateVersion(
                    template_id=template.id, version_no=no, status="published", duration_days=45,
                    change_note=f"v{no}", content_hash=f"hash-{no}", is_current_published=current,
                    created_by=SUPER_ADMIN.id, published_by=SUPER_ADMIN.id, published_at=datetime.now(timezone.utc),
                )
                session.add(version)
                session.flush()
                session.add(V2TemplateTask(
                    template_version_id=version.id, code="T008", sequence_no=1, title="Site handover",
                    schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                    phase="Mobilisation", category="Site", applicability="mandatory", evidence_required=False,
                    duration_days=1,
                ))
                ids[no] = version.id
        return ids

    def token(self, version_no: int) -> str:
        with self.Session() as session:
            return concurrency_token(session.get(V2TemplateVersion, self.versions[version_no]))

    def archive(self, version_no: int, replacement_no: int | None = None):
        body = {"revision_token": self.token(version_no), "reason": "No longer used for new projects."}
        if replacement_no is not None:
            body["replacement_current_version_id"] = str(self.versions[replacement_no])
        return self.client.post(f"/api/v2/templates/versions/{self.versions[version_no]}/archive", json=body)

    def listed(self, status: str | None = None) -> list[tuple[int, str]]:
        params = {"page_size": 100, **({"status": status} if status else {})}
        body = self.client.get("/api/v2/templates", params=params).json()
        return sorted((item["version_no"], item["status"]) for item in body["items"])

    def project_form_choices(self) -> list[int]:
        return sorted(item["version_no"] for item in self.client.get("/api/v2/projects/published-template-versions").json())

    def test_archive_moves_the_version_to_history_and_out_of_project_creation(self):
        response = self.archive(1)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "archived")

        self.assertEqual(self.listed(), [(2, "published")])  # working list
        self.assertEqual(self.listed("archived"), [(1, "archived")])  # history
        self.assertEqual(self.project_form_choices(), [2])

        # Its detail and tasks stay readable (this answered 404 before the fix).
        detail = self.client.get(f"/api/v2/templates/versions/{self.versions[1]}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["status"], "archived")
        tasks = self.client.get(f"/api/v2/templates/versions/{self.versions[1]}/tasks")
        self.assertEqual(tasks.status_code, 200, tasks.text)

    def test_archiving_the_current_version_requires_a_replacement(self):
        refused = self.archive(2)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["detail"]["code"], "replacement_current_required")

        response = self.archive(2, replacement_no=1)
        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as session:
            v1, v2 = (session.get(V2TemplateVersion, self.versions[n]) for n in (1, 2))
            self.assertEqual((v1.status, v1.is_current_published), ("published", True))
            self.assertEqual((v2.status, v2.is_current_published), ("archived", False))
        self.assertEqual(self.project_form_choices(), [1])

    def test_an_archived_version_stays_read_only(self):
        self.archive(1)
        with self.Session() as session:
            before = session.scalar(select(func.count()).select_from(V2TemplateTask))
        # Cannot be archived again, cloned, or edited.
        self.assertEqual(self.archive(1).status_code, 409)
        clone = self.client.post(f"/api/v2/templates/versions/{self.versions[1]}/clone", json={"change_note": "x"})
        self.assertEqual(clone.status_code, 404)
        edit = self.client.post(
            f"/api/v2/templates/versions/{self.versions[1]}/tasks",
            json={"revision_token": self.token(1), "code": "T100", "title": "New", "phase": "P", "category": "C",
                  "schedule_classification": "execution", "planned_start_day": 1, "planned_end_day": 1,
                  "applicability": "mandatory", "evidence_required": False},
        )
        self.assertIn(edit.status_code, (404, 409, 422), edit.text)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2TemplateTask)), before)

    def test_admin_can_archive_and_sees_archived_history_like_super_admin(self):
        self.actor = ADMIN
        response = self.archive(1)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.listed(), [(2, "published")])  # working list
        self.assertEqual(self.listed("archived"), [(1, "archived")])  # history
        self.assertEqual(self.client.get(f"/api/v2/templates/versions/{self.versions[1]}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
