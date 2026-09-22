"""U3 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
connect-token table, schema-only - no generation/consumption logic yet.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import TelegramConnectToken
from app.models import EmployeeProfile, User, UserRole
from app.vendor_models import V2Vendor, V2VendorContact

EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")


class TelegramConnectTokenModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # SQLite doesn't enforce CHECK constraints via a pragma by
            # default in older drivers - modern sqlite3 does, but foreign
            # keys need this explicit pragma.
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        for table in (
            User.__table__, EmployeeProfile.__table__,
            V2Vendor.__table__, V2VendorContact.__table__, TelegramConnectToken.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed_employee()

    def _seed_employee(self) -> None:
        with self.Session.begin() as session:
            session.add(User(
                id=EMPLOYEE_ID, name="Field Employee", email="field@example.com",
                role=UserRole.supervisor, active=True,
            ))
            session.flush()
            session.add(EmployeeProfile(
                user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Supervisor", availability="available",
            ))

    def _future(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=1)

    def test_row_with_only_employee_id_set_is_valid(self):
        with self.Session.begin() as session:
            session.add(TelegramConnectToken(
                token="tok-employee", employee_id=EMPLOYEE_ID, expires_at=self._future(),
            ))

    def test_row_with_only_vendor_contact_id_set_is_valid(self):
        with self.Session.begin() as session:
            vendor = V2Vendor(name="Acme Electric", contact_person="Acme Owner", phone="+911111111111")
            session.add(vendor)
            session.flush()
            contact = V2VendorContact(vendor_id=vendor.id, name="Jane Doe", phone="+911234567890")
            session.add(contact)
            session.flush()
            session.add(TelegramConnectToken(
                token="tok-vendor", vendor_contact_id=contact.id, expires_at=self._future(),
            ))

    def test_row_with_both_set_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as session:
                session.add(TelegramConnectToken(
                    token="tok-both", employee_id=EMPLOYEE_ID, vendor_contact_id=uuid.uuid4(),
                    expires_at=self._future(),
                ))

    def test_row_with_neither_set_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as session:
                session.add(TelegramConnectToken(token="tok-neither", expires_at=self._future()))


if __name__ == "__main__":
    unittest.main()
