"""Telegram self-link / unlink (2026-09-29): an Admin generates a one-time
`t.me/<bot>?start=<token>` link, the person taps Start in a private chat,
and exactly one Telegram chat is linked to exactly one SiteOps identity.

Covers the one-to-one rule, the sequential test flow (link Rohan -> unlink
-> link the same chat to Deepak), that a relinked chat never receives the
previous person's queued messages, and offboarding.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.config import settings
from app.database import get_db
from app.execution_models import (
    MessageDelivery, OutboxEvent, TelegramConnectToken, TelegramInboundUpdate, TelegramPendingInput,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent
from app.routes.telegram_connect_codes import router as connect_router
from app.routes.telegram_webhook import router as webhook_router
from app.services import telegram_provider
from app.services.message_dispatch import MessageDispatchService
from app.services.telegram_connect import hash_token
from app.services.telegram_inbound import TelegramInboundService
from app.vendor_models import V2Vendor, V2VendorContact

WEBHOOK_SECRET = "test-telegram-webhook-secret"
ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
ROHAN_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
DEEPAK_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
PM_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
MY_CHAT = 777001


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class _FakeResponse:
    def __init__(self, json_body: dict | None = None):
        self.status_code = 200
        self._json_body = json_body if json_body is not None else {"ok": True, "result": {"message_id": 1}}
        self.content = b"x"

    def json(self):
        return self._json_body


def _telegram_ok(url, json=None, **_kw):
    if url.endswith("/getMe"):
        return _FakeResponse({"ok": True, "result": {"username": "SiteOpsBot"}})
    return _FakeResponse()


class TelegramSelfLinkTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Vendor.__table__, V2VendorContact.__table__,
            TelegramConnectToken.__table__, TelegramInboundUpdate.__table__, TelegramPendingInput.__table__,
            V2AuditEvent.__table__, OutboxEvent.__table__, MessageDelivery.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        self._saved = (settings.telegram_webhook_secret, settings.telegram_access_token, settings.outbox_dispatch_enabled)
        settings.telegram_webhook_secret = WEBHOOK_SECRET
        settings.telegram_access_token = "test-token"
        settings.outbox_dispatch_enabled = False
        telegram_provider._BOT_USERNAMES.clear()

        self.actor = None
        app = FastAPI()
        app.include_router(webhook_router)
        app.include_router(connect_router)

        def override_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[current_user] = lambda: self.actor
        self.client = TestClient(app)

        with self.Session.begin() as session:
            self.admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            session.add_all([
                self.admin,
                User(id=ROHAN_ID, name="Rohan", email="rohan@example.com", role=UserRole.supervisor, active=True),
                User(id=DEEPAK_ID, name="Deepak", email="deepak@example.com", role=UserRole.internal_employee, active=True),
                User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True),
            ])
            session.flush()
            profiles = {
                key: EmployeeProfile(
                    user_id=user_id, employee_code=code, designation=key, availability="available",
                    active_channel="telegram",
                )
                for key, user_id, code in (("rohan", ROHAN_ID, "E-1"), ("deepak", DEEPAK_ID, "E-2"), ("pm", PM_ID, "E-3"))
            }
            session.add_all(profiles.values())
            session.flush()
            self.profile_ids = {key: profile.id for key, profile in profiles.items()}
        self.actor = self.admin
        self._update_id = 0

    def tearDown(self):
        self.client.close()
        settings.telegram_webhook_secret, settings.telegram_access_token, settings.outbox_dispatch_enabled = self._saved
        telegram_provider._BOT_USERNAMES.clear()

    # ---- helpers ------------------------------------------------------

    def generate(self, who: str):
        return self.client.post("/api/v2/telegram/connect-code", json={"employee_id": str(self.profile_ids[who])})

    def unlink(self, who: str):
        return self.client.post("/api/v2/telegram/unlink", json={"employee_id": str(self.profile_ids[who])})

    def start(self, text: str, chat_id: int = MY_CHAT, chat_type: str = "private"):
        self._update_id += 1
        return self.client.post(
            "/api/v2/telegram/inbound",
            json={"update_id": self._update_id, "message": {"chat": {"id": chat_id, "type": chat_type}, "text": text}},
            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        )

    def chat_of(self, who: str) -> str | None:
        with self.Session() as session:
            return session.get(EmployeeProfile, self.profile_ids[who]).telegram_chat_id

    @staticmethod
    def replies(mock_post) -> list[str]:
        return [c.kwargs["json"]["text"] for c in mock_post.call_args_list if c.kwargs.get("json", {}).get("text")]

    def link(self, who: str, mock_post, chat_id: int = MY_CHAT) -> None:
        code = self.generate(who).json()["code"]
        self.start(f"/start {code}", chat_id=chat_id)
        self.assertEqual(self.chat_of(who), str(chat_id))

    # ---- generate -----------------------------------------------------

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_generate_returns_bot_link_and_stores_only_a_hash(self, _mock_post):
        response = self.generate("rohan")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["link"], f"https://t.me/SiteOpsBot?start={body['code']}")
        self.assertGreaterEqual(len(body["code"]), 32)
        self.assertNotIn(str(self.profile_ids["rohan"]), body["link"])
        self.assertNotIn("rohan", body["link"].lower())
        with self.Session() as session:
            stored = session.scalar(select(TelegramConnectToken))
        self.assertEqual(stored.token, hash_token(body["code"]))
        self.assertNotEqual(stored.token, body["code"])

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_only_admin_roles_can_generate_or_unlink(self, _mock_post):
        with self.Session() as session:
            self.actor = session.get(User, PM_ID)
        self.assertEqual(self.generate("rohan").status_code, 403)
        self.assertEqual(self.unlink("rohan").status_code, 403)

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_generate_is_refused_while_already_linked(self, mock_post):
        self.link("rohan", mock_post)
        response = self.generate("rohan")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Unlink it first", response.json()["detail"])

    # ---- /start -------------------------------------------------------

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_start_links_audits_and_redacts_the_stored_token(self, mock_post):
        code = self.generate("rohan").json()["code"]
        self.start(f"/start {code}")
        self.assertEqual(self.chat_of("rohan"), str(MY_CHAT))
        self.assertIn("You're connected", self.replies(mock_post)[-1])
        with self.Session() as session:
            audit = session.scalar(select(V2AuditEvent).where(V2AuditEvent.action == "telegram_linked"))
            self.assertEqual(audit.entity_id, self.profile_ids["rohan"])
            self.assertEqual(audit.actor_user_id, ROHAN_ID)
            stored = session.scalar(select(TelegramInboundUpdate))
            self.assertEqual(stored.message_text, "/start [redacted]")
            self.assertNotIn(code, str(stored.raw_payload))

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_expired_token_is_refused(self, mock_post):
        code = self.generate("rohan").json()["code"]
        with self.Session.begin() as session:
            session.scalar(select(TelegramConnectToken)).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.start(f"/start {code}")
        self.assertIsNone(self.chat_of("rohan"))
        self.assertIn("isn't valid or has expired", self.replies(mock_post)[-1])

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_used_token_cannot_be_reused(self, mock_post):
        code = self.generate("rohan").json()["code"]
        self.start(f"/start {code}")
        self.unlink("rohan")
        self.start(f"/start {code}")
        self.assertIsNone(self.chat_of("rohan"))
        self.assertIn("isn't valid or has expired", self.replies(mock_post)[-1])

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_group_chat_is_refused_and_token_stays_usable_in_private(self, mock_post):
        code = self.generate("rohan").json()["code"]
        self.start(f"/start {code}", chat_id=-100555, chat_type="group")
        self.assertIsNone(self.chat_of("rohan"))
        self.assertIn("private chat", self.replies(mock_post)[-1])
        self.start(f"/start {code}")
        self.assertEqual(self.chat_of("rohan"), str(MY_CHAT))

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_chat_already_linked_to_another_user_is_refused(self, mock_post):
        self.link("rohan", mock_post)
        code = self.generate("deepak").json()["code"]
        self.start(f"/start {code}")
        self.assertIsNone(self.chat_of("deepak"))
        self.assertEqual(self.chat_of("rohan"), str(MY_CHAT))
        self.assertEqual(self.replies(mock_post)[-1], "This Telegram account is already linked. Unlink it first.")

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_user_already_linked_to_another_chat_is_refused(self, mock_post):
        code = self.generate("rohan").json()["code"]
        # Rohan becomes linked elsewhere after the link was generated.
        with self.Session.begin() as session:
            session.get(EmployeeProfile, self.profile_ids["rohan"]).telegram_chat_id = "999999"
        self.start(f"/start {code}")
        self.assertEqual(self.chat_of("rohan"), "999999")
        self.assertIn("already linked to another Telegram account", self.replies(mock_post)[-1])

    # ---- unlink and relink --------------------------------------------

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_admin_unlink_frees_the_chat_and_clears_its_open_question(self, mock_post):
        self.link("rohan", mock_post)
        with self.Session.begin() as session:
            session.add(TelegramPendingInput(
                chat_id=str(MY_CHAT), kind="task_add_progress", task_id=uuid.uuid4(),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            ))
        response = self.unlink("rohan")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["telegram_connected"])
        self.assertIsNone(self.chat_of("rohan"))
        with self.Session() as session:
            self.assertIsNone(session.scalar(select(TelegramPendingInput)))

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_same_telegram_can_link_rohan_then_deepak_then_pm_in_turn(self, mock_post):
        for who in ("rohan", "deepak", "pm"):
            self.link(who, mock_post)
            self.assertEqual(self.unlink(who).status_code, 200)
            self.assertIsNone(self.chat_of(who))
        with self.Session() as session:
            actions = [a.action for a in session.scalars(select(V2AuditEvent))]
        self.assertEqual(actions.count("telegram_linked"), 3)
        self.assertEqual(actions.count("telegram_unlinked"), 3)

    # ---- queued messages never cross identities ------------------------

    def _user_event(self, user_id: uuid.UUID, name: str) -> uuid.UUID:
        with self.Session.begin() as session:
            outbox = OutboxEvent(
                event_type="user.created", aggregate_type="user", aggregate_id=user_id,
                payload={"user_id": str(user_id), "name": name}, idempotency_key=str(uuid.uuid4()), status="pending",
            )
            session.add(outbox)
            session.flush()
            return outbox.id

    def _dispatch(self) -> None:
        with self.Session() as session:
            MessageDispatchService(session).process_pending()
            session.commit()

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_rohans_parked_message_never_reaches_deepak_after_relink(self, mock_post):
        self.link("rohan", mock_post)
        self.unlink("rohan")
        rohan_event = self._user_event(ROHAN_ID, "Rohan")
        self._dispatch()  # Rohan has no chat now: parked as missing_chat_id
        with self.Session() as session:
            parked = session.scalar(select(MessageDelivery).where(MessageDelivery.outbox_event_id == rohan_event))
            self.assertEqual((parked.status, parked.failure_code), ("failed", "missing_chat_id"))

        self.link("deepak", mock_post)
        deepak_event = self._user_event(DEEPAK_ID, "Deepak")
        mock_post.reset_mock()
        self._dispatch()

        sent_to_chat = [
            c.kwargs["json"] for c in mock_post.call_args_list
            if c.args[0].endswith("/sendMessage") and c.kwargs["json"]["chat_id"] == str(MY_CHAT)
        ]
        self.assertEqual(len(sent_to_chat), 1)  # only Deepak's own message
        with self.Session() as session:
            rohan_delivery = session.scalar(select(MessageDelivery).where(MessageDelivery.outbox_event_id == rohan_event))
            deepak_delivery = session.scalar(select(MessageDelivery).where(MessageDelivery.outbox_event_id == deepak_event))
        # History keeps each delivery's original recipient.
        self.assertEqual(rohan_delivery.recipient_employee_id, self.profile_ids["rohan"])
        self.assertEqual((rohan_delivery.status, rohan_delivery.failure_code), ("failed", "missing_chat_id"))
        self.assertEqual(deepak_delivery.recipient_employee_id, self.profile_ids["deepak"])
        self.assertEqual(deepak_delivery.status, "sent")

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_messages_stop_the_moment_rohan_is_unlinked(self, mock_post):
        self.link("rohan", mock_post)
        self.unlink("rohan")
        self._user_event(ROHAN_ID, "Rohan")
        mock_post.reset_mock()
        self._dispatch()
        self.assertFalse([c for c in mock_post.call_args_list if c.args[0].endswith("/sendMessage")])

    # ---- offboarding --------------------------------------------------

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_offboarded_user_gets_no_messages_cannot_act_and_cannot_link(self, mock_post):
        self.link("rohan", mock_post)
        with self.Session.begin() as session:
            session.get(User, ROHAN_ID).active = False
        event_id = self._user_event(ROHAN_ID, "Rohan")
        mock_post.reset_mock()
        self._dispatch()
        self.assertFalse([c for c in mock_post.call_args_list if c.args[0].endswith("/sendMessage")])
        with self.Session() as session:
            delivery = session.scalar(select(MessageDelivery).where(MessageDelivery.outbox_event_id == event_id))
            self.assertEqual(delivery.failure_code, "recipient_offboarded")
            # Not re-selected on later passes.
            self.assertEqual(MessageDispatchService(session)._select_events(50), [])
            # Telegram commands/buttons resolve no identity for this chat.
            self.assertEqual(TelegramInboundService(session)._match_employees_by_chat_id(str(MY_CHAT)), [])

        # An offboarded person's link can't be completed either.
        self.unlink("rohan")
        code = self.generate("rohan").json()["code"]
        self.start(f"/start {code}")
        self.assertIsNone(self.chat_of("rohan"))

    @patch("app.services.telegram_provider.httpx.post", side_effect=_telegram_ok)
    def test_offboarding_notice_itself_is_still_sent(self, mock_post):
        self.link("rohan", mock_post)
        with self.Session.begin() as session:
            session.get(User, ROHAN_ID).active = False
            session.add(OutboxEvent(
                event_type="user.offboarded", aggregate_type="user", aggregate_id=ROHAN_ID,
                payload={"user_id": str(ROHAN_ID), "name": "Rohan"}, idempotency_key=str(uuid.uuid4()), status="pending",
            ))
        mock_post.reset_mock()
        self._dispatch()
        self.assertEqual(len([c for c in mock_post.call_args_list if c.args[0].endswith("/sendMessage")]), 1)


if __name__ == "__main__":
    unittest.main()
