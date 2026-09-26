"""U10 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD4/KTD8): a recipient whose `active_channel` is 'telegram' actually
routes to the Telegram adapter; everyone else is unaffected.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.execution_models import MessageDelivery, OutboxEvent, ProjectExternalApproval
from app.models import EmployeeProfile, User, UserRole
from app.services.message_dispatch import MessageDispatchService, Recipient
from app.services.message_templates import DEFAULT_TEMPLATE


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None):
        self.status_code = status_code
        self._json_body = json_body
        self.content = b"x" if json_body is not None else b""

    def json(self):
        return self._json_body


TELEGRAM_EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee2")
WHATSAPP_EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee3")
NO_CHATID_EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee4")


class TelegramAdapterRoutingTests(unittest.TestCase):
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

        self._original_telegram_token = settings.telegram_access_token
        settings.telegram_access_token = "test-token"
        self.service = MessageDispatchService(self.session)

        with self.session.begin():
            self.session.add(User(id=TELEGRAM_EMPLOYEE_ID, name="Telegram Person", email="tg@example.com", role=UserRole.supervisor, active=True))
            self.session.add(User(id=WHATSAPP_EMPLOYEE_ID, name="WhatsApp Person", email="wa@example.com", role=UserRole.supervisor, active=True, phone="+911111111111"))
            self.session.add(User(id=NO_CHATID_EMPLOYEE_ID, name="No Chat Id Person", email="nc@example.com", role=UserRole.supervisor, active=True))
            self.session.flush()
            telegram_profile = EmployeeProfile(
                user_id=TELEGRAM_EMPLOYEE_ID, employee_code="EMP-TG", designation="Supervisor",
                availability="available", active_channel="telegram", telegram_chat_id="555999",
            )
            whatsapp_profile = EmployeeProfile(
                user_id=WHATSAPP_EMPLOYEE_ID, employee_code="EMP-WA", designation="Supervisor", availability="available",
            )
            no_chatid_profile = EmployeeProfile(
                user_id=NO_CHATID_EMPLOYEE_ID, employee_code="EMP-NC", designation="Supervisor",
                availability="available", active_channel="telegram",
            )
            self.session.add_all([telegram_profile, whatsapp_profile, no_chatid_profile])
            self.session.flush()
            # `Recipient.employee_id` holds `EmployeeProfile.id`, not
            # `User.id` - capture the profile's own id here, same as every
            # real resolver method in message_dispatch.py does.
            self.telegram_profile_id = telegram_profile.id
            self.whatsapp_profile_id = whatsapp_profile.id
            self.no_chatid_profile_id = no_chatid_profile.id
            self.event = OutboxEvent(
                event_type="project.activated", aggregate_type="project", aggregate_id=uuid.uuid4(),
                payload={"project_name": "Test Project"}, idempotency_key=str(uuid.uuid4()), status="pending",
            )
            self.session.add(self.event)

    def tearDown(self):
        self.session.close()
        settings.telegram_access_token = self._original_telegram_token

    @patch("app.services.telegram_provider.httpx.post")
    def test_telegram_recipient_routes_through_telegram_adapter(self, mock_post):
        mock_post.return_value = _FakeResponse(200, {"ok": True, "result": {"message_id": 1}})
        recipient = Recipient(employee_id=self.telegram_profile_id, vendor_contact_id=None, phone="", channel="telegram")

        self.service._dispatch_to_recipient(self.event, recipient, DEFAULT_TEMPLATE)

        mock_post.assert_called_once()
        sent_body = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["chat_id"], "555999")
        delivery = self.session.query(MessageDelivery).one()
        self.assertEqual(delivery.channel, "telegram")
        self.assertEqual(delivery.status, "sent")

    @patch("app.services.telegram_provider.httpx.post")
    def test_whatsapp_recipient_is_unaffected(self, mock_post):
        recipient = Recipient(employee_id=self.whatsapp_profile_id, vendor_contact_id=None, phone="+911111111111")

        self.service._dispatch_to_recipient(self.event, recipient, DEFAULT_TEMPLATE)

        mock_post.assert_not_called()  # Telegram's httpx.post - not touched
        delivery = self.session.query(MessageDelivery).one()
        self.assertEqual(delivery.channel, "whatsapp")
        self.assertEqual(delivery.status, "sent")

    def _gate_event(self, event_type: str, payload: dict | None = None) -> OutboxEvent:
        gate_event = OutboxEvent(
            event_type=event_type, aggregate_type="gate_command_confirmation", aggregate_id=uuid.uuid4(),
            payload=payload or {"gate_name": "Fire NOC", "project_name": "Test Project"},
            idempotency_key=str(uuid.uuid4()), status="pending",
        )
        self.session.add(gate_event)
        self.session.flush()
        return gate_event

    @patch("app.services.telegram_provider.httpx.post")
    def test_redundant_gate_confirmations_are_not_sent_on_telegram(self, mock_post):
        recipient = Recipient(employee_id=self.telegram_profile_id, vendor_contact_id=None, phone="", channel="telegram")
        for event_type in (
            "gate_confirmation.accepted", "gate_confirmation.declined", "gate_confirmation.status_recorded",
            "gate_confirmation.session_closed", "gate_confirmation.decided",
        ):
            with self.subTest(event_type=event_type):
                self.service._dispatch_to_recipient(self._gate_event(event_type), recipient, DEFAULT_TEMPLATE)

        mock_post.assert_not_called()
        self.assertEqual(self.session.query(MessageDelivery).count(), 0)

    @patch("app.services.telegram_provider.httpx.post")
    def test_session_opened_confirmation_is_still_sent_on_telegram(self, mock_post):
        mock_post.return_value = _FakeResponse(200, {"ok": True, "result": {"message_id": 7}})
        recipient = Recipient(employee_id=self.telegram_profile_id, vendor_contact_id=None, phone="", channel="telegram")

        self.service._dispatch_to_recipient(self._gate_event("gate_confirmation.session_opened"), recipient, DEFAULT_TEMPLATE)

        mock_post.assert_called_once()
        sent_body = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["parse_mode"], "HTML")
        self.assertIn("<b>Submit Evidence</b>", sent_body["text"])

    @patch("app.services.telegram_provider.httpx.post")
    def test_gate_confirmations_still_reach_whatsapp_recipients(self, mock_post):
        recipient = Recipient(employee_id=self.whatsapp_profile_id, vendor_contact_id=None, phone="+911111111111")

        self.service._dispatch_to_recipient(self._gate_event("gate_confirmation.status_recorded"), recipient, DEFAULT_TEMPLATE)

        mock_post.assert_not_called()
        delivery = self.session.query(MessageDelivery).one()
        self.assertEqual(delivery.channel, "whatsapp")
        self.assertEqual(delivery.status, "sent")

    @patch("app.services.telegram_provider.httpx.post")
    def test_actionable_gate_message_is_sent_with_inline_buttons(self, mock_post):
        mock_post.return_value = _FakeResponse(200, {"ok": True, "result": {"message_id": 9}})
        ProjectExternalApproval.__table__.create(self.engine)  # the renderer looks the gate up
        recipient = Recipient(employee_id=self.telegram_profile_id, vendor_contact_id=None, phone="", channel="telegram")
        approval_id = uuid.uuid4()
        gate_event = OutboxEvent(
            event_type="project_external_approval.assigned", aggregate_type="project_external_approval",
            aggregate_id=approval_id,
            payload={"approval_id": str(approval_id), "gate_name": "Fire NOC", "project_name": "Test Project",
                     "assigned_to_user_id": str(TELEGRAM_EMPLOYEE_ID)},
            idempotency_key=str(uuid.uuid4()), status="pending",
        )
        self.session.add(gate_event)
        self.session.flush()

        self.service._dispatch_to_recipient(gate_event, recipient, DEFAULT_TEMPLATE)

        sent_body = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["parse_mode"], "HTML")
        self.assertEqual(
            sent_body["reply_markup"]["inline_keyboard"][0][0],
            {"text": "Acknowledge", "callback_data": f"g1:ac:{approval_id.hex}"},
        )
        self.assertNotIn("Reply with", sent_body["text"])
        self.assertNotIn("GATEACCEPT", sent_body["text"])

    @patch("app.services.telegram_provider.httpx.post")
    def test_non_gate_telegram_message_is_sent_without_parse_mode(self, mock_post):
        mock_post.return_value = _FakeResponse(200, {"ok": True, "result": {"message_id": 8}})
        recipient = Recipient(employee_id=self.telegram_profile_id, vendor_contact_id=None, phone="", channel="telegram")

        self.service._dispatch_to_recipient(self.event, recipient, DEFAULT_TEMPLATE)

        self.assertNotIn("parse_mode", mock_post.call_args.kwargs["json"])
        self.assertNotIn("reply_markup", mock_post.call_args.kwargs["json"])

    @patch("app.services.telegram_provider.httpx.post")
    def test_telegram_recipient_with_no_chat_id_fails_clearly(self, mock_post):
        recipient = Recipient(employee_id=self.no_chatid_profile_id, vendor_contact_id=None, phone="", channel="telegram")

        self.service._dispatch_to_recipient(self.event, recipient, DEFAULT_TEMPLATE)

        mock_post.assert_not_called()
        delivery = self.session.query(MessageDelivery).one()
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.failure_code, "missing_chat_id")


if __name__ == "__main__":
    unittest.main()
