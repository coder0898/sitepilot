"""U8 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD5): read-only channel lookup - always returns 'whatsapp' today since no
one has been toggled yet. Not called from `_dispatch_to_recipient` or
`_build_adapter` yet (U9).
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import EmployeeProfile, User, UserRole
from app.services.message_dispatch import MessageDispatchService, Recipient
from app.vendor_models import V2Vendor, V2VendorContact

EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")


class ChannelLookupTests(unittest.TestCase):
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
        self.session = self.Session()
        self.service = MessageDispatchService(self.session)

    def tearDown(self):
        self.session.close()

    def test_employee_recipient_resolves_to_whatsapp(self):
        with self.session.begin():
            self.session.add(User(id=EMPLOYEE_ID, name="Field Employee", email="field@example.com", role=UserRole.supervisor, active=True))
            self.session.flush()
            profile = EmployeeProfile(user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Supervisor", availability="available")
            self.session.add(profile)
            self.session.flush()
            profile_id = profile.id

        # `Recipient.employee_id` holds `EmployeeProfile.id`, not `User.id` -
        # same convention every real resolver in message_dispatch.py uses.
        recipient = Recipient(employee_id=profile_id, vendor_contact_id=None, phone="+911234567890")
        self.assertEqual(self.service._resolve_recipient_channel(recipient), "whatsapp")

    def test_employee_recipient_with_telegram_active_channel_resolves_to_telegram(self):
        with self.session.begin():
            self.session.add(User(id=EMPLOYEE_ID, name="Field Employee", email="field@example.com", role=UserRole.supervisor, active=True))
            self.session.flush()
            profile = EmployeeProfile(
                user_id=EMPLOYEE_ID, employee_code="EMP-002", designation="Supervisor",
                availability="available", active_channel="telegram",
            )
            self.session.add(profile)
            self.session.flush()
            profile_id = profile.id

        recipient = Recipient(employee_id=profile_id, vendor_contact_id=None, phone="")
        self.assertEqual(self.service._resolve_recipient_channel(recipient), "telegram")

    def test_vendor_contact_recipient_resolves_to_whatsapp(self):
        with self.session.begin():
            vendor = V2Vendor(name="Acme Electric", contact_person="Acme Owner", phone="+911111111111")
            self.session.add(vendor)
            self.session.flush()
            contact = V2VendorContact(vendor_id=vendor.id, name="Jane Doe", phone="+911234567890")
            self.session.add(contact)
            self.session.flush()
            contact_id = contact.id

        recipient = Recipient(employee_id=None, vendor_contact_id=contact_id, phone="+911234567890")
        self.assertEqual(self.service._resolve_recipient_channel(recipient), "whatsapp")


if __name__ == "__main__":
    unittest.main()
