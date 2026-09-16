"""U5 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD1/KTD5): active-channel field + `Recipient.channel` - neither wired
into real routing yet.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import EmployeeProfile, User, UserRole
from app.services.message_dispatch import Recipient
from app.vendor_models import V2Vendor, V2VendorContact

EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")


class ActiveChannelFieldTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (User.__table__, EmployeeProfile.__table__, V2Vendor.__table__, V2VendorContact.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def test_new_employee_profile_defaults_active_channel_to_whatsapp(self):
        with self.Session.begin() as session:
            session.add(User(id=EMPLOYEE_ID, name="Field Employee", email="field@example.com", role=UserRole.supervisor, active=True))
            session.flush()
            profile = EmployeeProfile(user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Supervisor", availability="available")
            session.add(profile)
            session.flush()
            session.refresh(profile)
            self.assertEqual(profile.active_channel, "whatsapp")

    def test_new_vendor_contact_defaults_active_channel_to_whatsapp(self):
        with self.Session.begin() as session:
            vendor = V2Vendor(name="Acme Electric", contact_person="Acme Owner", phone="+911111111111")
            session.add(vendor)
            session.flush()
            contact = V2VendorContact(vendor_id=vendor.id, name="Jane Doe", phone="+911234567890")
            session.add(contact)
            session.flush()
            session.refresh(contact)
            self.assertEqual(contact.active_channel, "whatsapp")

    def test_unsupported_active_channel_value_is_rejected(self):
        user_id = uuid.uuid4()
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as session:
                session.add(User(id=user_id, name="X", email="x@example.com", role=UserRole.supervisor, active=True))
                session.flush()
                session.add(EmployeeProfile(
                    user_id=user_id, employee_code="EMP-002", designation="Supervisor",
                    availability="available", active_channel="sms",
                ))


class RecipientChannelFieldTests(unittest.TestCase):
    def test_constructing_without_channel_defaults_to_whatsapp(self):
        recipient = Recipient(employee_id=uuid.uuid4(), vendor_contact_id=None, phone="+911234567890")
        self.assertEqual(recipient.channel, "whatsapp")

    def test_constructing_with_explicit_channel_is_honored(self):
        recipient = Recipient(employee_id=uuid.uuid4(), vendor_contact_id=None, phone="+911234567890", channel="telegram")
        self.assertEqual(recipient.channel, "telegram")


if __name__ == "__main__":
    unittest.main()
