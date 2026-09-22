"""U9 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD4): `MessageDispatchService` picks the outbound adapter per recipient
via U8's lookup, instead of one adapter for the whole pass. Behavior is
unchanged today because every real recipient's channel still reads
'whatsapp' (no one has been toggled onto Telegram yet - U15).

This is the highest-risk unit in the plan - the WhatsApp path must behave
identically before and after. `test_message_delivery_dispatch_v2.py`
already exercises the full `process_pending` flow end to end and must
keep passing unmodified; this file adds direct coverage of the new
per-recipient adapter-selection and `MessageDelivery.channel` write.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import MessageDelivery, OutboxEvent
from app.models import EmployeeProfile, User, UserRole
from app.services.message_dispatch import MessageDispatchService, Recipient, SandboxProviderAdapter
from app.services.message_templates import DEFAULT_TEMPLATE


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")
EMPLOYEE_PHONE = "+9000000099"


class PerRecipientAdapterSelectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (User.__table__, EmployeeProfile.__table__, OutboxEvent.__table__, MessageDelivery.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()

        with self.session.begin():
            self.session.add(User(id=EMPLOYEE_ID, name="Field Employee", email="field@example.com", role=UserRole.supervisor, active=True, phone=EMPLOYEE_PHONE))
            self.session.flush()
            profile = EmployeeProfile(user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Supervisor", availability="available")
            self.session.add(profile)
            self.session.flush()
            # `Recipient.employee_id` holds `EmployeeProfile.id`, not
            # `User.id` - same convention every real resolver in
            # message_dispatch.py uses.
            self.profile_id = profile.id
            self.event = OutboxEvent(
                event_type="project.activated", aggregate_type="project", aggregate_id=uuid.uuid4(),
                payload={}, idempotency_key=str(uuid.uuid4()), status="pending",
            )
            self.session.add(self.event)

    def tearDown(self):
        self.session.close()

    def test_no_extra_configuration_needed_to_construct_the_service(self):
        # Constructing with no Telegram adapter configured must not error -
        # no recipient resolves to 'telegram' yet.
        MessageDispatchService(self.session)

    def test_whatsapp_recipient_dispatches_through_the_same_adapter_as_before(self):
        service = MessageDispatchService(self.session)
        recipient = Recipient(employee_id=self.profile_id, vendor_contact_id=None, phone=EMPLOYEE_PHONE)

        service._dispatch_to_recipient(self.event, recipient, DEFAULT_TEMPLATE)

        delivery = self.session.query(MessageDelivery).one()
        self.assertEqual(delivery.status, "sent")
        self.assertIsInstance(service._adapters["whatsapp"], SandboxProviderAdapter)

    def test_message_delivery_channel_is_recorded_as_whatsapp(self):
        service = MessageDispatchService(self.session)
        recipient = Recipient(employee_id=self.profile_id, vendor_contact_id=None, phone=EMPLOYEE_PHONE)

        service._dispatch_to_recipient(self.event, recipient, DEFAULT_TEMPLATE)

        delivery = self.session.query(MessageDelivery).one()
        self.assertEqual(delivery.channel, "whatsapp")


if __name__ == "__main__":
    unittest.main()
