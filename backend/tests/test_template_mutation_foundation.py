from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import current_user
from app.models import User, UserRole
from app.repositories.template_mutation_repository import TemplateMutationRepository
from app.services.template_audit import (
    TemplateAuditAction,
    TemplateAuditWrite,
    write_template_audit_event,
)
from app.services.template_mutation_access import (
    concurrency_token,
    require_current_concurrency_token,
    require_draft_template_version,
    require_template_mutator,
)
from app.services.transaction_boundary import command_transaction


class MutationAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()

        @app.post("/mutation-check")
        def mutation_check(actor: User = Depends(require_template_mutator)):
            return {"role": actor.role.value}

        cls.app = app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def request_as(self, role: UserRole | None):
        self.app.dependency_overrides.pop(current_user, None)
        if role is not None:
            self.app.dependency_overrides[current_user] = lambda: User(
                id=uuid.uuid4(),
                name="Mutation tester",
                email=f"{role.value}@example.com",
                role=role,
                active=True,
            )
        return self.client.post("/mutation-check")

    def test_super_admin_mutation_allowed(self):
        response = self.request_as(UserRole.super_admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"role": "super_admin"})

    def test_all_other_authenticated_roles_forbidden(self):
        for role in (
            UserRole.admin,
            UserRole.project_manager,
            UserRole.supervisor,
            UserRole.internal_employee,
        ):
            with self.subTest(role=role):
                self.assertEqual(self.request_as(role).status_code, 403)

    def test_unauthenticated_keeps_existing_401(self):
        response = self.request_as(None)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Login required.")


class GuardAndConcurrencyTests(unittest.TestCase):
    def version(self, status="draft", updated_at=None):
        return SimpleNamespace(
            id=uuid.uuid4(),
            status=status,
            updated_at=updated_at or datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc),
        )

    def test_draft_mutation_allowed(self):
        version = self.version("draft")
        self.assertIs(require_draft_template_version(version), version)

    def test_published_mutation_rejected(self):
        with self.assertRaises(Exception) as raised:
            require_draft_template_version(self.version("published"))
        exc = raised.exception
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(exc.detail["code"], "template_version_immutable")

    def test_missing_version_has_stable_not_found(self):
        with self.assertRaises(Exception) as raised:
            require_draft_template_version(None)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Template version not found.")

    def test_stale_revision_rejected_with_structured_conflict(self):
        version = self.version()
        current = concurrency_token(version)
        with self.assertRaises(Exception) as raised:
            require_current_concurrency_token(version, "2020-01-01T00:00:00Z")
        exc = raised.exception
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(exc.detail["code"], "stale_template_version")
        self.assertEqual(exc.detail["current_token"], current)

    def test_repository_rejects_stale_token_before_touch_or_flush(self):
        version = self.version()
        result = Mock()
        result.scalar_one_or_none.return_value = version
        db = Mock()
        db.execute.return_value = result
        repository = TemplateMutationRepository(db)

        with self.assertRaises(Exception):
            repository.get_version_for_mutation(
                version.id,
                expected_token="stale-token",
                lock=False,
            )

        db.flush.assert_not_called()
        self.assertEqual(version.updated_at, datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc))


class FakeAuditSession:
    def __init__(self):
        self.pending = []
        self.persisted = []
        self._in_transaction = False
        self.rollback_calls = 0

    def in_transaction(self):
        return self._in_transaction

    def add(self, value):
        self.pending.append(value)

    def rollback(self):
        self.rollback_calls += 1
        self.pending.clear()
        self._in_transaction = False

    def begin(self):
        session = self

        class Transaction:
            def __enter__(self):
                session._in_transaction = True
                return session

            def __exit__(self, exc_type, exc, tb):
                if exc_type is None:
                    session.persisted.extend(session.pending)
                    session.pending.clear()
                else:
                    session.pending.clear()
                session._in_transaction = False
                return False

        return Transaction()


class AuditFoundationTests(unittest.TestCase):
    def audit_write(self):
        return TemplateAuditWrite(
            action=TemplateAuditAction.TEMPLATE_TASK_UPDATED,
            entity_type="template_task",
            entity_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            reason="Update draft task title.",
            before_json={"title": "Before"},
            after_json={"title": "After"},
        )

    def test_audit_event_created_once_for_successful_mutation(self):
        db = FakeAuditSession()
        with command_transaction(db):
            write_template_audit_event(db, self.audit_write())
        self.assertEqual(len(db.persisted), 1)
        self.assertEqual(db.persisted[0].action, "template_task_updated")

    def test_no_audit_event_on_rolled_back_mutation(self):
        db = FakeAuditSession()
        with self.assertRaises(RuntimeError):
            with command_transaction(db):
                write_template_audit_event(db, self.audit_write())
                raise RuntimeError("Force rollback")
        self.assertEqual(db.persisted, [])
        self.assertEqual(db.pending, [])

    def test_unsupported_audit_action_is_rejected(self):
        db = FakeAuditSession()
        invalid = TemplateAuditWrite(
            action="unknown_action",
            entity_type="template_version",
            entity_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            reason="Invalid action test.",
        )
        with self.assertRaises(ValueError):
            write_template_audit_event(db, invalid)
        self.assertEqual(db.pending, [])


if __name__ == "__main__":
    unittest.main()
