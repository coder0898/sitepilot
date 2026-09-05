from __future__ import annotations

import unittest
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import OutboxEvent
from app.models import EmployeeProfile, User, UserAccountEvent, UserRole
from app.routes.users import router as users_router

ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")


class UserInviteOutboxEmissionTests(unittest.TestCase):
    """U13: `invite_user` emits a `user.created` outbox event (R13) resolving
    to the newly invited user themselves, in the same transaction as the
    roster row and its `EmployeeProfile` - follows the exact
    `OutboxService(db).emit(...)` call shape U1-U3 already established (see
    `activate_project` in `app.routes.projects_v2`)."""

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
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session.begin() as session:
            session.add(User(
                id=ACTOR_ID, name="Admin", email="admin@example.com",
                role=UserRole.super_admin, active=True, supabase_user_id=uuid.uuid4(),
            ))

        app = FastAPI()
        app.include_router(users_router)

        def override_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[current_user] = lambda: self._actor()
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _actor(self) -> User:
        with self.Session() as session:
            return session.get(User, ACTOR_ID)

    def _outbox_events(self) -> list[OutboxEvent]:
        with self.Session() as session:
            return list(session.scalars(select(OutboxEvent)).all())

    def test_inviting_a_user_emits_one_user_created_event(self):
        response = self.client.post("/api/users/invite", json={
            "name": "New Employee",
            "email": "new-employee@example.com",
            "phone": "+919876543210",
            "role": UserRole.internal_employee.value,
            "employee_code": "EMP100",
            "designation": "Site Engineer",
        })
        self.assertEqual(response.status_code, 200, response.text)
        new_user_id = uuid.UUID(response.json()["id"])

        events = self._outbox_events()
        self.assertEqual(len(events), 1)
        emitted = events[0]
        self.assertEqual(emitted.event_type, "user.created")
        self.assertEqual(emitted.aggregate_type, "user")
        self.assertEqual(emitted.aggregate_id, new_user_id)
        self.assertEqual(emitted.payload, {"user_id": str(new_user_id), "name": "New Employee"})
        self.assertEqual(emitted.status, "pending")


if __name__ == "__main__":
    unittest.main()
