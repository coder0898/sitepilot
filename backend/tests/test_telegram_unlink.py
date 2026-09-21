"""Admin-only Telegram unlink: frees an employee's telegram_chat_id so a
different employee can connect the same physical Telegram account during
local testing (telegram_chat_id is unique at the DB level).
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent
from app.services.telegram_connect import TelegramConnectService

ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
EMPLOYEE_A_USER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
EMPLOYEE_B_USER_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TelegramUnlinkTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (User.__table__, EmployeeProfile.__table__, V2AuditEvent.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()

        with self.db.begin():
            self.admin = User(id=ADMIN_ID, name="Niddhi Admin", email="admin@example.com", role=UserRole.admin, active=True)
            user_a = User(id=EMPLOYEE_A_USER_ID, name="Employee A", email="a@example.com", role=UserRole.supervisor, active=True)
            user_b = User(id=EMPLOYEE_B_USER_ID, name="Employee B", email="b@example.com", role=UserRole.supervisor, active=True)
            self.db.add_all([self.admin, user_a, user_b])
            self.db.flush()

            self.employee_a = EmployeeProfile(
                user_id=EMPLOYEE_A_USER_ID, employee_code="EMP-A", designation="Supervisor",
                availability="available", telegram_chat_id="555", active_channel="telegram",
            )
            self.employee_b = EmployeeProfile(
                user_id=EMPLOYEE_B_USER_ID, employee_code="EMP-B", designation="Supervisor", availability="available",
            )
            self.db.add_all([self.employee_a, self.employee_b])

        self.service = TelegramConnectService(self.db)

    def tearDown(self):
        self.db.close()

    def test_unlinking_a_connected_employee_clears_chat_id(self):
        result = self.service.unlink_employee(employee_id=self.employee_a.id, actor=self.admin)

        self.assertIsNone(result.telegram_chat_id)
        refreshed = self.db.get(EmployeeProfile, self.employee_a.id)
        self.assertIsNone(refreshed.telegram_chat_id)

    def test_unlink_never_touches_active_channel_or_other_fields(self):
        self.service.unlink_employee(employee_id=self.employee_a.id, actor=self.admin)

        refreshed = self.db.get(EmployeeProfile, self.employee_a.id)
        self.assertEqual(refreshed.active_channel, "telegram")  # untouched, per KTD3-style separation
        self.assertEqual(refreshed.employee_code, "EMP-A")
        self.assertEqual(refreshed.designation, "Supervisor")

    def test_unlinking_writes_one_audit_row(self):
        self.service.unlink_employee(employee_id=self.employee_a.id, actor=self.admin)

        rows = self.db.scalars(select(V2AuditEvent).where(V2AuditEvent.action == "telegram_unlinked")).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].entity_type, "employee")
        self.assertEqual(rows[0].entity_id, self.employee_a.id)
        self.assertEqual(rows[0].actor_user_id, ADMIN_ID)

    def test_unlinking_an_already_unconnected_employee_is_a_silent_no_op(self):
        result = self.service.unlink_employee(employee_id=self.employee_b.id, actor=self.admin)

        self.assertIsNone(result.telegram_chat_id)
        rows = self.db.scalars(select(V2AuditEvent).where(V2AuditEvent.action == "telegram_unlinked")).all()
        self.assertEqual(rows, [])  # no audit row for a non-change

    def test_unknown_employee_raises_404(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.service.unlink_employee(employee_id=uuid.uuid4(), actor=self.admin)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_freed_chat_id_can_be_reused_by_a_different_employee(self):
        # The actual scenario this feature exists for: reuse one real
        # Telegram account across test employees without a unique-constraint
        # collision.
        self.service.unlink_employee(employee_id=self.employee_a.id, actor=self.admin)

        self.employee_b.telegram_chat_id = "555"  # same chat id A just freed
        self.db.commit()

        refreshed_b = self.db.get(EmployeeProfile, self.employee_b.id)
        self.assertEqual(refreshed_b.telegram_chat_id, "555")


if __name__ == "__main__":
    unittest.main()
