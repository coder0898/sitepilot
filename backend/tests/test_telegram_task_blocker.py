"""Report and resolve blockers from Telegram (Telegram task plan U12).

[Report Blocker] asks for the type, then the description, and records the
blocker through TaskBlockerService with the person as its reporter. [Resolve]
(Supervisor/PM/Admin only) carries the blocker's id - the task and project
come from the blocker row - and the reporter is told it was resolved.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import select

from app.execution_models import OutboxEvent, TaskBlocker
from app.services.message_dispatch import MessageDispatchService
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_message import task_callback
from app.services.telegram_render import render_telegram
from tests.test_telegram_task_callback import EMPLOYEE_CHAT, OTHER_CHAT, SUPERVISOR_CHAT, TaskButtonHarness


class TelegramTaskBlockerTests(TaskButtonHarness):
    def setUp(self):
        super().setUp()
        self.set_status(self.task, "in_progress")
        self.message_id = 2000

    # ---- helpers ------------------------------------------------------------------

    def tap(self, chat, code, target_id, **kwargs) -> bool:
        self.message_id += 1
        return self.press(chat, task_callback(code, target_id), message_id=self.message_id, **kwargs)

    def say(self, chat, text, chat_type="private") -> tuple[bool, bool]:
        self.update_id += 1
        return TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=chat, text=text, chat_type=chat_type,
        )

    def report(self, chat=EMPLOYEE_CHAT, type_="Material", description="Tiles not delivered") -> None:
        self.tap(chat, "rb", self.task.id)
        self.assertEqual(self.say(chat, type_), (True, False))
        self.assertEqual(self.say(chat, description), (True, True))

    def blockers(self) -> list[TaskBlocker]:
        self.session.expire_all()
        return list(self.session.scalars(select(TaskBlocker).where(TaskBlocker.task_id == self.task.id)))

    def event(self, event_type) -> OutboxEvent:
        self.session.expire_all()
        return self.session.scalar(select(OutboxEvent).where(
            OutboxEvent.aggregate_id == self.task.id, OutboxEvent.event_type == event_type,
        ))

    # ---- reporting -------------------------------------------------------------------

    def test_report_asks_type_then_description_and_records_the_reporter(self):
        self.tap(EMPLOYEE_CHAT, "rb", self.task.id)
        self.assertIn("What type of blocker is it?", self.calls("sendMessage")[-1]["text"])
        self.say(EMPLOYEE_CHAT, "Material")
        self.assertIn("Now describe the blocker", self.calls("sendMessage")[-1]["text"])
        self.say(EMPLOYEE_CHAT, "Tiles not delivered")

        [blocker] = self.blockers()
        self.assertEqual((blocker.type, blocker.description), ("Material", "Tiles not delivered"))
        self.assertEqual(blocker.reported_by, self.employee[0].id)
        self.assertIn("<b>Blocker Reported</b>", self.last_reply())
        self.assertEqual(self.event("task.blocker_created").payload["reported_by"], str(self.employee[0].id))

    def test_any_project_member_may_report_even_if_not_assigned(self):
        self.report(chat=OTHER_CHAT)
        [blocker] = self.blockers()
        self.assertEqual(blocker.reported_by, self.other[0].id)

    def test_cancel_at_either_question_records_nothing(self):
        self.tap(EMPLOYEE_CHAT, "rb", self.task.id)
        self.tap(EMPLOYEE_CHAT, "bc", self.task.id)
        self.assertIn("Blocker report cancelled", self.last_reply())

        self.tap(EMPLOYEE_CHAT, "rb", self.task.id)
        self.say(EMPLOYEE_CHAT, "Access")
        self.tap(EMPLOYEE_CHAT, "bc", self.task.id)
        self.assertEqual(self.say(EMPLOYEE_CHAT, "Gate locked"), (False, False))  # not a description any more
        self.assertEqual(self.blockers(), [])

    def test_group_chat_cannot_report(self):
        self.assertFalse(self.tap(EMPLOYEE_CHAT, "rb", self.task.id, chat_type="group"))
        self.assertIn("Use the bot in a private chat", self.last_reply())
        self.assertEqual(self.blockers(), [])

    # ---- resolving ---------------------------------------------------------------------

    def test_supervisor_resolves_and_the_reporter_is_told(self):
        self.report()
        [blocker] = self.blockers()
        self.assertTrue(self.tap(SUPERVISOR_CHAT, "bs", blocker.id))

        [blocker] = self.blockers()
        self.assertIsNotNone(blocker.resolved_at)
        self.assertEqual(blocker.resolved_by, self.supervisor[0].id)
        resolved = self.event("task.blocker_resolved")
        recipients = {r.employee_id for r in MessageDispatchService(self.session)._resolve_recipients(resolved)}
        self.assertIn(self.employee[1].id, recipients)
        reporter_copy = render_telegram(self.session, resolved.event_type, resolved.payload, self.employee[1].id)
        self.assertIn("The blocker you reported was resolved.", reporter_copy.text)

    def test_an_employee_gets_no_resolve_button_and_a_forged_one_is_refused(self):
        self.report()
        [blocker] = self.blockers()
        created = self.event("task.blocker_created")
        employee_copy = render_telegram(self.session, created.event_type, created.payload, self.employee[1].id)
        self.assertEqual(employee_copy.button_rows(), [])
        supervisor_copy = render_telegram(self.session, created.event_type, created.payload, self.supervisor[1].id)
        [[resolve]] = supervisor_copy.button_rows()
        self.assertEqual((resolve["text"], resolve["callback_data"]), ("Resolve", f"t1:bs:{blocker.id.hex}"))

        self.assertFalse(self.tap(EMPLOYEE_CHAT, "bs", blocker.id))
        self.assertIn("Only the project's Supervisor, PM, or an Admin can resolve a blocker.", self.last_reply())
        self.assertIsNone(self.blockers()[0].resolved_at)

    def test_resolving_twice_is_refused_readably(self):
        self.report()
        [blocker] = self.blockers()
        self.assertTrue(self.tap(SUPERVISOR_CHAT, "bs", blocker.id))
        self.assertFalse(self.tap(SUPERVISOR_CHAT, "bs", blocker.id))
        self.assertIn("already been resolved", self.last_reply())

    def test_an_old_blocker_without_a_reporter_resolves_and_tells_no_reporter(self):
        with self.session.begin():
            old = TaskBlocker(task_id=self.task.id, project_id=self.project.id, type="Design", description="Old one")
            self.session.add(old)
        self.assertTrue(self.tap(SUPERVISOR_CHAT, "bs", old.id))
        resolved = self.event("task.blocker_resolved")
        self.assertIsNone(resolved.payload["reported_by"])
        recipients = {r.employee_id for r in MessageDispatchService(self.session)._resolve_recipients(resolved)}
        self.assertNotIn(self.employee[1].id, recipients)

    def test_an_unknown_blocker_button_is_no_longer_available(self):
        self.assertFalse(self.tap(SUPERVISOR_CHAT, "bs", uuid.uuid4()))
        self.assertIn("This button is no longer available.", self.last_reply())

    # ---- where [Report Blocker] appears -------------------------------------------------

    def test_report_blocker_button_on_task_started_and_daily_checks_for_members(self):
        payloads = {
            "task.status_changed": {"before_status": "ready", "target_status": "in_progress"},
            "task.midday_check": {"lifecycle_status": "in_progress"},
            "task.eod_check": {"lifecycle_status": "in_progress"},
        }
        for event_type, payload in payloads.items():
            full = {"task_id": str(self.task.id), "project_id": str(self.project.id), **payload}
            for recipient in (self.employee, self.supervisor, self.other):
                with self.subTest(event_type=event_type, recipient=recipient[0].name):
                    message = render_telegram(self.session, event_type, full, recipient[1].id)
                    self.assertIn("Report Blocker", [b["text"] for row in message.button_rows() for b in row])

    def test_progress_added_reply_offers_report_blocker(self):
        self.tap(EMPLOYEE_CHAT, "ap", self.task.id)
        self.say(EMPLOYEE_CHAT, "Half the tiles laid")
        labels = [b["text"] for row in self.calls("sendMessage")[-1]["reply_markup"]["inline_keyboard"] for b in row]
        self.assertEqual(labels, ["Submit for Review", "Done", "Report Blocker"])


if __name__ == "__main__":
    unittest.main()
