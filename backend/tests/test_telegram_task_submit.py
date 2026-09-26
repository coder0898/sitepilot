"""Submit for Review from Telegram and the submission snapshot (Telegram task
plan U8).

[Submit for Review] runs the same lifecycle transition as the Web App. The
`submitted` event records who submitted and exactly which progress updates
the submission rests on (KTD18); the review message is built from that
snapshot. The race checks here are the snapshot-level half of KTD24 - the
row lock itself is proven against real Postgres in
test_task_progress_lock_postgres.py.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import select

from app.execution_models import FileObject, OutboxEvent, Task, TaskProgressUpdate, TelegramPendingInput
from app.models import User
from app.services.task_lifecycle import TaskLifecycleService
from app.services.task_progress import TaskProgressService
from app.services.task_verification import TaskVerificationService
from app.services.telegram_message import task_callback
from app.services.telegram_provider import MediaDownloadResult
from app.services.telegram_task_callback import TelegramTaskCallbackService
from tests.test_telegram_task_callback import EMPLOYEE_CHAT, OTHER_CHAT, TaskButtonHarness


class TelegramTaskSubmitTests(TaskButtonHarness):
    def setUp(self):
        super().setUp()
        self.stored: dict[str, bytes] = {}
        self._patches = [
            patch("app.services.evidence_storage.write", side_effect=lambda key, data, *_: self.stored.__setitem__(key, data)),
            patch("app.services.task_progress.compress_evidence_image", side_effect=lambda data, mime: (data, mime)),
            patch(
                "app.services.telegram_provider.TelegramProviderAdapter.download_file",
                return_value=MediaDownloadResult(ok=True, bytes=b"\xff\xd8\xff jpeg"),
            ),
        ]
        for p in self._patches:
            p.start()
        self.set_status(self.task, "in_progress")

    def tearDown(self):
        for p in self._patches:
            p.stop()
        super().tearDown()

    # ---- helpers ------------------------------------------------------------------------

    def log(self, note="Work done.", *, with_file=False, user=None) -> TaskProgressUpdate:
        user = user or self.session.get(User, self.employee[0].id)
        return TaskProgressService(self.session).submit_progress(
            self.project.id, self.task.id, user, note=note,
            evidence_bytes=b"\xff\xd8\xff jpeg" if with_file else None,
            evidence_filename="site.jpg" if with_file else None,
            evidence_content_type="image/jpeg" if with_file else None,
        )

    def submit(self, chat=EMPLOYEE_CHAT, message_id=60) -> bool:
        return self.press(chat, task_callback("sb", self.task.id), message_id=message_id)

    def submitted_event(self) -> dict:
        self.session.expire_all()
        rows = self.session.scalars(select(OutboxEvent).where(
            OutboxEvent.aggregate_id == self.task.id, OutboxEvent.event_type == "task.status_changed",
        )).all()
        [row] = [r for r in rows if r.payload.get("target_status") == "submitted"]
        return row.payload

    def progress_rows(self) -> list[TaskProgressUpdate]:
        self.session.expire_all()
        return list(self.session.scalars(select(TaskProgressUpdate).where(TaskProgressUpdate.task_id == self.task.id)))

    # ---- the button -------------------------------------------------------------------------

    def test_submit_moves_the_task_to_submitted_as_the_employee_from_telegram(self):
        update = self.log("East wall finished")
        self.assertTrue(self.submit())
        self.assertEqual(self.status(self.task), "submitted")
        self.assertEqual(self.calls("answerCallbackQuery")[-1]["text"], "Submitted for review")
        payload = self.submitted_event()
        self.assertEqual(payload["submitted_by"], str(self.employee[0].id))
        self.assertEqual(payload["progress_update_ids"], [str(update.id)])

    def test_submit_closes_add_progress_mode(self):
        self.log()
        self.press(EMPLOYEE_CHAT, task_callback("ap", self.task.id), message_id=61)
        self.assertIsNotNone(self.session.scalar(select(TelegramPendingInput)))
        self.submit()
        self.session.expire_all()
        self.assertIsNone(self.session.scalar(select(TelegramPendingInput)))

    def test_no_new_progress_is_explained_in_plain_words(self):
        self.assertFalse(self.submit())
        self.assertEqual(self.status(self.task), "in_progress")
        self.assertIn("Add new progress before submitting.", self.last_reply())

    def test_evidence_required_with_only_notes_asks_for_a_photo_or_pdf(self):
        with self.session.begin():
            self.session.get(Task, self.task.id).evidence_required = True
        self.log("Notes only")
        self.assertFalse(self.submit())
        self.assertIn("This task needs a photo or PDF.", self.last_reply())
        self.log("With a photo", with_file=True)
        self.assertTrue(self.submit(message_id=62))

    def test_someone_other_than_the_executor_is_refused(self):
        self.log()
        self.assertFalse(self.submit(chat=OTHER_CHAT))
        self.assertEqual(self.status(self.task), "in_progress")
        self.assertIn("only they can start or submit it", self.last_reply())

    def test_a_task_no_longer_in_progress_is_refused(self):
        self.log()
        self.session.commit()
        self.set_status(self.task, "ready")
        self.assertFalse(self.submit())
        self.assertIn("cannot move from ready to submitted", self.last_reply())

    def test_same_submit_button_twice_is_already_done(self):
        self.log()
        self.assertTrue(self.submit(message_id=70))
        self.assertFalse(self.submit(message_id=70))
        self.assertEqual(self.calls("answerCallbackQuery")[-1]["text"], "Already done")

    # ---- the snapshot (KTD18) -----------------------------------------------------------------

    def test_snapshot_holds_exactly_this_cycles_updates(self):
        employee = self.session.get(User, self.employee[0].id)
        first = self.log("Cycle 1")
        TaskLifecycleService(self.session).transition(self.project.id, self.task.id, "submitted", employee)
        TaskVerificationService(self.session).verify(
            self.project.id, self.task.id, "rejected", self.session.get(User, self.supervisor[0].id), remarks="Redo",
        )
        second = self.log("Cycle 2 a")
        third = self.log("Cycle 2 b", with_file=True)
        self.assertTrue(self.submit())

        events = [
            r.payload for r in self.session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == self.task.id))
            if r.payload.get("target_status") == "submitted"
        ]
        self.assertEqual(events[0]["progress_update_ids"], [str(first.id)])
        self.assertEqual(events[1]["progress_update_ids"], [str(second.id), str(third.id)])

    # ---- races (snapshot level; the lock itself: test_task_progress_lock_postgres) --------------

    def test_race_progress_first_belongs_to_the_submission(self):
        update = self.log("Committed just before submit")
        self.assertTrue(self.submit())
        self.assertIn(str(update.id), self.submitted_event()["progress_update_ids"])

    def test_race_submit_first_refuses_the_late_photo_and_leaves_nothing_behind(self):
        self.log("Real work")
        self.press(EMPLOYEE_CHAT, task_callback("ap", self.task.id), message_id=63)
        # The submit commits first (here from the Web App, so the Telegram
        # mode is still open when the photo arrives).
        TaskLifecycleService(self.session).transition(
            self.project.id, self.task.id, "submitted", self.session.get(User, self.employee[0].id),
        )
        snapshot = self.submitted_event()["progress_update_ids"]
        files_before = self.session.scalars(select(FileObject)).all()

        self.update_id += 1
        handled, acted = TelegramTaskCallbackService(self.session).handle_progress_media(
            update_id=self.update_id, chat_id=EMPLOYEE_CHAT, chat_type="private",
            media={"id": "late", "kind": "photo", "mime_type": "image/jpeg", "file_size": 100, "caption": "late"},
        )

        self.assertEqual((handled, acted), (True, False))
        self.assertIn("currently submitted", self.last_reply())
        self.assertEqual(len(self.progress_rows()), 1)
        self.assertEqual(self.session.scalars(select(FileObject)).all(), files_before)
        self.assertEqual(self.stored, {})
        self.assertEqual(self.submitted_event()["progress_update_ids"], snapshot)

    def test_race_invariant_the_decision_reviews_exactly_the_snapshot(self):
        self.log("A")
        self.log("B")
        self.assertTrue(self.submit())
        snapshot = set(self.submitted_event()["progress_update_ids"])
        TaskVerificationService(self.session).verify(
            self.project.id, self.task.id, "rejected", self.session.get(User, self.supervisor[0].id), remarks="Redo",
        )
        rows = self.progress_rows()
        self.assertEqual({str(r.id) for r in rows if r.reviewed_at is not None}, snapshot)
        self.assertEqual([r for r in rows if r.reviewed_at is None], [])


if __name__ == "__main__":
    unittest.main()
