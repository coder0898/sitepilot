"""Telegram T3-T5 and T7: scheduled task reminders on Asia/Kolkata time
(app/services/task_reminders.py), who receives them (message_dispatch.py),
their buttons (telegram_task_render.py), and the readiness / Report Delay
button flows (telegram_task_callback.py).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.execution_models import (
    OutboxEvent,
    Task,
    TaskBlocker,
    TaskDelayEvent,
    TaskReadinessDeclaration,
    TaskReminderLog,
)
from app.services.message_dispatch import MessageDispatchService
from app.services.task_reminders import IST, TaskReminderService
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_message import task_callback
from app.services.telegram_render import render_telegram
from app.vendor_models import TaskVendorAssignment
from tests.test_telegram_task_callback import EMPLOYEE_CHAT, TaskButtonHarness

TODAY = date(2026, 9, 28)


def ist(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


class ReminderHarness(TaskButtonHarness):
    def setUp(self):
        super().setUp()
        for table in (
            TaskReminderLog.__table__, TaskReadinessDeclaration.__table__, TaskDelayEvent.__table__,
            TaskVendorAssignment.__table__,
        ):
            table.create(self.engine)

    def make_task(self, code, status="planned", start=None, end=None, project=None, **extra) -> Task:
        with self.session.begin():
            task = self._task(project or self.project, code, status, start)
            task.planned_end_date = end
            for key, value in extra.items():
                setattr(task, key, value)
        return task

    def run_at(self, when: datetime) -> list[tuple[str, str]]:
        sent = TaskReminderService(self.session).send_due_reminders(when)
        return [(reminder, task.original_code) for reminder, task in sent]

    def events(self, event_type: str) -> list[OutboxEvent]:
        self.session.expire_all()
        return list(self.session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == event_type)))


class ReminderScheduleTests(ReminderHarness):
    def test_times_are_indian_standard_time_not_utc(self):
        self.make_task("S1", start=TODAY)
        # 03:29 UTC is 08:59 IST - too early; 03:30 UTC is 09:00 IST.
        self.assertEqual(self.run_at(datetime(2026, 9, 28, 3, 29, tzinfo=timezone.utc)), [])
        self.assertEqual(self.run_at(datetime(2026, 9, 28, 3, 30, tzinfo=timezone.utc)), [("start_check", "S1")])

    def test_the_ist_date_decides_today_across_the_utc_midnight(self):
        # 20:00 UTC on the 27th is 01:30 IST on the 28th: a task starting on
        # the 28th is "today", not "tomorrow".
        self.make_task("S1", start=TODAY)
        self.make_task("S2", start=TODAY + timedelta(days=1))
        sent = self.run_at(datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc) + timedelta(hours=13))  # 14:30 IST 28th
        self.assertEqual(sent, [])  # nothing is scheduled at 14:30 for not-started tasks
        self.assertEqual(self.run_at(ist(9, 5)), [("prestart_warning", "S2"), ("start_check", "S1")])

    def test_day_before_start_gets_the_warning_in_the_morning_and_the_readiness_check_in_the_evening(self):
        self.make_task("S1", start=TODAY + timedelta(days=1))
        self.assertEqual(self.run_at(ist(9, 0)), [("prestart_warning", "S1")])
        self.assertEqual(self.run_at(ist(18, 30)), [("readiness_check", "S1")])
        [readiness] = self.events("task.readiness_check")
        self.assertEqual(readiness.payload["scheduled_for_date"], (TODAY + timedelta(days=1)).isoformat())

    def test_start_check_is_muted_once_the_task_has_started(self):
        self.make_task("S1", status="in_progress", start=TODAY)
        self.make_task("S2", status="ready", start=TODAY)
        self.assertEqual(self.run_at(ist(9, 0)), [("start_check", "S2")])

    def test_a_reminder_is_not_sent_after_its_window(self):
        self.make_task("S1", start=TODAY)
        self.assertEqual(self.run_at(ist(13, 1)), [])

    def test_midday_and_eod_go_to_in_progress_work_only(self):
        self.make_task("W1", status="in_progress")
        self.make_task("W2", status="submitted")
        self.make_task("W3", status="completed")
        self.make_task("W4", status="cancelled")
        self.assertEqual(self.run_at(ist(13, 30)), [("midday_check", "W1")])
        self.assertEqual(self.run_at(ist(18, 30)), [("eod_check", "W1")])

    def test_open_blocker_mutes_midday_eod_and_overdue(self):
        task = self.make_task("W1", status="in_progress", end=TODAY - timedelta(days=1))
        with self.session.begin():
            self.session.add(TaskBlocker(
                task_id=task.id, project_id=self.project.id, type="Material", description="Tiles not delivered",
            ))
        for when in (ist(13, 30), ist(18, 30), ist(6, 30), ist(9, 30)):
            with self.subTest(when=when):
                self.assertEqual(self.run_at(when), [])

    def test_overdue_warning_at_0630_and_escalation_at_0930_the_day_after_it_was_due(self):
        self.make_task("W1", status="in_progress", end=TODAY - timedelta(days=1))
        self.make_task("W2", status="rejected", end=TODAY - timedelta(days=1))
        self.make_task("W3", status="submitted", end=TODAY - timedelta(days=1))
        self.make_task("W4", status="in_progress", end=TODAY)  # due today: not overdue yet
        self.assertEqual(self.run_at(ist(6, 29)), [])
        self.assertEqual(self.run_at(ist(6, 30)), [("sla_overdue", "W1"), ("sla_overdue", "W2")])
        self.assertEqual(
            [r for r in self.run_at(ist(9, 30)) if r[0] == "sla_escalation"],
            [("sla_escalation", "W1"), ("sla_escalation", "W2")],
        )

    def test_each_reminder_goes_out_at_most_once_a_day(self):
        self.make_task("W1", status="in_progress")
        self.assertEqual(self.run_at(ist(13, 30)), [("midday_check", "W1")])
        self.assertEqual(self.run_at(ist(13, 35)), [])
        self.assertEqual(self.run_at(ist(17, 55)), [])
        self.assertEqual(len(self.events("task.midday_check")), 1)
        # The next IST day is a new reminder.
        self.assertEqual(self.run_at(ist(13, 30, TODAY + timedelta(days=1))), [("midday_check", "W1")])
        self.assertEqual(len(self.session.scalars(select(TaskReminderLog)).all()), 2)

    def test_an_existing_log_row_blocks_the_send(self):
        task = self.make_task("W1", status="in_progress")
        with self.session.begin():
            self.session.add(TaskReminderLog(task_id=task.id, reminder_type="midday_check", scheduled_for_date=TODAY))
        self.assertEqual(self.run_at(ist(13, 30)), [])
        self.assertEqual(self.events("task.midday_check"), [])

    def test_inactive_projects_and_milestones_get_no_reminders(self):
        self.make_task("M1", status="in_progress", task_kind="milestone")
        with self.session.begin():
            self.session.get(type(self.other_project), self.other_project.id).status = "archived"
        self.make_task("A1", status="in_progress", project=self.other_project)
        self.assertEqual(self.run_at(ist(13, 30)), [])


class ReminderAudienceTests(ReminderHarness):
    def recipients(self, event_type: str) -> set:
        event = OutboxEvent(
            event_type=event_type, aggregate_type="task", aggregate_id=self.task.id,
            payload={"task_id": str(self.task.id), "project_id": str(self.project.id)},
            idempotency_key=str(uuid.uuid4()), status="pending",
        )
        return {r.employee_id for r in MessageDispatchService(self.session)._resolve_recipients(event)}

    def test_prestart_warning_goes_to_the_assignee_and_the_supervisor(self):
        self.assertEqual(self.recipients("task.prestart_warning"), {self.employee[1].id, self.supervisor[1].id})

    def test_overdue_warning_goes_to_the_assignee(self):
        self.assertEqual(self.recipients("task.sla_overdue"), {self.employee[1].id})

    def test_escalation_goes_to_the_pm_and_admins(self):
        self.assertEqual(self.recipients("task.sla_escalated"), {self.pm[1].id, self.admin[1].id})

    def test_start_check_keeps_its_audience(self):
        self.assertEqual(
            self.recipients("task.start_check"), {self.employee[1].id, self.supervisor[1].id, self.pm[1].id},
        )


class ReminderMessageTests(ReminderHarness):
    def render(self, event_type: str, recipient, status: str | None = None, **payload):
        self.session.commit()
        if status:
            self.set_status(self.task, status)
        body = {"task_id": str(self.task.id), "project_id": str(self.project.id), "lifecycle_status": status or "planned", **payload}
        return render_telegram(self.session, event_type, body, recipient[1].id)

    def buttons(self, message) -> list[str]:
        return [b["text"] for row in message.button_rows() for b in row]

    def test_prestart_warning_offers_report_blocker(self):
        message = self.render("task.prestart_warning", self.employee)
        self.assertIn("Task Starts Tomorrow", message.text)
        self.assertEqual(self.buttons(message), ["Report Blocker"])

    def test_readiness_check_offers_ready_need_help_issue(self):
        message = self.render("task.readiness_check", self.employee)
        self.assertIn("Can This Task Start Tomorrow?", message.text)
        self.assertEqual(self.buttons(message), ["Ready", "Need Help", "Issue"])

    def test_start_check_offers_the_next_lifecycle_step(self):
        message = self.render("task.start_check", self.employee, status="ready")
        self.assertIn("Task Starts Today", message.text)
        self.assertEqual(self.buttons(message)[0], "Start Task")

    def test_midday_and_eod_offer_progress_and_submit_to_the_executor(self):
        midday = self.render("task.midday_check", self.employee, status="in_progress")
        self.assertEqual(self.buttons(midday), ["Add Progress", "Submit for Review", "Report Blocker"])
        eod = self.render("task.eod_check", self.employee, status="in_progress")
        self.assertEqual(self.buttons(eod), ["Add Progress", "Submit for Review", "Report Delay", "Report Blocker"])

    def test_overdue_offers_submit_now_and_report_delay(self):
        message = self.render("task.sla_overdue", self.employee, status="in_progress", planned_end_date="2026-09-27")
        self.assertIn("Task Overdue", message.text)
        self.assertEqual(self.buttons(message), ["Add Progress", "Submit Now", "Report Delay"])

    def test_escalation_names_the_assignee_and_links_to_the_web_app(self):
        message = self.render("task.sla_escalated", self.pm, status="in_progress", planned_end_date="2026-09-27")
        self.assertIn("Escalation: Task Overdue", message.text)
        self.assertIn("Assigned to: Rohan", message.text)
        self.assertIn("Last progress: None logged", message.text)
        self.assertEqual(message.button_rows(), [])


class ReadinessAndDelayButtonTests(ReminderHarness):
    def text(self, body: str):
        self.update_id += 1
        return TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=EMPLOYEE_CHAT, text=body, chat_type="private",
        )

    def declarations(self) -> list[TaskReadinessDeclaration]:
        self.session.expire_all()
        return list(self.session.scalars(select(TaskReadinessDeclaration)))

    def delays(self) -> list[TaskDelayEvent]:
        self.session.expire_all()
        return list(self.session.scalars(select(TaskDelayEvent)))

    def test_ready_records_a_declaration_without_changing_the_status(self):
        self.assertTrue(self.press(EMPLOYEE_CHAT, task_callback("yr", self.task.id)))
        [declaration] = self.declarations()
        self.assertEqual((declaration.status, declaration.note), ("ready", None))
        self.assertEqual(self.status(self.task), "planned")
        self.assertIn("Readiness Recorded: Ready", self.last_reply())

    def test_issue_asks_for_a_note_then_records_it(self):
        self.press(EMPLOYEE_CHAT, task_callback("yi", self.task.id))
        self.assertIn("What is missing", self.last_reply())
        self.assertEqual(self.declarations(), [])
        self.assertEqual(self.text("No power on site"), (True, True))
        [declaration] = self.declarations()
        self.assertEqual((declaration.status, declaration.note), ("issue", "No power on site"))
        self.assertIn("Your Supervisor and PM have been told", self.last_reply())

    def test_cancelling_the_note_records_nothing(self):
        self.press(EMPLOYEE_CHAT, task_callback("yh", self.task.id))
        self.press(EMPLOYEE_CHAT, task_callback("yc", self.task.id))
        self.assertIn("Readiness not recorded", self.last_reply())
        self.assertEqual(self.text("late note"), (False, False))
        self.assertEqual(self.declarations(), [])

    def test_report_delay_asks_cause_days_and_reason_then_records_it(self):
        self.set_status(self.task, "in_progress")
        self.press(EMPLOYEE_CHAT, task_callback("dl", self.task.id))
        causes = [b["text"] for row in self.calls("sendMessage")[-1]["reply_markup"]["inline_keyboard"] for b in row]
        self.assertEqual(causes, ["Client", "Approval", "Design", "Site Readiness", "Internal", "Other", "Cancel"])
        self.assertNotIn("Vendor", causes)

        self.press(EMPLOYEE_CHAT, task_callback("dt", self.task.id, "client"))
        self.assertIn("By how many days", self.last_reply())
        self.assertEqual(self.text("two"), (True, False))
        self.assertIn("That wasn't a number of days", self.last_reply())
        self.assertEqual(self.text("2"), (True, False))
        self.assertIn("What is the reason", self.last_reply())
        self.assertEqual(self.text("Client has not approved the drawings"), (True, True))

        [delay] = self.delays()
        self.assertEqual(
            (delay.responsibility_type, delay.impact_days, delay.reason),
            ("client", 2, "Client has not approved the drawings"),
        )
        self.assertIn("Delay Recorded", self.last_reply())
        self.assertEqual(self.status(self.task), "in_progress")

    def test_vendor_cause_is_refused_even_if_sent_directly(self):
        self.press(EMPLOYEE_CHAT, task_callback("dt", self.task.id, "vendor"))
        self.assertIn("no longer available", self.last_reply())

    def test_cancelling_a_delay_records_nothing(self):
        self.press(EMPLOYEE_CHAT, task_callback("dt", self.task.id, "design"))
        self.press(EMPLOYEE_CHAT, task_callback("dc", self.task.id))
        self.assertIn("Delay report cancelled", self.last_reply())
        self.assertEqual(self.text("3"), (False, False))
        self.assertEqual(self.delays(), [])
