"""Telegram evidence for External Approval Gates (gate plan chunk 4).

Photos, documents and text notes sent on Telegram go into the employee's open
evidence session through the shared path WhatsApp attachments use (download,
type/size checks, evidence storage, `FileObject`, `append_attachment`), with
a readable reply for every outcome. [Cancel Evidence Session] discards the
session with the shared `discard_session`. The Admin's review message carries
up to five of the submitted files, uploaded from evidence storage after the
message itself, plus a Web App link.

Reuses test_telegram_callback.py's database harness (users, gate, linked
chats); Telegram and evidence storage are faked here.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.execution_models import (
    FileObject,
    GateEvidenceSession,
    GateEvidenceSessionAttachment,
    InboundMessage,
    MessageDelivery,
    OutboxEvent,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
    TelegramInboundUpdate,
)
from app.models import EmployeeProfile, User
from app.project_models import V2Project
from app.routes.telegram_webhook import _extract_media
from app.routes.telegram_webhook import router as telegram_webhook_router
from app.services.inbound_message import InboundMessageService
from app.services.message_dispatch import MessageDispatchService
from app.services.project_gate_submission import MAX_EVIDENCE_SIZE_BYTES
from app.services.telegram_evidence import TelegramEvidenceService
from app.services.telegram_gate_render import MAX_REVIEW_ATTACHMENTS
from app.services.telegram_inbound import TelegramInboundService
from app.services.telegram_provider import TelegramProviderAdapter
from tests import test_telegram_callback as callback_harness
from tests.test_telegram_callback import ADMIN_CHAT, ASSIGNEE_CHAT, OTHER_CHAT, OTHER_ID, UNLINKED_CHAT

JPEG = b"\xff\xd8\xff\xe0" + b"j" * 200
PDF = b"%PDF-1.7\n" + b"p" * 200


class _Response:
    def __init__(self, body: dict | None = None, content: bytes | None = None, status_code: int = 200):
        self._body = body
        self.status_code = status_code
        self.content = content if content is not None else b"{}"

    def json(self):
        return self._body or {}


class FakeTelegram:
    """Bot API stand-in: getFile/file download for inbound files, and a
    record of every call (sendMessage, sendPhoto, sendDocument...)."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict]] = []
        self.next_message_id = 100

    def post(self, url, json=None, data=None, files=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, {"json": json, "data": data, "files": files}))
        if method == "getFile":
            file_id = json["file_id"]
            if file_id not in self.files:
                return _Response({"ok": False, "description": "Bad Request: invalid file_id"}, status_code=400)
            return _Response({"ok": True, "result": {"file_id": file_id, "file_path": f"docs/{file_id}",
                                                      "file_size": len(self.files[file_id])}})
        self.next_message_id += 1
        return _Response({"ok": True, "result": {"message_id": self.next_message_id}})

    def get(self, url, timeout=None):
        self.calls.append(("download", {"url": url}))
        return _Response(content=self.files[url.rsplit("/", 1)[-1]])

    def of(self, method: str) -> list[dict]:
        return [kwargs for name, kwargs in self.calls if name == method]


class TelegramGateEvidenceTests(unittest.TestCase):
    # The callback tests' harness: same users, gate and linked chats.
    setUp_harness = callback_harness.TelegramCallbackTests.setUp
    tearDown_harness = callback_harness.TelegramCallbackTests.tearDown
    press = callback_harness.TelegramCallbackTests.press
    cb = callback_harness.TelegramCallbackTests.cb

    def setUp(self):
        self.setUp_harness()
        for table in (MessageDelivery.__table__,):
            table.create(self.engine)
        self._http_patch.stop()  # replaced by the richer fake below
        self.telegram = FakeTelegram()
        self.evidence_store: dict[str, bytes] = {}
        self._patches = [
            patch("app.services.telegram_provider.httpx.post", side_effect=self.telegram.post),
            patch("app.services.telegram_provider.httpx.get", side_effect=self.telegram.get),
            patch("app.services.evidence_storage.write",
                  side_effect=lambda key, data, content_type: self.evidence_store.__setitem__(key, data)),
            patch("app.services.evidence_storage.read", side_effect=self.evidence_store.get),
        ]
        for p in self._patches:
            p.start()
        self._http_patch.stop = lambda: None  # already stopped; tearDown_harness stops it again

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tearDown_harness()

    # ---- helpers ------------------------------------------------------------------

    def open_session(self) -> None:
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("op")))
        self.telegram.calls.clear()

    def send_media(self, chat_id: str, media: dict) -> None:
        """Simulates the webhook's media path for one update."""
        self.update_id += 1
        self.session.add(TelegramInboundUpdate(update_id=self.update_id, chat_id=chat_id, raw_payload={}))
        self.session.commit()
        TelegramEvidenceService(self.session).handle_media(update_id=self.update_id, chat_id=chat_id, media=media)

    def send_text(self, chat_id: str, text: str) -> None:
        self.update_id += 1
        TelegramEvidenceService(self.session).handle_text(update_id=self.update_id, chat_id=chat_id, text=text)

    def photo(self, file_id: str = "ph1", data: bytes = JPEG, caption: str | None = None, **extra) -> dict:
        self.telegram.files[file_id] = data
        return {"id": file_id, "kind": "photo", "mime_type": "image/jpeg", "filename": None,
                "file_size": len(data), "caption": caption, **extra}

    def document(self, file_id: str, filename: str | None, mime_type: str | None, data: bytes = PDF,
                 caption: str | None = None, file_size: int | None = -1) -> dict:
        self.telegram.files[file_id] = data
        return {"id": file_id, "kind": "document", "mime_type": mime_type, "filename": filename,
                "file_size": len(data) if file_size == -1 else file_size, "caption": caption}

    def open_session_row(self) -> GateEvidenceSession:
        return self.session.query(GateEvidenceSession).one()

    def session_files(self) -> list[FileObject]:
        return list(
            self.session.query(FileObject)
            .join(GateEvidenceSessionAttachment, GateEvidenceSessionAttachment.file_id == FileObject.id)
            .order_by(GateEvidenceSessionAttachment.created_at)
        )

    def replies(self) -> list[dict]:
        return [c["json"] for c in self.telegram.of("sendMessage")]

    def last_reply(self) -> dict:
        return self.replies()[-1]

    # ---- employee: photos, documents, notes -----------------------------------------

    def test_photo_is_stored_and_attached_to_the_open_session(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.photo())

        [file_object] = self.session_files()
        self.assertEqual((file_object.mime_type, file_object.original_filename), ("image/jpeg", "photo-1.jpg"))
        self.assertEqual(file_object.uploaded_by, self.approval.assigned_to_user_id)
        self.assertEqual(self.evidence_store[file_object.storage_key], JPEG)
        self.assertEqual(file_object.size_bytes, len(JPEG))
        self.assertEqual(self.telegram.of("getFile")[0]["json"], {"file_id": "ph1"})

        reply = self.last_reply()
        self.assertIn("<b>Evidence Added</b>", reply["text"])
        self.assertIn("Approval: Fire NOC", reply["text"])
        self.assertIn("Received: Photo", reply["text"])
        self.assertIn("You can add more evidence or submit everything for review.", reply["text"])
        self.assertEqual(
            reply["reply_markup"]["inline_keyboard"],
            [
                [{"text": "Add More Evidence", "callback_data": "g1:ad"},
                 {"text": "Submit for Review", "callback_data": "g1:cl"}],
                [{"text": "Cancel Evidence Session", "callback_data": "g1:cx"}],
            ],
        )
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "assigned")  # not submitted

    def test_pdf_document_keeps_its_filename_and_mime_type(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.document("doc1", "fire-noc-receipt.pdf", "application/pdf"))

        [file_object] = self.session_files()
        self.assertEqual((file_object.original_filename, file_object.mime_type), ("fire-noc-receipt.pdf", "application/pdf"))
        self.assertTrue(file_object.storage_key.endswith(".pdf"))
        self.assertIn("Received: fire-noc-receipt.pdf", self.last_reply()["text"])

    def test_image_sent_as_a_file_is_accepted_as_its_own_type(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.document("doc2", "site.png", "image/png", data=b"\x89PNG" + b"x" * 50))

        [file_object] = self.session_files()
        self.assertEqual((file_object.original_filename, file_object.mime_type), ("site.png", "image/png"))

    def test_caption_is_kept_in_the_session_note_with_its_file(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.document("doc1", "receipt.pdf", "application/pdf", caption="Fire dept receipt"))
        self.send_media(ASSIGNEE_CHAT, self.photo(caption="Front gate"))

        self.assertEqual(len(self.session_files()), 2)
        self.assertEqual(self.open_session_row().note, "receipt.pdf: Fire dept receipt\nphoto-2.jpg: Front gate")
        self.assertIn("Received: Photo (with caption)", self.last_reply()["text"])

    def test_text_note_in_an_open_session_is_confirmed(self):
        self.open_session()
        self.send_text(ASSIGNEE_CHAT, "Application number FN-2291")

        self.assertEqual(self.open_session_row().note, "Application number FN-2291")
        self.assertIn("Received: Text note", self.last_reply()["text"])

    def test_text_without_a_session_keeps_todays_silent_behaviour(self):
        self.send_text(ASSIGNEE_CHAT, "hello")
        self.assertEqual(self.replies(), [])

    def test_mixed_items_in_one_session_are_submitted_together(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.photo("p1"))
        self.send_media(ASSIGNEE_CHAT, self.document("d1", "permit.pdf", "application/pdf"))
        self.send_text(ASSIGNEE_CHAT, "Inspection done")
        self.send_media(ASSIGNEE_CHAT, self.photo("p2", data=JPEG + b"2"))

        self.assertEqual([f.original_filename for f in self.session_files()], ["photo-1.jpg", "permit.pdf", "photo-3.jpg"])
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("cl")))  # Submit for Review - existing close path

        approval = self.session.get(ProjectExternalApproval, self.approval.id)
        self.assertEqual(approval.status, "submitted")
        submission = self.session.query(ProjectExternalApprovalSubmission).one()
        self.assertEqual(submission.note, "Inspection done")
        evidence_types = sorted(e.evidence_type for e in self.session.query(ProjectExternalApprovalEvidence))
        self.assertEqual(evidence_types, ["document", "photo", "photo"])
        self.assertIsNotNone(self.open_session_row().closed_at)
        self.assertEqual(
            self.session.query(OutboxEvent).filter_by(event_type="project_external_approval.submitted").count(), 1,
        )

    def test_submitting_an_empty_session_still_fails(self):
        self.open_session()
        self.assertFalse(self.press(ASSIGNEE_CHAT, self.cb("cl")))

        self.assertIn("This evidence session is empty", self.last_reply()["text"])
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "assigned")
        self.assertEqual(self.session.query(ProjectExternalApprovalSubmission).count(), 0)

    # ---- employee: rejections -----------------------------------------------------------

    def assert_not_added(self, reply_contains: str) -> None:
        self.assertEqual(self.session.query(FileObject).count(), 0)
        self.assertEqual(self.evidence_store, {})
        self.assertIn(reply_contains, self.last_reply()["text"])

    def test_unsupported_type_is_rejected_without_downloading(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.document("v1", "clip.mp4", "video/mp4"))

        self.assert_not_added("<b>Couldn't add this evidence</b>")
        self.assertIn("This file type or size isn't supported", self.last_reply()["text"])
        self.assertEqual(self.telegram.of("getFile"), [])

    def test_iphone_heic_file_is_rejected_cleanly(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.document("h1", "IMG_0001.HEIC", "image/heic"))
        self.assert_not_added("This file type or size isn't supported")

    def test_oversized_file_is_rejected_before_download_when_telegram_reports_its_size(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.document(
            "big", "plans.pdf", "application/pdf", file_size=MAX_EVIDENCE_SIZE_BYTES + 1,
        ))

        self.assert_not_added("This file type or size isn't supported")
        self.assertEqual(self.telegram.of("getFile"), [])

    def test_oversized_download_without_a_reported_size_is_not_stored(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.document(
            "big2", "plans.pdf", "application/pdf", data=b"x" * (MAX_EVIDENCE_SIZE_BYTES + 1), file_size=None,
        ))
        self.assert_not_added("This file type or size isn't supported")

    def test_failed_download_asks_to_send_again(self):
        self.open_session()
        media = self.document("gone", "a.pdf", "application/pdf")
        del self.telegram.files["gone"]
        self.send_media(ASSIGNEE_CHAT, media)
        self.assert_not_added("couldn't be downloaded from Telegram")

    def test_media_with_no_open_session_is_not_attached_anywhere(self):
        self.send_media(ASSIGNEE_CHAT, self.photo())

        self.assert_not_added("<b>No evidence submission is currently open</b>")
        self.assertIn("Open the approval and tap Submit Evidence first.", self.last_reply()["text"])
        self.assertEqual(self.telegram.of("getFile"), [])

    def test_another_employees_media_never_lands_in_the_assignees_session(self):
        self.open_session()
        self.send_media(OTHER_CHAT, self.photo())

        self.assert_not_added("No evidence submission is currently open")
        self.assertEqual(self.session_files(), [])

    def test_media_after_the_gate_is_reassigned_away_is_rejected(self):
        self.open_session()
        self.session.get(ProjectExternalApproval, self.approval.id).assigned_to_user_id = OTHER_ID
        self.session.commit()
        self.send_media(ASSIGNEE_CHAT, self.photo())
        self.assert_not_added("no longer assigned to you")

    def test_media_from_an_unlinked_chat_explains_the_link(self):
        self.send_media(UNLINKED_CHAT, self.photo())
        self.assert_not_added("isn't linked to SiteOps")
        self.assertEqual(self.session.query(InboundMessage).one().processing_status, "unmatched")

    def test_caption_that_looks_like_a_command_is_only_a_caption(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.photo(caption="GATECLOSE"))

        self.assertEqual(len(self.session_files()), 1)
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "assigned")

    # ---- cancel ---------------------------------------------------------------------

    def test_cancel_discards_the_session_without_submitting(self):
        self.open_session()
        self.send_media(ASSIGNEE_CHAT, self.photo())

        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("cx")))

        row = self.open_session_row()
        self.assertIsNotNone(row.expired_at)  # existing discarded state
        self.assertIsNone(row.closed_at)
        self.assertEqual(self.session.query(GateEvidenceSessionAttachment).count(), 1)  # history kept
        self.assertEqual(self.session.query(ProjectExternalApprovalSubmission).count(), 0)
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "assigned")
        event = self.session.query(OutboxEvent).filter_by(event_type="gate_confirmation.session_cancelled").one()
        self.assertEqual(event.payload["approval_id"], str(self.approval.id))
        self.assertEqual(self.session.query(InboundMessage).filter_by(raw_body="GATECANCEL").one().processing_status,
                         "processed")

        # A new submission can be started afterwards.
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("op"), message_id=77))

    def test_cancel_with_no_open_session_is_explained(self):
        self.assertFalse(self.press(ASSIGNEE_CHAT, self.cb("cx")))
        self.assertIn("You have no open evidence session to cancel.", self.last_reply()["text"])

    def test_add_more_button_only_acknowledges(self):
        self.open_session()
        self.assertFalse(self.press(ASSIGNEE_CHAT, "g1:ad"))
        self.assertEqual(self.telegram.of("answerCallbackQuery")[0]["json"]["text"], "Send your next photo, PDF or note")
        self.assertIsNone(self.open_session_row().expired_at)

    def test_whatsapp_can_cancel_with_the_same_typed_command(self):
        self.open_session()
        user_phone = "+919000000001"
        self.session.get(User, self.approval.assigned_to_user_id).phone = user_phone
        self.session.commit()
        outcome = InboundMessageService(self.session).process("wamid.cancel", user_phone, "GATECANCEL")
        self.assertEqual(outcome.processing_status, "processed")
        self.assertIsNotNone(self.open_session_row().expired_at)

    # ---- duplicate webhook delivery ---------------------------------------------------

    def test_duplicate_webhook_delivery_adds_the_file_once(self):
        self.open_session()
        self.telegram.files["dup"] = JPEG
        update = {
            "update_id": 777001,
            "message": {"message_id": 5, "chat": {"id": int(ASSIGNEE_CHAT)}, "caption": "Gate photo",
                        "photo": [{"file_id": "small", "file_size": 10, "width": 90, "height": 90},
                                  {"file_id": "dup", "file_size": len(JPEG), "width": 1280, "height": 960}]},
        }
        app = FastAPI()
        app.include_router(telegram_webhook_router)
        app.dependency_overrides[get_db] = lambda: self.session
        original_secret, settings.telegram_webhook_secret = settings.telegram_webhook_secret, "hook-secret"
        try:
            client = TestClient(app)
            for _ in range(2):
                response = client.post("/api/v2/telegram/inbound", json=update,
                                       headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})
                self.assertEqual(response.status_code, 200)
        finally:
            settings.telegram_webhook_secret = original_secret

        self.assertEqual(len(self.session_files()), 1)
        self.assertEqual(len(self.telegram.of("getFile")), 1)
        self.assertEqual(self.telegram.of("getFile")[0]["json"], {"file_id": "dup"})  # the largest size
        self.assertEqual(self.open_session_row().note, "photo-1.jpg: Gate photo")
        self.assertEqual(len([r for r in self.replies() if "Evidence Added" in r["text"]]), 1)

    # ---- webhook parsing ----------------------------------------------------------------

    def test_extract_media_uses_the_largest_photo_and_maps_documents(self):
        photo = _extract_media({"caption": "c", "photo": [
            {"file_id": "a", "file_size": 100, "width": 90, "height": 90},
            {"file_id": "b", "file_size": 900, "width": 800, "height": 600},
            {"file_id": "c", "file_size": 400, "width": 320, "height": 240},
        ]})
        self.assertEqual((photo["id"], photo["kind"], photo["mime_type"], photo["caption"]), ("b", "photo", "image/jpeg", "c"))

        guessed = _extract_media({"document": {"file_id": "d", "file_name": "scan.pdf", "file_size": 5}})
        self.assertEqual((guessed["mime_type"], guessed["filename"]), ("application/pdf", "scan.pdf"))

        voice = _extract_media({"voice": {"file_id": "v", "mime_type": "audio/ogg"}})
        self.assertEqual((voice["kind"], voice["mime_type"]), ("document", "audio/ogg"))
        self.assertEqual(_extract_media({"sticker": {"file_id": "s"}})["mime_type"], "sticker/unknown")
        self.assertIsNone(_extract_media({"text": "hello"}))

    # ---- Admin review ----------------------------------------------------------------------

    def submit_with(self, *media: dict, note: str | None = None) -> None:
        self.open_session()
        for item in media:
            self.send_media(ASSIGNEE_CHAT, item)
        if note:
            self.send_text(ASSIGNEE_CHAT, note)
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("cl"), message_id=88))
        self.telegram.calls.clear()

    def dispatch_to_telegram_admin(self) -> None:
        for profile in self.session.query(EmployeeProfile):
            profile.active_channel = "telegram"
        self.session.commit()
        MessageDispatchService(self.session).process_pending()

    def admin_calls(self, method: str) -> list[dict]:
        return [
            c for c in self.telegram.of(method)
            if ((c["json"] or {}).get("chat_id") or (c["data"] or {}).get("chat_id")) == ADMIN_CHAT
        ]

    def test_admin_review_message_summarises_and_links_to_the_web_app(self):
        self.submit_with(self.photo("p1", caption="Front"), self.document("d1", "noc.pdf", "application/pdf"),
                         note="All pages attached")
        self.dispatch_to_telegram_admin()

        [review] = self.admin_calls("sendMessage")
        text = review["json"]["text"]
        self.assertIn("<b>External Approval Ready for Review</b>", text)
        self.assertIn("Submitted by: Rohan", text)
        self.assertIn("Evidence: 1 photo, 1 PDF, note", text)
        self.assertIn("Note: photo-1.jpg: Front All pages attached", text)
        self.assertIn("The submitted files follow below.", text)
        project_code = self.session.get(V2Project, self.project_id).code
        self.assertIn(
            f'<a href="{settings.frontend_url.rstrip("/")}/?tab=execution&amp;project={project_code}&amp;pane=approvals">'
            "Open in Web App</a>",
            text,
        )
        self.assertNotIn(str(self.approval.id), text)
        self.assertNotIn(self.approval.id.hex, text)
        self.assertEqual(
            [b["text"] for row in review["json"]["reply_markup"]["inline_keyboard"] for b in row], ["Approve", "Reject"],
        )

    def test_admin_receives_the_submitted_files_from_evidence_storage(self):
        self.submit_with(self.photo("p1"), self.document("d1", "noc.pdf", "application/pdf"))
        self.dispatch_to_telegram_admin()

        method_order = [name for name, kw in self.telegram.calls
                        if (kw.get("json") or kw.get("data") or {}).get("chat_id") == ADMIN_CHAT]
        # The message first, then the files (SQLite timestamps can't order the two files).
        self.assertEqual(method_order[0], "sendMessage")
        self.assertEqual(sorted(method_order[1:]), ["sendDocument", "sendPhoto"])
        [photo] = self.admin_calls("sendPhoto")
        self.assertEqual(photo["files"]["photo"], ("photo-1.jpg", JPEG, "image/jpeg"))
        self.assertRegex(photo["data"]["caption"], r"^Evidence [12] of 2: photo-1\.jpg$")
        [document] = self.admin_calls("sendDocument")
        self.assertEqual(document["files"]["document"], ("noc.pdf", PDF, "application/pdf"))
        # The employee's own "Submitted for Review" copy carries no files.
        employee_files = [kw for name, kw in self.telegram.calls
                          if name in ("sendPhoto", "sendDocument") and kw["data"]["chat_id"] == ASSIGNEE_CHAT]
        self.assertEqual(employee_files, [])

    def test_admin_gets_at_most_five_files_and_is_pointed_to_the_web_app(self):
        photos = [self.photo(f"p{i}", data=JPEG + bytes([i])) for i in range(MAX_REVIEW_ATTACHMENTS + 2)]
        self.submit_with(*photos)
        self.dispatch_to_telegram_admin()

        self.assertEqual(len(self.admin_calls("sendPhoto")), MAX_REVIEW_ATTACHMENTS)
        self.assertIn("The first 5 of 7 files follow below. See the Web App for all of them.",
                      self.admin_calls("sendMessage")[0]["json"]["text"])

    def test_files_are_never_resent_once_the_review_message_was_delivered(self):
        self.submit_with(self.photo("p1"))
        self.dispatch_to_telegram_admin()
        MessageDispatchService(self.session).process_pending()

        self.assertEqual(len(self.admin_calls("sendPhoto")), 1)

    def test_missing_stored_file_is_skipped_without_failing_the_delivery(self):
        self.submit_with(self.photo("p1"), self.document("d1", "noc.pdf", "application/pdf"))
        pdf_key = self.session.query(FileObject).filter_by(original_filename="noc.pdf").one().storage_key
        del self.evidence_store[pdf_key]
        self.dispatch_to_telegram_admin()

        self.assertEqual(len(self.admin_calls("sendPhoto")), 1)
        self.assertEqual(self.admin_calls("sendDocument"), [])
        admin_profile_id = self.session.query(EmployeeProfile.id).filter_by(telegram_chat_id=ADMIN_CHAT).scalar()
        review = (self.session.query(MessageDelivery)
                  .filter_by(recipient_employee_id=admin_profile_id).one())
        self.assertEqual(review.status, "sent")

    def test_admin_can_still_approve_from_the_review_message(self):
        self.submit_with(self.photo("p1"))
        self.update_id += 1
        self.assertTrue(self.press(ADMIN_CHAT, self.cb("ap"), message_id=99))
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "approved")


class TelegramFileDownloadTests(unittest.TestCase):
    def test_download_stops_before_fetching_when_get_file_reports_too_large(self):
        response = _Response({"ok": True, "result": {"file_path": "docs/x", "file_size": 50}})
        with patch("app.services.telegram_provider.httpx.post", return_value=response), \
                patch("app.services.telegram_provider.httpx.get") as get:
            result = TelegramProviderAdapter(access_token="t0k3n").download_file("x", max_bytes=10)
        self.assertEqual((result.ok, result.failure_code), (False, "too_large"))
        get.assert_not_called()

    def test_network_failure_reason_never_contains_the_bot_token(self):
        import httpx

        with patch("app.services.telegram_provider.httpx.post",
                   side_effect=httpx.ConnectError("failed https://api.telegram.org/botSECRET-TOKEN/getFile")):
            result = TelegramProviderAdapter(access_token="SECRET-TOKEN").download_file("x")
            sent = TelegramProviderAdapter(access_token="SECRET-TOKEN").send_photo("1", b"x", "a.jpg", "image/jpeg")
        self.assertNotIn("SECRET-TOKEN", result.failure_reason)
        self.assertNotIn("SECRET-TOKEN", sent.failure_reason)


if __name__ == "__main__":
    unittest.main()
