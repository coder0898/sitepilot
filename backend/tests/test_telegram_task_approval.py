"""PM Approve / Reject from Telegram (Telegram task plan U10).

The buttons call TaskApprovalService.approve - the same call as the Web App,
source "telegram" - and carry what is awaiting approval (class_a: the
verification; approval-gate task: the submission), so a stale button is
refused. Approval requests reach only people who may approve (KTD20): the
fallback verifier is never one of them, and when no PM may approve, Admins are
asked; when nobody may, the state is made explicit instead of silent.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.execution_models import OutboxEvent, Task, TaskApprovalDecision, TaskSupportAssignment
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2ProjectMembership
from app.services.message_dispatch import MessageDispatchService
from app.services.task_lifecycle import TaskLifecycleService
from app.services.task_progress import TaskProgressService
from app.services.task_verification import TaskVerificationService
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_message import submission_token, task_callback
from tests.test_telegram_task_callback import ADMIN_CHAT, PM_CHAT, TaskButtonHarness

PM2_CHAT = "700"


class TelegramTaskApprovalTests(TaskButtonHarness):
    def setUp(self):
        super().setUp()
        with self.session.begin():
            task = self.session.get(Task, self.task.id)
            task.task_class = "class_a"
            task.lifecycle_status = "in_progress"

    # ---- helpers ----------------------------------------------------------------------

    def user(self, person) -> User:
        return self.session.get(User, person[0].id)

    def submit(self, note="Work done.") -> str:
        employee = self.user(self.employee)
        update = TaskProgressService(self.session).submit_progress(self.project.id, self.task.id, employee, note=note)
        TaskLifecycleService(self.session).transition(self.project.id, self.task.id, "submitted", employee)
        return submission_token([update.id])

    def verification_events(self) -> list[OutboxEvent]:
        return list(self.session.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == "task.verification_recorded", OutboxEvent.aggregate_id == self.task.id,
        )))

    def verify_by(self, person) -> str:
        """Verifies the waiting submission; returns the approval token. The new
        event is found by elimination - two in the same second tie on time."""
        before = {e.id for e in self.verification_events()}
        TaskVerificationService(self.session).verify(self.project.id, self.task.id, "verified", self.user(person))
        [event] = [e for e in self.verification_events() if e.id not in before]
        self.latest_verification_event = event
        return uuid.UUID(event.payload["verification_id"]).hex[:8]

    def end_membership(self, role: str) -> None:
        self.session.commit()
        membership = self.session.scalar(select(V2ProjectMembership).where(
            V2ProjectMembership.project_id == self.project.id, V2ProjectMembership.project_role == role,
        ))
        membership.ends_at = datetime.now(timezone.utc)
        self.session.commit()

    def end_supervisor(self) -> None:
        self.end_membership("site_supervisor")

    def add_second_pm(self):
        self.session.commit()
        self.pm2 = self._person("Kiran", UserRole.project_manager, PM2_CHAT)
        self._member(self.project, self.pm2, "project_manager")
        self.session.commit()

    def approval_request_recipients(self) -> set:
        return {
            r.employee_id
            for r in MessageDispatchService(self.session)._resolve_recipients(self.latest_verification_event)
        }

    def admin_employee_id(self):
        return self.admin[1].id

    def decisions(self) -> list[TaskApprovalDecision]:
        self.session.expire_all()
        return list(self.session.scalars(select(TaskApprovalDecision).where(TaskApprovalDecision.task_id == self.task.id)))

    # ---- class_a -------------------------------------------------------------------------

    def test_pm_approves_class_a_work_and_it_completes_as_telegram(self):
        self.submit()
        token = self.verify_by(self.supervisor)
        self.assertTrue(self.press(PM_CHAT, task_callback("pa", self.task.id, token)))

        self.assertEqual(self.status(self.task), "completed")
        [decision] = self.decisions()
        self.assertEqual((decision.decision, decision.decided_by), ("approved", self.pm[0].id))
        sources = {a.source for a in self.session.scalars(select(V2AuditEvent).where(
            V2AuditEvent.entity_id == self.task.id, V2AuditEvent.actor_user_id == self.pm[0].id,
        ))}
        self.assertEqual(sources, {"telegram"})
        self.assertEqual(self.calls("answerCallbackQuery")[-1]["text"], "Approved")

    def test_pm_rejects_with_a_reason_and_the_task_reopens(self):
        self.submit()
        token = self.verify_by(self.supervisor)
        self.assertFalse(self.press(PM_CHAT, task_callback("pr", self.task.id, token)))
        self.assertIn("Please enter the reason for rejecting this work.", self.calls("sendMessage")[-1]["text"])
        self.update_id += 1
        handled, acted = TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=PM_CHAT, text="Wrong concrete grade", chat_type="private",
        )
        self.assertEqual((handled, acted), (True, True))
        self.assertEqual(self.status(self.task), "in_progress")
        [decision] = self.decisions()
        self.assertEqual((decision.decision, decision.remarks), ("rejected", "Wrong concrete grade"))

    def test_a_stale_approve_from_an_earlier_cycle_is_refused(self):
        self.submit("Cycle 1")
        first = self.verify_by(self.supervisor)
        # SQLite keeps whole seconds; make cycle 1 clearly older, as it always
        # is in practice, so "the current verification" is unambiguous.
        self.session.commit()
        from app.execution_models import TaskVerification
        from datetime import timedelta
        for verification in self.session.scalars(select(TaskVerification).where(TaskVerification.task_id == self.task.id)):
            verification.verified_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.session.commit()
        # PM rejects in the Web App; the work is redone and verified again.
        from app.services.task_approval import TaskApprovalService
        TaskApprovalService(self.session).approve(self.project.id, self.task.id, "rejected", self.user(self.pm), remarks="Redo")
        self.submit("Cycle 2")
        second = self.verify_by(self.supervisor)
        self.assertNotEqual(first, second)

        self.assertFalse(self.press(PM_CHAT, task_callback("pa", self.task.id, first)))
        self.assertIn("older submission", self.last_reply())
        self.assertEqual(self.status(self.task), "verified")
        self.assertTrue(self.press(PM_CHAT, task_callback("pa", self.task.id, second), message_id=95))
        self.assertEqual(self.status(self.task), "completed")

    def test_standard_work_never_awaits_approval(self):
        with self.session.begin():
            self.session.get(Task, self.task.id).task_class = "standard"
        self.submit()
        TaskVerificationService(self.session).verify(self.project.id, self.task.id, "verified", self.user(self.supervisor))
        self.assertEqual(self.status(self.task), "completed")
        self.assertFalse(self.press(PM_CHAT, task_callback("pa", self.task.id, "deadbeef")))
        self.assertIn("no longer awaiting approval", self.last_reply())

    # ---- eligible approvers (KTD20) - the required fallback test ---------------------------

    def test_no_supervisor_pm_fallback_verifies_then_cannot_approve_and_admin_is_asked(self):
        """no Supervisor -> PM fallback verifies -> same PM cannot approve ->
        Admin receives the approval request and approves."""
        self.submit()  # submitted while the Supervisor was still active
        self.end_supervisor()
        token = self.verify_by(self.pm)
        self.assertEqual(self.latest_verification_event.payload["decision_mode"], "pm_fallback")

        # The same PM is refused by the approval service itself.
        self.assertFalse(self.press(PM_CHAT, task_callback("pa", self.task.id, token)))
        self.assertIn("cannot also record its approval decision", self.last_reply())
        self.assertEqual(self.status(self.task), "verified")

        # The Admin is asked, and their Approve completes the task.
        self.assertIn(self.admin_employee_id(), self.approval_request_recipients())
        self.assertTrue(self.press(ADMIN_CHAT, task_callback("pa", self.task.id, token), message_id=96))
        self.assertEqual(self.status(self.task), "completed")

    def test_with_a_second_pm_the_other_pm_approves_and_admin_is_not_asked(self):
        self.add_second_pm()
        self.submit()
        self.end_supervisor()
        token = self.verify_by(self.pm)

        self.assertNotIn(self.admin_employee_id(), self.approval_request_recipients())
        self.assertIn(self.pm2[1].id, self.approval_request_recipients())
        self.assertTrue(self.press(PM2_CHAT, task_callback("pa", self.task.id, token)))
        self.assertEqual(self.status(self.task), "completed")

    def test_an_admin_who_verified_as_fallback_cannot_approve_but_the_pm_can(self):
        self.submit()
        token = self.verify_by(self.admin)
        self.assertFalse(self.press(ADMIN_CHAT, task_callback("pa", self.task.id, token)))
        self.assertIn("cannot also record its approval decision", self.last_reply())
        self.assertTrue(self.press(PM_CHAT, task_callback("pa", self.task.id, token), message_id=97))

    def test_no_active_pm_means_admin_is_asked(self):
        self.submit()
        token = self.verify_by(self.supervisor)
        self.end_membership("project_manager")
        self.assertIn(self.admin_employee_id(), self.approval_request_recipients())
        # The Admin has no project membership and keeps their authority (KTD22).
        self.assertTrue(self.press(ADMIN_CHAT, task_callback("pa", self.task.id, token)))
        self.assertEqual(self.status(self.task), "completed")

    def test_no_eligible_approver_is_logged_explicitly_and_nothing_changes(self):
        self.submit()
        self.end_supervisor()
        self.verify_by(self.pm)
        self.session.commit()
        self.session.get(User, self.admin[0].id).active = False
        self.session.commit()
        with self.assertLogs("app.services.message_dispatch", level="WARNING") as logs:
            recipients = self.approval_request_recipients()
        self.assertIn("no_eligible_approver", logs.output[0])
        self.assertIn("T001", logs.output[0])
        self.assertNotIn(self.admin_employee_id(), recipients)
        self.assertEqual(self.status(self.task), "verified")

    # ---- approval-gate task -----------------------------------------------------------------

    def test_approval_gate_task_is_approved_directly_after_submission(self):
        with self.session.begin():
            task = self.session.get(Task, self.task.id)
            task.task_kind, task.task_class = "approval_gate", None
        token = self.submit("Permit filed")
        self.assertTrue(self.press(PM_CHAT, task_callback("pa", self.task.id, token)))
        self.assertEqual(self.status(self.task), "completed")
        self.assertIsNone(self.decisions()[0].verification_id)

    def test_approval_gate_pm_reject_reopens_it(self):
        with self.session.begin():
            task = self.session.get(Task, self.task.id)
            task.task_kind, task.task_class = "approval_gate", None
        token = self.submit("Permit filed")
        self.press(PM_CHAT, task_callback("pr", self.task.id, token))
        self.update_id += 1
        TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=PM_CHAT, text="Unsigned copy", chat_type="private",
        )
        self.assertEqual(self.status(self.task), "in_progress")

    def test_cancel_on_the_pm_reject_question_records_nothing(self):
        self.submit()
        token = self.verify_by(self.supervisor)
        self.press(PM_CHAT, task_callback("pr", self.task.id, token))
        self.press(PM_CHAT, task_callback("pc", self.task.id, token), message_id=98)
        self.assertIn("Rejection cancelled", self.last_reply())
        self.assertEqual(self.decisions(), [])
        self.assertEqual(self.status(self.task), "verified")


if __name__ == "__main__":
    unittest.main()
