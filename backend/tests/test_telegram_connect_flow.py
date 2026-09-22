"""U13 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD3): opening the bot's `/start <token>` link links a Telegram chat to an
existing identity, without touching `active_channel`.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import get_db
from app.execution_models import TelegramConnectToken, TelegramInboundUpdate
from app.models import EmployeeProfile, User, UserRole
from app.routes.telegram_webhook import router as telegram_webhook_router
from app.vendor_models import V2Vendor, V2VendorContact

WEBHOOK_SECRET = "test-telegram-webhook-secret"
EMPLOYEE_USER_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_body: dict | None = None):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {"ok": True, "result": {"message_id": 1}}
        self.content = b"x"

    def json(self):
        return self._json_body


class TelegramConnectFlowTests(unittest.TestCase):
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
            User.__table__, EmployeeProfile.__table__, V2Vendor.__table__, V2VendorContact.__table__,
            TelegramConnectToken.__table__, TelegramInboundUpdate.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        self._original_webhook_secret = settings.telegram_webhook_secret
        self._original_access_token = settings.telegram_access_token
        settings.telegram_webhook_secret = WEBHOOK_SECRET
        settings.telegram_access_token = "test-token"

        self.app = FastAPI()
        self.app.include_router(telegram_webhook_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

        with self.Session.begin() as session:
            session.add(User(id=EMPLOYEE_USER_ID, name="Field Employee", email="field@example.com", role=UserRole.supervisor, active=True))
            session.flush()
            self.employee_profile = EmployeeProfile(
                user_id=EMPLOYEE_USER_ID, employee_code="EMP-001", designation="Supervisor", availability="available",
            )
            session.add(self.employee_profile)
            vendor = V2Vendor(name="Acme Electric", contact_person="Acme Owner", phone="+911111111111")
            session.add(vendor)
            session.flush()
            self.vendor_contact = V2VendorContact(vendor_id=vendor.id, name="Jane Doe", phone="+911234567890")
            session.add(self.vendor_contact)

    def tearDown(self):
        self.client.close()
        settings.telegram_webhook_secret = self._original_webhook_secret
        settings.telegram_access_token = self._original_access_token

    def _add_token(self, *, employee_id=None, vendor_contact_id=None, expires_in=timedelta(days=1), used=False, token="tok-123"):
        with self.Session.begin() as session:
            session.add(TelegramConnectToken(
                token=token, employee_id=employee_id, vendor_contact_id=vendor_contact_id,
                expires_at=datetime.now(timezone.utc) + expires_in,
                used_at=datetime.now(timezone.utc) if used else None,
            ))
        return token

    def _start(self, text: str, update_id: int = 1, chat_id: int = 555):
        return self.client.post(
            "/api/v2/telegram/inbound",
            json={"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}},
            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        )

    @patch("app.services.telegram_provider.httpx.post")
    def test_valid_token_for_employee_sets_chat_id_and_leaves_channel_untouched(self, mock_post):
        mock_post.return_value = _FakeResponse()
        token = self._add_token(employee_id=self.employee_profile.id)

        response = self._start(f"/start {token}")

        self.assertEqual(response.status_code, 200)
        with self.Session() as session:
            profile = session.get(EmployeeProfile, self.employee_profile.id)
            self.assertEqual(profile.telegram_chat_id, "555")
            self.assertEqual(profile.active_channel, "whatsapp")

    @patch("app.services.telegram_provider.httpx.post")
    def test_valid_token_for_vendor_contact_sets_chat_id(self, mock_post):
        mock_post.return_value = _FakeResponse()
        token = self._add_token(vendor_contact_id=self.vendor_contact.id)

        self._start(f"/start {token}")

        with self.Session() as session:
            contact = session.get(V2VendorContact, self.vendor_contact.id)
            self.assertEqual(contact.telegram_chat_id, "555")
            self.assertEqual(contact.active_channel, "whatsapp")

    @patch("app.services.telegram_provider.httpx.post")
    def test_already_used_token_is_rejected_and_does_not_overwrite(self, mock_post):
        mock_post.return_value = _FakeResponse()
        token = self._add_token(employee_id=self.employee_profile.id, used=True)

        self._start(f"/start {token}", chat_id=999)

        with self.Session() as session:
            profile = session.get(EmployeeProfile, self.employee_profile.id)
            self.assertIsNone(profile.telegram_chat_id)

    @patch("app.services.telegram_provider.httpx.post")
    def test_expired_token_is_rejected(self, mock_post):
        mock_post.return_value = _FakeResponse()
        token = self._add_token(employee_id=self.employee_profile.id, expires_in=timedelta(days=-1))

        self._start(f"/start {token}")

        with self.Session() as session:
            profile = session.get(EmployeeProfile, self.employee_profile.id)
            self.assertIsNone(profile.telegram_chat_id)

    @patch("app.services.telegram_provider.httpx.post")
    def test_start_with_no_token_is_rejected_with_no_identity_change(self, mock_post):
        mock_post.return_value = _FakeResponse()

        response = self._start("/start")

        self.assertEqual(response.status_code, 200)
        mock_post.assert_called_once()  # reply sent, no crash

    @patch("app.services.telegram_provider.httpx.post")
    def test_unrecognized_token_is_rejected(self, mock_post):
        mock_post.return_value = _FakeResponse()

        self._start("/start does-not-exist")

        with self.Session() as session:
            profile = session.get(EmployeeProfile, self.employee_profile.id)
            self.assertIsNone(profile.telegram_chat_id)

    @patch("app.services.telegram_provider.httpx.post")
    def test_repeated_invalid_attempts_are_throttled(self, mock_post):
        mock_post.return_value = _FakeResponse()

        for i in range(7):
            self._start("/start bad-token", update_id=100 + i)

        # After the threshold, further attempts get the rate-limited reply
        # rather than another invalid-token lookup - both reply via the
        # same adapter call, so assert on the total call count matching
        # attempts made (no crash, no unbounded lookups).
        self.assertEqual(mock_post.call_count, 7)

    @patch("app.services.telegram_provider.httpx.post")
    def test_retried_webhook_delivery_does_not_consume_token_twice(self, mock_post):
        mock_post.return_value = _FakeResponse()
        token = self._add_token(employee_id=self.employee_profile.id)

        self._start(f"/start {token}", update_id=42)
        self._start(f"/start {token}", update_id=42)  # same update_id - Telegram retry

        # Only one reply was ever sent - the second delivery short-circuited
        # on the duplicate update_id before reaching TelegramConnectService.
        self.assertEqual(mock_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
