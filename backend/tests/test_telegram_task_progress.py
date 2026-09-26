"""Add Progress from Telegram (Telegram task plan U7).

[Add Progress] opens a 10-minute mode for one task. While it is open every
note, photo or PDF from that chat becomes one normal progress update through
TaskProgressService (source "telegram"). A command closes the mode and runs as
a command; opening a gate evidence session closes it; so do Done and expiry.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select

from app.execution_models import FileObject, InboundMessage, Task, TaskEvidence, TaskProgressUpdate, TelegramPendingInput
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_message import gate_callback, task_callback
from app.services.telegram_provider import MediaDownloadResult
from app.services.telegram_task_callback import TelegramTaskCallbackService
from tests.test_telegram_task_callback import EMPLOYEE_CHAT, OTHER_CHAT, TaskButtonHarness

PDF_BYTES = b"%PDF-1.4 fake pdf"
JPEG_BYTES = b"\xff\xd8\xff fake jpeg"


class TelegramTaskProgressTests(TaskButtonHarness):
    def setUp(self):
        super().setUp()
        self.stored: dict[str, bytes] = {}
        self._patches = [
            patch("app.services.evidence_storage.write", side_effect=lambda key, data, *_: self.stored.__setitem__(key, data)),
            patch("app.services.task_progress.compress_evidence_image", side_effect=lambda data, mime: (data, mime)),
            patch(
                "app.services.telegram_provider.TelegramProviderAdapter.download_file",
                side_effect=lambda file_id, max_bytes=None: self.downloads.append(file_id) or MediaDownloadResult(
                    ok=True, bytes=PDF_BYTES if file_id.startswith("pdf") else JPEG_BYTES,
                ),
            ),
        ]
        self.downloads: list[str] = []
        for p in self._patches:
            p.start()
        self.set_status(self.task, "in_progress")

    def tearDown(self):
        for p in self._patches:
            p.stop()
        super().tearDown()

    # ---- helpers -----------------------------------------------------------------

    def open_mode(self, chat=EMPLOYEE_CHAT, **kwargs) -> None:
        self.press(chat, task_callback("ap", self.task.id), **kwargs)

    def text(self, body, chat=EMPLOYEE_CHAT, chat_type="private") -> tuple[bool, bool]:
        """The webhook's text path: Add Progress mode / questions first."""
        self.update_id += 1
        return TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=chat, text=body, chat_type=chat_type,
        )

    def media(self, *, kind="photo", mime="image/jpeg", file_id="photo-1", filename=None, size=1000, caption=None,
              chat=EMPLOYEE_CHAT, update_id=None) -> tuple[bool, bool]:
        if update_id is None:
            self.update_id += 1
            update_id = self.update_id
        return TelegramTaskCallbackService(self.session).handle_progress_media(
            update_id=update_id, chat_id=chat, chat_type="private",
            media={"id": file_id, "kind": kind, "mime_type": mime, "filename": filename, "file_size": size, "caption": caption},
        )

    def updates(self) -> list[TaskProgressUpdate]:
        self.session.expire_all()
        return list(self.session.scalars(
            select(TaskProgressUpdate).where(TaskProgressUpdate.task_id == self.task.id).order_by(TaskProgressUpdate.created_at)
        ))

    def mode(self) -> TelegramPendingInput | None:
        self.session.expire_all()
        return self.session.scalar(select(TelegramPendingInput).where(TelegramPendingInput.kind == "task_add_progress"))

    # ---- opening the mode -------------------------------------------------------------

    def test_add_progress_opens_the_mode_and_says_what_to_send(self):
        self.open_mode()
        mode = self.mode()
        self.assertEqual(mode.task_id, self.task.id)
        prompt = self.calls("sendMessage")[-1]
        self.assertIn("Add Progress: T001 - Task T001", prompt["text"])
        self.assertIn("Send a note, a photo or a PDF", prompt["text"])
        self.assertEqual([b["text"] for b in prompt["reply_markup"]["inline_keyboard"][0]], ["Submit for Review", "Done"])

    def test_task_not_in_progress_is_refused_before_anything_is_sent(self):
        self.set_status(self.task, "ready")
        self.open_mode()
        self.assertIsNone(self.mode())
        self.assertIn("only be logged while the task is in progress", self.last_reply())

    def test_someone_who_may_not_log_progress_is_refused(self):
        self.open_mode(chat=OTHER_CHAT)  # a member, but not the assignee
        self.assertIsNone(self.mode())
        self.assertIn("only they can log progress", self.last_reply())

    def test_group_chat_cannot_open_the_mode(self):
        self.open_mode(chat_type="group")
        self.assertIsNone(self.mode())
        self.assertIn("Use the bot in a private chat", self.last_reply())

    # ---- items ---------------------------------------------------------------------------

    def test_a_note_becomes_one_progress_update_from_telegram(self):
        self.open_mode()
        self.assertEqual(self.text("Framing done on the east wall"), (True, True))

        [update] = self.updates()
        self.assertEqual((update.note, update.update_type, update.source), ("Framing done on the east wall", "note", "telegram"))
        self.assertEqual(update.submitted_by, self.employee[0].id)
        reply = self.calls("sendMessage")[-1]["text"]
        self.assertIn("Progress Added", reply)
        self.assertIn('Received: Note: "Framing done on the east wall"', reply)

    def test_a_photo_with_caption_is_one_update_with_its_file(self):
        self.open_mode()
        self.assertEqual(self.media(caption="East wall after priming"), (True, True))

        [update] = self.updates()
        self.assertEqual((update.note, update.update_type, update.source), ("East wall after priming", "evidence", "telegram"))
        evidence = self.session.scalar(select(TaskEvidence).where(TaskEvidence.task_progress_update_id == update.id))
        file_object = self.session.get(FileObject, evidence.file_id)
        self.assertEqual(file_object.mime_type, "image/jpeg")
        self.assertEqual(list(self.stored.values()), [JPEG_BYTES])
        self.assertIn("Received: Photo (with caption)", self.calls("sendMessage")[-1]["text"])

    def test_pdf_and_png_are_accepted(self):
        self.open_mode()
        self.media(kind="document", mime="application/pdf", file_id="pdf-1", filename="test-report.pdf")
        self.media(kind="document", mime="image/png", file_id="png-1", filename="layout.png")
        self.assertEqual([u.update_type for u in self.updates()], ["evidence", "evidence"])
        self.assertIn("Received: test-report.pdf", self.calls("sendMessage")[-2]["text"])

    def test_unsupported_types_and_oversized_files_are_refused_before_download(self):
        self.open_mode()
        for kwargs in (
            {"kind": "document", "mime": "image/heic", "file_id": "heic-1", "filename": "IMG.HEIC"},
            {"kind": "document", "mime": "video/mp4", "file_id": "video-1"},
            {"kind": "document", "mime": "application/pdf", "file_id": "pdf-big", "size": 11 * 1024 * 1024},
        ):
            with self.subTest(**kwargs):
                self.assertEqual(self.media(**kwargs), (True, False))
                self.assertIn("isn't supported", self.last_reply())
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.updates(), [])

    def test_several_items_slide_the_timeout_from_the_last_one(self):
        self.open_mode()
        for note in ("One", "Two", "Three"):
            with self.session.begin():
                self.session.scalar(select(TelegramPendingInput)).expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
            self.text(note)
        self.assertEqual([u.note for u in self.updates()], ["One", "Two", "Three"])
        remaining = self.mode().expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        self.assertGreater(remaining, timedelta(minutes=9))

    def test_an_item_after_the_mode_expired_is_not_stored_and_no_notice_is_sent(self):
        self.open_mode()
        with self.session.begin():
            self.session.scalar(select(TelegramPendingInput)).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        sent_before = len(self.calls("sendMessage"))

        self.assertEqual(self.text("Late note"), (False, False))  # goes on to normal processing
        self.assertEqual(self.media(), (False, False))  # goes on to the gate evidence path

        self.assertEqual(self.updates(), [])
        self.assertIsNone(self.mode())
        self.assertEqual(len(self.calls("sendMessage")), sent_before)

    def test_the_same_telegram_update_is_never_stored_twice(self):
        self.open_mode()
        self.update_id += 1
        self.media(update_id=self.update_id)
        self.media(update_id=self.update_id)
        self.assertEqual(len(self.updates()), 1)

    # ---- closing the mode -------------------------------------------------------------------

    def test_a_typed_command_closes_the_mode_and_runs_as_a_command(self):
        self.open_mode()
        for command in ("STATUS T001 submitted", "gateopen abc12345"):
            with self.subTest(command=command):
                self.open_mode()
                self.assertEqual(self.text(command), (False, False))  # handed on to command processing
                self.assertIsNone(self.mode())
        self.assertEqual(self.updates(), [])

    def test_opening_a_gate_evidence_session_closes_the_mode(self):
        self.open_mode()
        self.update_id += 1
        TelegramCallbackService(self.session).handle(
            update_id=self.update_id, chat_id=EMPLOYEE_CHAT, message_id=99, callback_query_id="cbq",
            data=gate_callback("op", "0" * 32),
        )
        self.assertIsNone(self.mode())
        # The next photo is not task progress.
        self.assertEqual(self.media(), (False, False))
        self.assertEqual(self.updates(), [])

    def test_done_closes_the_mode(self):
        self.open_mode()
        self.press(EMPLOYEE_CHAT, task_callback("dn", self.task.id), message_id=55)
        self.assertIsNone(self.mode())
        self.assertIn("Add Progress closed", self.last_reply())
        self.assertEqual(self.text("After done"), (False, False))

    def test_a_task_that_left_in_progress_closes_the_mode_with_a_readable_refusal(self):
        self.open_mode()
        self.set_status(self.task, "submitted")
        self.assertEqual(self.text("Too late"), (True, False))
        self.assertIsNone(self.mode())
        self.assertIn("currently submitted", self.last_reply())
        self.assertEqual(self.updates(), [])
        self.assertEqual(
            self.session.scalar(select(InboundMessage).where(InboundMessage.provider_message_id == str(self.update_id))).processing_status,
            "rejected",
        )


if __name__ == "__main__":
    unittest.main()
