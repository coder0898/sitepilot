"""Phase 2 U9: inbound webhook parsing for `image`/`document` message types
and the top-level `errors[]` array (`app.routes.whatsapp_webhook_v2`).

The existing all-text-message webhook scenarios (signature gate,
verification handshake, identity matching, multi-message batching, etc.)
already live in `test_inbound_message_matching_v2.py` and are unchanged by
this unit - re-run there, not duplicated here.

This file covers only what U9 added:
    - `_extract_media_metadata` / `_extract_errors`, unit-tested directly
      (no DB, no HTTP) since they are pure parsing helpers.
    - An end-to-end image/document webhook delivery: parsed without ever
      calling `download_inbound_media` (parsing and downloading are
      separate concerns - see `whatsapp_media.py`).
    - An `errors[]`-only delivery: handled without raising and without
      reaching `InboundMessageService.process()`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import get_db
from app.execution_models import InboundMessage
from app.models import EmployeeProfile, User, UserRole
from app.routes.whatsapp_webhook_v2 import (
    _extract_errors,
    _extract_media_metadata,
    router as whatsapp_webhook_router,
)
from app.vendor_models import V2VendorContact

WEBHOOK_SECRET = "test-webhook-secret"
EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")
EMPLOYEE_PHONE = "+9000000099"


# ---- pure parsing helpers: no DB, no HTTP -----------------------------------


class ExtractMediaMetadataTests(unittest.TestCase):
    def test_text_message_has_no_media_metadata(self):
        self.assertIsNone(_extract_media_metadata({"type": "text", "text": {"body": "hi"}}))

    def test_image_message_extracts_id_and_mime_type(self):
        message = {"type": "image", "image": {"id": "media-1", "mime_type": "image/jpeg", "sha256": "abc"}}
        self.assertEqual(_extract_media_metadata(message), {"id": "media-1", "mime_type": "image/jpeg"})

    def test_document_message_also_extracts_filename(self):
        message = {
            "type": "document",
            "document": {"id": "media-2", "mime_type": "application/pdf", "filename": "report.pdf"},
        }
        self.assertEqual(
            _extract_media_metadata(message),
            {"id": "media-2", "mime_type": "application/pdf", "filename": "report.pdf"},
        )

    def test_image_message_has_no_filename_key(self):
        message = {"type": "image", "image": {"id": "media-1", "mime_type": "image/jpeg"}}
        self.assertNotIn("filename", _extract_media_metadata(message))

    def test_malformed_or_missing_media_object_does_not_raise(self):
        self.assertIsNone(_extract_media_metadata({"type": "image", "image": "not-a-dict"}))
        self.assertIsNone(_extract_media_metadata({"type": "image"}))
        self.assertIsNone(_extract_media_metadata({"type": "location", "location": {"latitude": 1}}))


class ExtractErrorsTests(unittest.TestCase):
    def test_no_errors_key_returns_empty_list(self):
        self.assertEqual(_extract_errors({}), [])

    def test_extracts_top_level_errors_array(self):
        payload = {"errors": [{"code": 131052, "title": "Unable to download media sent by the user"}]}
        self.assertEqual(_extract_errors(payload), [{"code": 131052, "title": "Unable to download media sent by the user"}])

    def test_non_dict_entries_and_non_list_shapes_are_tolerated(self):
        self.assertEqual(_extract_errors({"errors": ["not-a-dict", {"code": 1}]}), [{"code": 1}])
        self.assertEqual(_extract_errors({"errors": "not-a-list"}), [])


# ---- end-to-end webhook delivery: media parsing + top-level errors ----------


class WebhookMediaAndErrorsApiTests(unittest.TestCase):
    """Minimal harness: just enough schema for `InboundMessageService` to
    run its identity-matching queries (`users`/`employee_profiles`/
    `siteops_v2.vendor_contacts`) and write an `inbound_messages` row -
    same ATTACH-DATABASE-for-cross-schema-FKs pattern as
    `test_inbound_message_matching_v2.py`, trimmed to only what this file's
    scenarios touch."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (User.__table__, EmployeeProfile.__table__, V2VendorContact.__table__, InboundMessage.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed_employee()

        self._original_webhook_secret = settings.whatsapp_webhook_secret
        settings.whatsapp_webhook_secret = WEBHOOK_SECRET

        self.app = FastAPI()
        self.app.include_router(whatsapp_webhook_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

    def _seed_employee(self) -> None:
        """A single active employee whose phone matches this file's media
        webhook payloads, so those deliveries resolve to a matched
        identity (and thus "rejected" - unrecognized command - rather
        than "unmatched"), exercising the same downstream path a real
        image/document delivery from a known sender would take."""
        with self.Session.begin() as session:
            session.add(User(
                id=EMPLOYEE_ID, name="Field Employee", email="field@example.com",
                role=UserRole.supervisor, active=True, phone=EMPLOYEE_PHONE,
            ))
            session.flush()
            session.add(EmployeeProfile(
                user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Supervisor", availability="available",
            ))

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        settings.whatsapp_webhook_secret = self._original_webhook_secret

    def post_signed(self, envelope: dict):
        raw_body = json.dumps(envelope).encode("utf-8")
        digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/api/v2/whatsapp/inbound",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={digest}"},
        )

    def inbound_rows(self) -> list[InboundMessage]:
        with self.Session() as session:
            return list(session.scalars(select(InboundMessage)).all())

    @patch("app.services.whatsapp_media.download_inbound_media")
    def test_image_message_parsed_without_downloading_media(self, mock_download):
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba-1",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "phone-1"},
                        "messages": [{
                            "from": "9000000099",
                            "id": "wamid.image-1",
                            "timestamp": "1700000000",
                            "type": "image",
                            "image": {"id": "media-1", "mime_type": "image/jpeg"},
                        }],
                    },
                }],
            }],
        }

        response = self.post_signed(envelope)

        self.assertEqual(response.status_code, 200, response.text)
        mock_download.assert_not_called()

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].provider_message_id, "wamid.image-1")
        # Not yet threaded through to InboundMessageService (a later unit's
        # job, per the code comment at the call site) - same "Unrecognized
        # command" outcome the pre-U9 non-text path already produced.
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "Unrecognized command.")

    @patch("app.services.whatsapp_media.download_inbound_media")
    def test_document_message_parsed_without_downloading_media(self, mock_download):
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba-1",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "phone-1"},
                        "messages": [{
                            "from": "9000000099",
                            "id": "wamid.document-1",
                            "timestamp": "1700000000",
                            "type": "document",
                            "document": {
                                "id": "media-2", "mime_type": "application/pdf", "filename": "report.pdf",
                            },
                        }],
                    },
                }],
            }],
        }

        response = self.post_signed(envelope)

        self.assertEqual(response.status_code, 200, response.text)
        mock_download.assert_not_called()

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "rejected")

    @patch("app.routes.whatsapp_webhook_v2.InboundMessageService")
    def test_top_level_errors_array_is_handled_without_calling_inbound_service(self, mock_service_cls):
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [],
            "errors": [{"code": 131052, "title": "Unable to download media sent by the user"}],
        }

        response = self.post_signed(envelope)

        self.assertEqual(response.status_code, 200, response.text)
        mock_service_cls.assert_not_called()
        self.assertEqual(self.inbound_rows(), [])


if __name__ == "__main__":
    unittest.main()
