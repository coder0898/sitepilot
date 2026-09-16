"""U15 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD1/KTD2): Admin/Super-Admin channel toggle, singly or in bulk, audited
via the existing generic audit table.
"""

from __future__ import annotations

import unittest
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent
from app.routes.channel_toggle import router as channel_toggle_router
from app.vendor_models import V2Vendor, V2VendorContact

ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
SUPERVISOR_USER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
NO_CHATID_USER_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class ChannelToggleApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2AuditEvent.__table__,
            V2Vendor.__table__, V2VendorContact.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()

        with self.session.begin():
            self.session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            self.session.add(User(id=SUPERVISOR_USER_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True))
            self.session.add(User(id=NO_CHATID_USER_ID, name="No Chat", email="nochat@example.com", role=UserRole.supervisor, active=True))
            self.session.flush()
            self.connected_profile = EmployeeProfile(
                user_id=SUPERVISOR_USER_ID, employee_code="EMP-001", designation="Supervisor",
                availability="available", telegram_chat_id="555",
            )
            self.no_chatid_profile = EmployeeProfile(
                user_id=NO_CHATID_USER_ID, employee_code="EMP-002", designation="Supervisor", availability="available",
            )
            self.session.add_all([self.connected_profile, self.no_chatid_profile])

        self.app = FastAPI()
        self.app.include_router(channel_toggle_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def act_as(self, role: UserRole) -> None:
        self._current_actor = User(id=uuid.uuid4(), name="Actor", email="actor@example.com", role=role, active=True)

    def _audit_rows(self) -> list[V2AuditEvent]:
        with self.Session() as session:
            return list(session.scalars(select(V2AuditEvent).where(V2AuditEvent.action == "channel_toggled")))

    def test_single_toggle_to_telegram_succeeds_with_chat_id_set(self):
        response = self.client.post("/api/v2/channel-toggle", json={
            "targets": [{"employee_id": str(self.connected_profile.id)}], "channel": "telegram",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["results"][0]["success"])
        with self.Session() as session:
            profile = session.get(EmployeeProfile, self.connected_profile.id)
            self.assertEqual(profile.active_channel, "telegram")
        self.assertEqual(len(self._audit_rows()), 1)

    def test_single_toggle_to_telegram_without_chat_id_is_rejected(self):
        response = self.client.post("/api/v2/channel-toggle", json={
            "targets": [{"employee_id": str(self.no_chatid_profile.id)}], "channel": "telegram",
        })

        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertFalse(result["success"])
        with self.Session() as session:
            profile = session.get(EmployeeProfile, self.no_chatid_profile.id)
            self.assertEqual(profile.active_channel, "whatsapp")
        self.assertEqual(len(self._audit_rows()), 0)

    def test_bulk_toggle_reports_per_person_failure_not_whole_batch_failure(self):
        response = self.client.post("/api/v2/channel-toggle", json={
            "targets": [
                {"employee_id": str(self.connected_profile.id)},
                {"employee_id": str(self.no_chatid_profile.id)},
            ],
            "channel": "telegram",
        })

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertTrue(results[0]["success"])
        self.assertFalse(results[1]["success"])
        self.assertEqual(len(self._audit_rows()), 1)

    def test_non_admin_cannot_toggle(self):
        self.act_as(UserRole.supervisor)

        response = self.client.post("/api/v2/channel-toggle", json={
            "targets": [{"employee_id": str(self.connected_profile.id)}], "channel": "telegram",
        })

        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_read_audit(self):
        self.act_as(UserRole.supervisor)

        response = self.client.get("/api/v2/channel-toggle/audit")

        self.assertEqual(response.status_code, 403)

    def test_toggle_back_to_whatsapp_succeeds_unconditionally_and_is_audited(self):
        with self.Session.begin() as session:
            profile = session.get(EmployeeProfile, self.connected_profile.id)
            profile.active_channel = "telegram"

        response = self.client.post("/api/v2/channel-toggle", json={
            "targets": [{"employee_id": str(self.connected_profile.id)}], "channel": "whatsapp",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["results"][0]["success"])
        self.assertEqual(len(self._audit_rows()), 1)

    def test_audit_read_endpoint_reflects_a_toggle(self):
        self.client.post("/api/v2/channel-toggle", json={
            "targets": [{"employee_id": str(self.connected_profile.id)}], "channel": "telegram",
        })

        response = self.client.get("/api/v2/channel-toggle/audit")

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["after"]["active_channel"], "telegram")


if __name__ == "__main__":
    unittest.main()
