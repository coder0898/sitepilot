"""Supervisor Verify / Reject from Telegram (Telegram task plan U9).

The buttons call TaskVerificationService.verify - the same call as the Web
App, source "telegram" - and carry their submission's token (KTD19), so a
button, or a reason question, from an earlier submission is refused.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.execution_models import TaskProgressUpdate, TaskVerification, TelegramPendingInput
from app.models import User
from app.project_models import V2AuditEvent
from app.services.task_lifecycle import TaskLifecycleService
from app.services.task_progress import TaskProgressService
from app.services.task_verification import TaskVerificationService
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_message import submission_token, task_callback
from tests.test_telegram_task_callback import EMPLOYEE_CHAT, PM_CHAT, SUPERVISOR_CHAT, TaskButtonHarness


class TelegramTaskReviewTests(TaskButtonHarness):
    def setUp(self):
        super().setUp()
        self.set_status(self.task, "in_progress")

    # ---- helpers --------------------------------------------------------------------

    def user(self, person) -> User:
        return self.session.get(User, person[0].id)

    def submit_cycle(self, note="Work done.", by=None) -> str:
        """Logs one update and submits; returns the submission's token."""
        by = by or self.employee
        update = TaskProgressService(self.session).submit_progress(self.project.id, self.task.id, self.user(by), note=note)
        TaskLifecycleService(self.session).transition(self.project.id, self.task.id, "submitted", self.user(by))
        return submission_token([update.id])

    def reject_in_web_app(self, remarks="Redo") -> None:
        TaskVerificationService(self.session).verify(
            self.project.id, self.task.id, "rejected", self.user(self.supervisor), remarks=remarks,
        )

    def reply(self, chat, text) -> tuple[bool, bool]:
        self.update_id += 1
        return TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=chat, text=text, chat_type="private",
        )

    def verifications(self) -> list[TaskVerification]:
        self.session.expire_all()
        return list(self.session.scalars(select(TaskVerification).where(TaskVerification.task_id == self.task.id)))

    # ---- verify ------------------------------------------------------------------------

    def test_supervisor_verifies_standard_work_and_it_completes_as_telegram(self):
        token = self.submit_cycle()
        self.assertTrue(self.press(SUPERVISOR_CHAT, task_callback("vf", self.task.id, token)))

        self.assertEqual(self.status(self.task), "completed")
        [verification] = self.verifications()
        self.assertEqual((verification.decision, verification.verified_by), ("verified", self.supervisor[0].id))
        sources = {a.source for a in self.session.scalars(
            select(V2AuditEvent).where(V2AuditEvent.entity_id == self.task.id, V2AuditEvent.actor_user_id == self.supervisor[0].id)
        )}
        self.assertEqual(sources, {"telegram"})
        self.assertEqual(self.calls("answerCallbackQuery")[-1]["text"], "Verified")
        self.assertEqual(len(self.calls("editMessageReplyMarkup")), 1)

    def test_same_verify_button_twice_is_already_done(self):
        token = self.submit_cycle()
        self.assertTrue(self.press(SUPERVISOR_CHAT, task_callback("vf", self.task.id, token), message_id=81))
        self.assertFalse(self.press(SUPERVISOR_CHAT, task_callback("vf", self.task.id, token), message_id=81))
        self.assertEqual(self.calls("answerCallbackQuery")[-1]["text"], "Already done")
        self.assertEqual(len(self.verifications()), 1)

    # ---- reject --------------------------------------------------------------------------

    def test_reject_asks_for_a_reason_then_records_it_and_reopens_the_task(self):
        token = self.submit_cycle()
        self.assertFalse(self.press(SUPERVISOR_CHAT, task_callback("vr", self.task.id, token)))
        question = self.calls("sendMessage")[-1]
        self.assertIn("Please enter the reason for rejecting this work.", question["text"])
        self.assertEqual(question["reply_markup"]["inline_keyboard"][0][0]["callback_data"], f"t1:vc:{self.task.id.hex}:{token}")
        self.assertEqual(self.status(self.task), "submitted")

        self.assertEqual(self.reply(SUPERVISOR_CHAT, "Gaps at the door frame"), (True, True))

        self.assertEqual(self.status(self.task), "in_progress")
        [verification] = self.verifications()
        self.assertEqual((verification.decision, verification.remarks), ("rejected", "Gaps at the door frame"))

    def test_cancel_on_the_reason_question_records_nothing(self):
        token = self.submit_cycle()
        self.press(SUPERVISOR_CHAT, task_callback("vr", self.task.id, token))
        self.press(SUPERVISOR_CHAT, task_callback("vc", self.task.id, token), message_id=90)

        self.assertIn("Rejection cancelled", self.last_reply())
        self.assertIsNone(self.session.scalar(select(TelegramPendingInput)))
        self.assertEqual(self.reply(SUPERVISOR_CHAT, "not a reason any more"), (False, False))
        self.assertEqual(self.status(self.task), "submitted")
        self.assertEqual(self.verifications(), [])

    def test_an_expired_reason_question_is_not_used(self):
        token = self.submit_cycle()
        self.press(SUPERVISOR_CHAT, task_callback("vr", self.task.id, token))
        with self.session.begin():
            self.session.scalar(select(TelegramPendingInput)).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.assertEqual(self.reply(SUPERVISOR_CHAT, "Too late"), (True, False))
        self.assertIn("Tap Reject on the review message again", self.last_reply())
        self.assertEqual(self.verifications(), [])

    # ---- who may review (AE5) --------------------------------------------------------------

    def test_a_supervisor_cannot_verify_their_own_submission_but_the_pm_can(self):
        with self.session.begin():
            from app.execution_models import TaskSupportAssignment
            self.session.query(TaskSupportAssignment).delete()  # the Supervisor executes it themselves
        token = self.submit_cycle(by=self.supervisor)

        self.assertFalse(self.press(SUPERVISOR_CHAT, task_callback("vf", self.task.id, token)))
        self.assertIn("a different Supervisor, PM, or Admin must verify it", self.last_reply())
        self.assertEqual(self.status(self.task), "submitted")

        self.assertTrue(self.press(PM_CHAT, task_callback("vf", self.task.id, token)))
        [verification] = self.verifications()
        self.assertEqual((verification.verified_by, verification.decision_mode), (self.pm[0].id, "pm_fallback"))

    # ---- stale buttons and questions (AE6, KTD19) --------------------------------------------

    def test_a_verify_button_from_an_earlier_submission_is_refused(self):
        """AE6: the cycle-1 button still exists while cycle 2 waits."""
        first_token = self.submit_cycle("Cycle 1")
        self.reject_in_web_app()
        second_token = self.submit_cycle("Cycle 2")
        self.assertNotEqual(first_token, second_token)

        self.assertFalse(self.press(SUPERVISOR_CHAT, task_callback("vf", self.task.id, first_token)))
        self.assertIn("older submission", self.last_reply())
        self.assertEqual(self.status(self.task), "submitted")
        self.assertEqual(len(self.verifications()), 1)  # only the Web App rejection

        self.assertTrue(self.press(SUPERVISOR_CHAT, task_callback("vf", self.task.id, second_token), message_id=91))
        self.assertEqual(self.status(self.task), "completed")

    def test_a_reject_reason_answered_after_a_new_submission_is_refused(self):
        token = self.submit_cycle("Cycle 1")
        self.press(SUPERVISOR_CHAT, task_callback("vr", self.task.id, token))
        # Meanwhile the task is rejected in the Web App and submitted again.
        self.reject_in_web_app()
        self.submit_cycle("Cycle 2")

        self.assertEqual(self.reply(SUPERVISOR_CHAT, "Late reason"), (True, False))
        self.assertIn("older submission", self.last_reply())
        self.assertEqual(self.status(self.task), "submitted")
        self.assertEqual(len(self.verifications()), 1)

    def test_already_decided_in_the_web_app_is_no_longer_awaiting_verification(self):
        token = self.submit_cycle()
        TaskVerificationService(self.session).verify(self.project.id, self.task.id, "verified", self.user(self.supervisor))
        self.assertFalse(self.press(SUPERVISOR_CHAT, task_callback("vf", self.task.id, token)))
        self.assertIn("no longer awaiting verification", self.last_reply())

    def test_group_chat_is_refused(self):
        token = self.submit_cycle()
        self.assertFalse(self.press(SUPERVISOR_CHAT, task_callback("vf", self.task.id, token), chat_type="group"))
        self.assertIn("Use the bot in a private chat", self.last_reply())
        self.assertEqual(self.status(self.task), "submitted")

    def test_the_current_token_matches_what_the_review_message_carried(self):
        self.submit_cycle("A")
        ids = [u.id for u in self.session.scalars(
            select(TaskProgressUpdate).where(TaskProgressUpdate.task_id == self.task.id, TaskProgressUpdate.reviewed_at.is_(None))
        )]
        from app.services.telegram_task_callback import TelegramTaskCallbackService
        task = self.session.get(type(self.task), self.task.id)
        self.assertEqual(TelegramTaskCallbackService(self.session).current_submission_token(task), submission_token(ids))


if __name__ == "__main__":
    unittest.main()
