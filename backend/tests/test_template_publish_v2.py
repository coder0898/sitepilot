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
from app.services.template_publish_service import compute_persisted_content_hash
from app.repositories.template_validation_repository import TemplateValidationRepository
from app.template_models import (
    V2Template, V2TemplateTask, V2TemplateVersion,
    V2TemplateTaskDependency, V2TemplateExternalGate, V2TemplateExternalGateTask,
)

ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class TemplatePublishApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach(dbapi_connection, _):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (V2Template.__table__, V2TemplateVersion.__table__, V2TemplateTask.__table__, V2TemplateTaskDependency.__table__, V2TemplateExternalGate.__table__, V2TemplateExternalGateTask.__table__):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI(); self.app.include_router(router)
        def db_override():
            with self.Session() as s:
                s.scalar(select(func.count()).select_from(V2Template))
                yield s
        self.app.dependency_overrides[get_db] = db_override
        self.role = UserRole.super_admin
        self.app.dependency_overrides[current_user] = lambda: User(id=ACTOR_ID, name="Actor", email="a@example.com", role=self.role, active=True)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close(); self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as s:
            template = V2Template(code="PUB", name="Publish Template", description="Source")
            s.add(template); s.flush()
            old = V2TemplateVersion(
                template_id=template.id, version_no=1, status="published", duration_days=45,
                change_note="Old", content_hash="oldhash", is_current_published=True,
                created_by=ACTOR_ID, published_by=ACTOR_ID,
                published_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
                updated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            )
            draft = V2TemplateVersion(
                template_id=template.id, version_no=2, status="draft", duration_days=45,
                change_note="Ready to publish", is_current_published=False, created_by=ACTOR_ID,
                updated_at=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
            )
            invalid = V2TemplateVersion(
                template_id=template.id, version_no=3, status="draft", duration_days=45,
                change_note="Invalid", is_current_published=False, created_by=ACTOR_ID,
                updated_at=datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
            )
            s.add_all([old, draft, invalid]); s.flush()
            s.add(V2TemplateTask(
                template_version_id=draft.id, code="T001", sequence_no=1, title="Task",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", evidence_required=False, duration_days=1,
            ))
            self.template_id, self.old_id, self.draft_id, self.invalid_id = template.id, old.id, draft.id, invalid.id

    def revision(self, version_id):
        with self.Session() as s:
            return concurrency_token(s.get(V2TemplateVersion, version_id))

    def publish(self, version_id, token=None, note="Approved release"):
        return self.client.post(
            f"/api/v2/templates/versions/{version_id}/publish",
            json={"revision_token": token or self.revision(version_id), "change_note": note},
        )

    def test_valid_draft_publishes_atomically_and_writes_one_audit(self):
        with patch("app.services.template_publish_service.write_template_audit_event") as audit:
            response = self.publish(self.draft_id)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json(); self.assertEqual(body["status"], "published")
        self.assertEqual(len(body["content_hash"]), 64)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[1].action, TemplateAuditAction.TEMPLATE_VERSION_PUBLISHED)
        with self.Session() as s:
            old = s.get(V2TemplateVersion, self.old_id); current = s.get(V2TemplateVersion, self.draft_id)
            self.assertEqual(old.status, "published")
            self.assertFalse(old.is_current_published)
            self.assertTrue(current.is_current_published)
            self.assertEqual(current.content_hash, body["content_hash"])
            count = s.scalar(select(func.count()).select_from(V2TemplateVersion).where(V2TemplateVersion.template_id == self.template_id, V2TemplateVersion.is_current_published.is_(True)))
            self.assertEqual(count, 1)
            expected = compute_persisted_content_hash(TemplateValidationRepository(s).load(self.draft_id))
            self.assertEqual(current.content_hash, expected)

    def test_invalid_draft_rejected_without_marker_or_status_writes(self):
        before_old = None
        with self.Session() as s: before_old = s.get(V2TemplateVersion, self.old_id).is_current_published
        with patch("app.services.template_publish_service.write_template_audit_event") as audit:
            response = self.publish(self.invalid_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "template_validation_failed")
        audit.assert_not_called()
        with self.Session() as s:
            self.assertEqual(s.get(V2TemplateVersion, self.invalid_id).status, "draft")
            self.assertEqual(s.get(V2TemplateVersion, self.old_id).is_current_published, before_old)

    def test_second_publish_is_rejected_and_published_is_immutable(self):
        with patch("app.services.template_publish_service.write_template_audit_event"):
            first = self.publish(self.draft_id)
        self.assertEqual(first.status_code, 200)
        second = self.client.post(f"/api/v2/templates/versions/{self.draft_id}/publish", json={"revision_token": self.revision(self.draft_id), "change_note": "Again"})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"]["code"], "template_version_immutable")

    def test_stale_revision_and_missing_change_note_rejected_without_writes(self):
        stale = self.publish(self.draft_id, token="2020-01-01T00:00:00Z")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["code"], "stale_template_version")
        with self.Session.begin() as s:
            version = s.get(V2TemplateVersion, self.draft_id); version.change_note = None
        missing = self.publish(self.draft_id, note="")
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["detail"]["code"], "change_note_required")

    def test_non_super_admin_forbidden(self):
        for role in (UserRole.admin, UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee):
            with self.subTest(role=role):
                self.role = role
                response = self.publish(self.draft_id)
                self.assertEqual(response.status_code, 403)

    def test_audit_failure_rolls_back_status_marker_hash_and_audit(self):
        def fail(*_args, **_kwargs):
            raise RuntimeError("audit failed")
        with patch("app.services.template_publish_service.write_template_audit_event", side_effect=fail):
            with self.assertRaises(RuntimeError):
                # TestClient raises server exceptions by default.
                self.publish(self.draft_id)
        with self.Session() as s:
            draft = s.get(V2TemplateVersion, self.draft_id); old = s.get(V2TemplateVersion, self.old_id)
            self.assertEqual(draft.status, "draft")
            self.assertFalse(draft.is_current_published)
            self.assertIsNone(draft.content_hash)
            self.assertTrue(old.is_current_published)


if __name__ == "__main__":
    unittest.main()
