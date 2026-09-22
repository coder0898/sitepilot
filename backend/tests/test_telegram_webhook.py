"""U2 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
inbound Telegram webhook receiver - raw receive only.

Minimal harness: just enough schema for `TelegramInboundUpdate` to exist,
same ATTACH-DATABASE-for-siteops_v2-schema pattern as
`test_whatsapp_webhook_v2.py`.
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import get_db
from app.execution_models import InboundMessage, TelegramConnectToken, TelegramInboundUpdate
from app.models import EmployeeProfile, User
from app.routes.telegram_webhook import router as telegram_webhook_router
from app.vendor_models import V2VendorContact


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


WEBHOOK_SECRET = "test-telegram-webhook-secret"


class TelegramWebhookApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        TelegramInboundUpdate.__table__.create(self.engine)
        # U13 wired /start handling into this route, which reads the
        # connect-token table when a message starts with "/start" (this
        # file's example text happens to be one) - create it here too, even
        # though this file's scenarios don't otherwise exercise U13.
        TelegramConnectToken.__table__.create(self.engine)
        # U14 wired command-parity dispatch into this route for any other
        # non-empty text - it reads/writes the shared inbound_messages
        # table (unmatched-identity outcome, since no identity is seeded
        # here) and queries User/EmployeeProfile/V2VendorContact for
        # identity matching, even though this file's scenarios don't
        # exercise U14 either.
        InboundMessage.__table__.create(self.engine)
        User.__table__.create(self.engine)
        EmployeeProfile.__table__.create(self.engine)
        V2VendorContact.__table__.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        self._original_secret = settings.telegram_webhook_secret
        settings.telegram_webhook_secret = WEBHOOK_SECRET

        self.app = FastAPI()
        self.app.include_router(telegram_webhook_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        settings.telegram_webhook_secret = self._original_secret

    def _rows(self) -> list[TelegramInboundUpdate]:
        with self.Session() as session:
            return list(session.execute(select(TelegramInboundUpdate)).scalars())

    def _post(self, body: dict, secret: str | None = WEBHOOK_SECRET):
        headers = {}
        if secret is not None:
            headers["X-Telegram-Bot-Api-Secret-Token"] = secret
        return self.client.post("/api/v2/telegram/inbound", json=body, headers=headers)

    def test_valid_secret_and_text_message_is_accepted_and_stored(self):
        response = self._post({
            "update_id": 1001,
            "message": {"chat": {"id": 555}, "text": "/start abc123"},
        })

        self.assertEqual(response.status_code, 200)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].update_id, 1001)
        self.assertEqual(rows[0].chat_id, "555")
        self.assertEqual(rows[0].message_text, "/start abc123")
        self.assertIsNone(rows[0].callback_data)

    def test_valid_secret_and_callback_query_is_accepted_and_stored(self):
        response = self._post({
            "update_id": 1002,
            "callback_query": {"message": {"chat": {"id": 555}}, "data": "accept"},
        })

        self.assertEqual(response.status_code, 200)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].chat_id, "555")
        self.assertEqual(rows[0].callback_data, "accept")
        self.assertIsNone(rows[0].message_text)

    def test_missing_secret_token_header_is_rejected(self):
        response = self._post({"update_id": 1003, "message": {"chat": {"id": 555}, "text": "hi"}}, secret=None)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self._rows(), [])

    def test_wrong_secret_token_is_rejected(self):
        response = self._post({"update_id": 1004, "message": {"chat": {"id": 555}, "text": "hi"}}, secret="wrong")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self._rows(), [])

    def test_malformed_update_body_is_rejected_without_server_error(self):
        response = self.client.post(
            "/api/v2/telegram/inbound",
            content=b"not json",
            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET, "Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._rows(), [])

    def test_unrecognized_update_shape_is_accepted_but_not_stored(self):
        # e.g. a poll answer or channel post - no `message`/`callback_query`.
        response = self._post({"update_id": 1005, "poll_answer": {"poll_id": "x"}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._rows(), [])

    def test_duplicate_update_id_is_not_stored_twice(self):
        body = {"update_id": 1006, "message": {"chat": {"id": 555}, "text": "hi"}}

        first = self._post(body)
        second = self._post(body)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self._rows()), 1)


if __name__ == "__main__":
    unittest.main()
