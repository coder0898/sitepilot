"""The rework loop on Telegram, over repeated rounds (Telegram task plan U11).

Driven end to end through the task buttons, as the people would use them:
the employee adds progress and submits, the Supervisor verifies or rejects
with a reason, the PM approves or rejects with a reason. Every round must
notify again (U1), refuse a resubmission until new progress is logged (U2),
refuse buttons from earlier rounds (KTD19), and offer [Add Progress]
[Submit Again] on "Rework Required".
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.execution_models import OutboxEvent, Task, TaskApprovalDecision, TaskVerification
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_render import render_telegram
from app.services.telegram_task_render import current_approval_token, current_submission_token
from app.services.telegram_message import task_callback
from tests.test_telegram_task_callback import EMPLOYEE_CHAT, PM_CHAT, SUPERVISOR_CHAT, TaskButtonHarness


class TelegramReworkLoopTests(TaskButtonHarness):
    def setUp(self):
        super().setUp()
        self.set_status(self.task, "in_progress")
        self.message_id = 1000

    # ---- people acting through the buttons ----------------------------------------------

    def tap(self, chat, code, token=None) -> bool:
        self.message_id += 1
        return self.press(chat, task_callback(code, self.task.id, token), message_id=self.message_id)

    def say(self, chat, text) -> tuple[bool, bool]:
        self.update_id += 1
        return TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=chat, text=text, chat_type="private",
        )

    def add_progress(self, note):
        self.tap(EMPLOYEE_CHAT, "ap")
        self.assertEqual(self.say(EMPLOYEE_CHAT, note), (True, True))

    def submit_again(self) -> bool:
        return self.tap(EMPLOYEE_CHAT, "sb")

    def review_token(self) -> str:
        self.session.expire_all()
        return current_submission_token(self.session, self.session.get(Task, self.task.id))

    def approval_token(self) -> str:
        self.session.expire_all()
        return current_approval_token(self.session, self.session.get(Task, self.task.id))

    def supervisor_rejects(self, reason):
        self.tap(SUPERVISOR_CHAT, "vr", self.review_token())
        self.assertEqual(self.say(SUPERVISOR_CHAT, reason), (True, True))

    def age_verifications(self, minutes: int) -> None:
        """SQLite keeps whole seconds, so decisions made within one second
        tie on time. Rounds are minutes apart in practice; say so explicitly,
        so "the current verification" (and the approval token) is unambiguous.
        Only verifications not already aged are moved."""
        self.session.commit()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
        for verification in self.session.scalars(select(TaskVerification).where(TaskVerification.task_id == self.task.id)):
            verified_at = verification.verified_at
            if verified_at.tzinfo is None:
                verified_at = verified_at.replace(tzinfo=timezone.utc)
            if verified_at > cutoff:
                verification.verified_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        self.session.commit()

    def pm_rejects(self, reason):
        self.tap(PM_CHAT, "pr", self.approval_token())
        self.assertEqual(self.say(PM_CHAT, reason), (True, True))

    # ---- what was recorded / sent --------------------------------------------------------

    def events(self, event_type, **payload_match) -> list[OutboxEvent]:
        self.session.expire_all()
        rows = self.session.scalars(select(OutboxEvent).where(
            OutboxEvent.aggregate_id == self.task.id, OutboxEvent.event_type == event_type,
        )).all()
        return [r for r in rows if all(r.payload.get(k) == v for k, v in payload_match.items())]

    def rework_message_for_employee(self, event: OutboxEvent):
        return render_telegram(self.session, event.event_type, event.payload, self.employee[1].id)

    # ---- standard work: reject, reject, verify ---------------------------------------------------

    def test_three_rounds_each_notify_and_each_needs_new_progress(self):
        """AE1 + AE2 over three rounds (reject, reject, verify)."""
        self.add_progress("Round 1")
        self.assertTrue(self.submit_again())
        tokens = [self.review_token()]
        self.supervisor_rejects("Round 1 gaps")

        # AE2: Submit Again is refused until this round has new progress.
        self.assertFalse(self.submit_again())
        self.assertIn("Add new progress before submitting.", self.last_reply())
        self.add_progress("Round 2")
        self.assertTrue(self.submit_again())
        tokens.append(self.review_token())
        self.supervisor_rejects("Round 2 still loose")

        self.assertFalse(self.submit_again())
        self.add_progress("Round 3")
        self.assertTrue(self.submit_again())
        tokens.append(self.review_token())

        # AE6: the buttons from rounds 1 and 2 are refused during round 3.
        for old in tokens[:2]:
            self.assertFalse(self.tap(SUPERVISOR_CHAT, "vf", old))
            self.assertIn("older submission", self.last_reply())
        self.assertTrue(self.tap(SUPERVISOR_CHAT, "vf", tokens[2]))
        self.assertEqual(self.status(self.task), "completed")

        # AE1: every round produced its own submitted and rejection messages.
        self.assertEqual(len(self.events("task.status_changed", target_status="submitted")), 3)
        rejections = self.events("task.verification_recorded", decision="rejected")
        self.assertEqual(sorted(e.payload["remarks"] for e in rejections), ["Round 1 gaps", "Round 2 still loose"])
        self.assertEqual(len(set(tokens)), 3)

    def test_rework_required_offers_add_progress_and_submit_again(self):
        self.add_progress("Work")
        self.submit_again()
        self.supervisor_rejects("Redo the edges")
        [rejection] = self.events("task.verification_recorded", decision="rejected")

        message = self.rework_message_for_employee(rejection)
        self.assertIn("<b>Rework Required</b>", message.text)
        self.assertIn("Reason: Redo the edges", message.text)
        self.assertEqual(
            [(b["text"], b["callback_data"]) for row in message.button_rows() for b in row],
            [("Add Progress", f"t1:ap:{self.task.id.hex}"), ("Submit Again", f"t1:sb:{self.task.id.hex}")],
        )
        # The reviewer's copy of the same rejection has no rework buttons.
        reviewer_copy = render_telegram(self.session, rejection.event_type, rejection.payload, self.supervisor[1].id)
        self.assertEqual(reviewer_copy.button_rows(), [])

    def test_rework_buttons_disappear_once_the_task_moves_on(self):
        self.add_progress("Work")
        self.submit_again()
        self.supervisor_rejects("Redo")
        [rejection] = self.events("task.verification_recorded", decision="rejected")
        self.add_progress("Fixed")
        self.submit_again()  # now submitted again: the old rework message offers nothing
        self.assertEqual(self.rework_message_for_employee(rejection).button_rows(), [])

    # ---- class_a: Supervisor reject, then PM reject, then approve -------------------------------

    def test_class_a_supervisor_reject_then_pm_reject_then_approve(self):
        with self.session.begin():
            self.session.get(Task, self.task.id).task_class = "class_a"

        self.add_progress("Round 1")
        self.submit_again()
        self.supervisor_rejects("Supervisor: redo")
        self.age_verifications(minutes=10)

        self.add_progress("Round 2")
        self.submit_again()
        self.assertTrue(self.tap(SUPERVISOR_CHAT, "vf", self.review_token()))
        self.assertEqual(self.status(self.task), "verified")
        first_approval = self.approval_token()
        self.pm_rejects("PM: wrong grade")
        self.assertEqual(self.status(self.task), "in_progress")
        self.age_verifications(minutes=5)

        self.assertFalse(self.submit_again())  # the PM rejection closed the round too
        self.add_progress("Round 3")
        self.submit_again()
        self.assertTrue(self.tap(SUPERVISOR_CHAT, "vf", self.review_token()))
        self.assertFalse(self.tap(PM_CHAT, "pa", first_approval))  # round 2's approval button
        self.assertIn("older submission", self.last_reply())
        self.assertTrue(self.tap(PM_CHAT, "pa", self.approval_token()))
        self.assertEqual(self.status(self.task), "completed")

        self.session.expire_all()
        verifications = self.session.scalars(select(TaskVerification).where(TaskVerification.task_id == self.task.id)).all()
        self.assertEqual(sorted(v.decision for v in verifications), ["rejected", "verified", "verified"])
        decisions = self.session.scalars(select(TaskApprovalDecision).where(TaskApprovalDecision.task_id == self.task.id)).all()
        self.assertEqual(sorted(d.decision for d in decisions), ["approved", "rejected"])
        self.assertEqual(len(self.events("task.approval_recorded", decision="rejected")), 1)

    # ---- approval-gate task: PM reject twice, then approve ------------------------------------------

    def test_approval_gate_pm_reject_twice_then_approve(self):
        with self.session.begin():
            task = self.session.get(Task, self.task.id)
            task.task_kind, task.task_class = "approval_gate", "class_a"

        tokens = []
        for round_no, reason in ((1, "Unsigned copy"), (2, "Wrong permit number")):
            self.add_progress(f"Round {round_no}")
            self.assertTrue(self.submit_again())
            tokens.append(self.approval_token())
            self.pm_rejects(reason)
            self.assertFalse(self.submit_again())

        self.add_progress("Round 3")
        self.assertTrue(self.submit_again())
        for old in tokens:
            self.assertFalse(self.tap(PM_CHAT, "pa", old))
        self.assertTrue(self.tap(PM_CHAT, "pa", self.approval_token()))
        self.assertEqual(self.status(self.task), "completed")

        self.assertEqual(len(self.events("task.status_changed", target_status="submitted")), 3)
        self.assertEqual(
            sorted(e.payload["remarks"] for e in self.events("task.approval_recorded", decision="rejected")),
            ["Unsigned copy", "Wrong permit number"],
        )
        # No Supervisor verification ever happened on the gate task.
        self.assertEqual(self.events("task.verification_recorded"), [])


if __name__ == "__main__":
    unittest.main()
