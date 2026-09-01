from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import EmployeeProfile, User, UserAccountEvent, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.routes.users import router as users_router
from app.template_models import V2Template, V2TemplateVersion

ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
UNLINKED_TARGET_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
LINKED_TARGET_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
LINKED_SUPABASE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class UnlinkedAccountEditTests(unittest.TestCase):
    """A pre-registered roster row (`invite_user`) has `supabase_user_id ==
    None` until the person's first Google sign-in auto-links it
    (`app.auth.current_user`) - that is the normal, expected state for every
    freshly invited account, not a broken one. `update_user`/
    `set_account_active` used to reject any edit to such an account with
    "This legacy account is not linked to Supabase Auth" - a 409 that
    blocked Admins from correcting a typo'd invite email or offboarding
    someone before their first login, with no way to actually perform the
    "link it" the message asked for (there is no manual-link action
    anywhere). Fixed by treating "not linked yet" as "nothing to sync to
    Supabase" rather than an error - see the same conditional-sync pattern
    `update_my_profile` already used."""

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
            EmployeeProfile.__table__,
            UserAccountEvent.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session.begin() as session:
            session.add(User(
                id=ACTOR_ID, name="Admin", email="admin@example.com",
                role=UserRole.super_admin, active=True, supabase_user_id=uuid.uuid4(),
            ))
            session.add(User(
                id=UNLINKED_TARGET_ID, name="Invited Employee", email="invited@example.com",
                role=UserRole.internal_employee, active=True, supabase_user_id=None,
            ))
            session.add(EmployeeProfile(
                user_id=UNLINKED_TARGET_ID, employee_code="EMP001", designation="Site Engineer",
            ))
            session.add(User(
                id=LINKED_TARGET_ID, name="Linked Employee", email="linked@example.com",
                role=UserRole.internal_employee, active=True, supabase_user_id=LINKED_SUPABASE_ID,
            ))
            session.add(EmployeeProfile(
                user_id=LINKED_TARGET_ID, employee_code="EMP002", designation="Site Engineer",
            ))

        app = FastAPI()
        app.include_router(users_router)

        def override_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[current_user] = lambda: self._actor(app)
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _actor(self, _app) -> User:
        with self.Session() as session:
            return session.get(User, ACTOR_ID)

    # ---- the actual bug: editing/offboarding an unlinked (never-logged-in)
    # account must succeed, not 409 ------------------------------------------

    def test_editing_an_unlinked_account_succeeds_without_calling_supabase(self):
        with patch("app.routes.users.admin_update_user") as mock_admin_update:
            response = self.client.put(f"/api/users/{UNLINKED_TARGET_ID}", json={
                "name": "Invited Employee Edited",
                "email": "invited-edited@example.com",
                "employee_code": "EMP001",
                "designation": "Senior Site Engineer",
            })
        self.assertEqual(response.status_code, 200, response.text)
        mock_admin_update.assert_not_called()

        with self.Session() as session:
            refreshed = session.get(User, UNLINKED_TARGET_ID)
            self.assertEqual(refreshed.email, "invited-edited@example.com")
            self.assertEqual(refreshed.name, "Invited Employee Edited")

    def test_offboarding_an_unlinked_account_succeeds_without_calling_supabase(self):
        with patch("app.routes.users.admin_update_user") as mock_admin_update:
            response = self.client.post(f"/api/users/{UNLINKED_TARGET_ID}/offboard", json={
                "reason": "No longer needed - never signed in.",
            })
        self.assertEqual(response.status_code, 200, response.text)
        mock_admin_update.assert_not_called()

        with self.Session() as session:
            refreshed = session.get(User, UNLINKED_TARGET_ID)
            self.assertFalse(refreshed.active)

    # ---- regression guard: a LINKED account must still sync to Supabase ----

    def test_editing_a_linked_account_still_syncs_to_supabase(self):
        with patch("app.routes.users.admin_update_user") as mock_admin_update:
            response = self.client.put(f"/api/users/{LINKED_TARGET_ID}", json={
                "name": "Linked Employee Edited",
                "email": "linked-edited@example.com",
                "employee_code": "EMP002",
                "designation": "Senior Site Engineer",
            })
        self.assertEqual(response.status_code, 200, response.text)
        mock_admin_update.assert_called_once()
        called_supabase_id = mock_admin_update.call_args.args[0]
        self.assertEqual(called_supabase_id, str(LINKED_SUPABASE_ID))

    def test_offboarding_a_linked_account_still_syncs_to_supabase(self):
        with patch("app.routes.users.admin_update_user") as mock_admin_update:
            response = self.client.post(f"/api/users/{LINKED_TARGET_ID}/offboard", json={
                "reason": "No longer needed.",
            })
        self.assertEqual(response.status_code, 200, response.text)
        mock_admin_update.assert_called_once_with(str(LINKED_SUPABASE_ID), {"ban_duration": "876000h"})


if __name__ == "__main__":
    unittest.main()
