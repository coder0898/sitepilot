"""Telegram task buttons: Mark Task Ready and Start Task (Telegram task plan U5,
app/services/telegram_task_callback.py).

The buttons call TaskLifecycleService.transition directly (source
"telegram"); these tests prove the channel guards (private chat, presser =
chat owner, linked active person, Admin or active project member) and that
every lifecycle refusal reaches the user as a readable message.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.execution_models import (
    FileObject,
    InboundMessage,
    OutboxEvent,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDependency,
    TaskEvidence,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
    TelegramInboundUpdate,
    TelegramPendingInput,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_message import task_callback
from app.services.telegram_task_callback import TelegramTaskCallbackService
from app.template_models import V2TemplateVersion  # noqa: F401 - FK target for V2Project
from app.vendor_models import V2VendorContact

SUPERVISOR_CHAT, EMPLOYEE_CHAT, OTHER_CHAT, ADMIN_CHAT, REMOVED_CHAT, UNLINKED_CHAT = "100", "200", "300", "400", "500", "999"
PM_CHAT = "600"


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class _FakeResponse:
    status_code = 200
    content = b"x"

    def json(self):
        return {"ok": True, "result": {"message_id": 1}}


class TaskButtonHarness(unittest.TestCase):
    """Shared setup for the task-button tests (also used by
    test_telegram_task_progress.py)."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            V2ProjectExternalGate.__table__, ProjectExternalApproval.__table__, ProjectExternalApprovalTask.__table__,
            Task.__table__, TaskDependency.__table__, TaskSupportAssignment.__table__, TaskVerification.__table__,
            TaskApprovalDecision.__table__, V2AuditEvent.__table__, OutboxEvent.__table__, InboundMessage.__table__,
            TelegramInboundUpdate.__table__, V2VendorContact.__table__, TelegramPendingInput.__table__,
            TaskProgressUpdate.__table__, TaskEvidence.__table__, FileObject.__table__, TaskBlocker.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()

        with self.session.begin():
            self.admin = self._person("Niddhi", UserRole.admin, ADMIN_CHAT)
            self.supervisor = self._person("Deepak", UserRole.supervisor, SUPERVISOR_CHAT)
            self.employee = self._person("Rohan", UserRole.internal_employee, EMPLOYEE_CHAT)
            self.other = self._person("Preeti", UserRole.internal_employee, OTHER_CHAT)
            self.removed = self._person("Chetan", UserRole.internal_employee, REMOVED_CHAT)
            self.pm = self._person("Prachit", UserRole.project_manager, PM_CHAT)

            self.project = self._project("PRJ-A")
            self.other_project = self._project("PRJ-B")
            self._member(self.project, self.supervisor, "site_supervisor")
            self._member(self.project, self.pm, "project_manager")
            self._member(self.other_project, self.supervisor, "site_supervisor")
            self._member(self.project, self.employee, "internal_employee")
            self._member(self.project, self.other, "internal_employee")
            self._member(self.project, self.removed, "internal_employee", ended=True)

            yesterday = date.today() - timedelta(days=1)
            self.task = self._task(self.project, "T001", "planned", yesterday)
            self.twin = self._task(self.other_project, "T001", "planned", yesterday)
            self.session.add(TaskSupportAssignment(
                task_id=self.task.id, project_id=self.project.id, employee_id=self.employee[1].id,
                responsibility="Execution", assigned_by=self.supervisor[0].id,
            ))

        self._original_token = settings.telegram_access_token
        settings.telegram_access_token = "test-token"
        self._http_patch = patch("app.services.telegram_provider.httpx.post", return_value=_FakeResponse())
        self.mock_post = self._http_patch.start()
        self.update_id = 7000

    def tearDown(self):
        self._http_patch.stop()
        settings.telegram_access_token = self._original_token
        self.session.close()

    # ---- fixtures -------------------------------------------------------------------

    def _person(self, name, role, chat_id):
        user = User(id=uuid.uuid4(), name=name, email=f"{name.lower()}@example.com", role=role, active=True)
        self.session.add(user)
        self.session.flush()
        profile = EmployeeProfile(
            user_id=user.id, employee_code=f"E-{name}", designation=name, availability="available",
            telegram_chat_id=chat_id, active_channel="telegram",
        )
        self.session.add(profile)
        self.session.flush()
        return user, profile

    def _project(self, code):
        project = V2Project(
            code=code, name=code, client_name="Client", site_address="Site", start_date=date(2026, 9, 1),
            status="active", created_by=self.admin[0].id,
        )
        self.session.add(project)
        self.session.flush()
        return project

    def _member(self, project, person, role, ended=False):
        self.session.add(V2ProjectMembership(
            project_id=project.id, employee_id=person[1].id, project_role=role, assigned_by=self.admin[0].id,
            assignment_reason="seed", ends_at=datetime.now(timezone.utc) if ended else None,
        ))

    def _task(self, project, code, status, planned_start):
        task = Task(
            project_id=project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(), original_code=code,
            template_sequence=1, title=f"Task {code}", schedule_classification="execution", applicability="mandatory",
            task_kind="work", lifecycle_status=status, planned_start_date=planned_start,
        )
        self.session.add(task)
        self.session.flush()
        return task

    # ---- helpers ----------------------------------------------------------------------

    def press(self, chat_id, data, *, message_id=42, chat_type="private", from_id=None) -> bool:
        """Simulates the webhook: store the raw update, then hand it over."""
        self.update_id += 1
        self.session.add(TelegramInboundUpdate(
            update_id=self.update_id, chat_id=chat_id, callback_data=data,
            raw_payload={"callback_query": {"id": f"cb{self.update_id}", "data": data,
                                            "message": {"chat": {"id": chat_id, "type": chat_type}, "message_id": message_id}}},
        ))
        self.session.commit()
        return TelegramTaskCallbackService(self.session).handle(
            update_id=self.update_id, chat_id=chat_id, chat_type=chat_type,
            from_id=from_id if from_id is not None else chat_id, message_id=message_id,
            callback_query_id=f"cb{self.update_id}", data=data,
        )

    def calls(self, method):
        return [c.kwargs["json"] for c in self.mock_post.call_args_list if c.args[0].endswith(f"/{method}")]

    def last_reply(self) -> str:
        return self.calls("sendMessage")[-1]["text"]

    def status(self, task) -> str:
        self.session.expire_all()
        return self.session.get(Task, task.id).lifecycle_status

    def set_status(self, task, status):
        with self.session.begin():
            self.session.get(Task, task.id).lifecycle_status = status

    def last_inbound(self) -> InboundMessage:
        return self.session.scalar(select(InboundMessage).order_by(InboundMessage.created_at.desc(), InboundMessage.provider_message_id.desc()))


class TelegramTaskCallbackTests(TaskButtonHarness):
    # ---- success paths ------------------------------------------------------------------

    def test_assignee_marks_ready_audited_as_telegram_with_their_name(self):
        self.assertTrue(self.press(EMPLOYEE_CHAT, task_callback("rd", self.task.id)))

        self.assertEqual(self.status(self.task), "ready")
        audit = self.session.scalar(select(V2AuditEvent).where(V2AuditEvent.entity_id == self.task.id))
        self.assertEqual((audit.source, audit.actor_user_id), ("telegram", self.employee[0].id))
        self.assertEqual(self.calls("answerCallbackQuery")[-1]["text"], "Marked ready")
        self.assertEqual(len(self.calls("editMessageReplyMarkup")), 1)  # buttons removed
        self.assertEqual(self.last_inbound().processing_status, "processed")
        self.assertEqual(self.last_inbound().raw_body, "[button] Mark Task Ready T001")

    def test_assignee_starts_an_on_time_task(self):
        self.set_status(self.task, "ready")
        self.assertTrue(self.press(EMPLOYEE_CHAT, task_callback("st", self.task.id)))
        self.assertEqual(self.status(self.task), "in_progress")

    def test_admin_without_membership_keeps_their_authority(self):
        self.set_status(self.task, "ready")
        self.assertTrue(self.press(ADMIN_CHAT, task_callback("st", self.task.id)))
        self.assertEqual(self.status(self.task), "in_progress")

    def test_the_button_acts_only_on_its_own_task_when_codes_repeat(self):
        self.assertTrue(self.press(SUPERVISOR_CHAT, task_callback("rd", self.twin.id)))
        self.assertEqual(self.status(self.twin), "ready")
        self.assertEqual(self.status(self.task), "planned")

    # ---- lifecycle refusals are readable -------------------------------------------------

    def test_non_assignee_employee_is_refused_by_the_lifecycle_rule(self):
        self.set_status(self.task, "ready")
        self.assertFalse(self.press(OTHER_CHAT, task_callback("st", self.task.id)))
        self.assertEqual(self.status(self.task), "ready")
        self.assertIn("Couldn't start this task", self.last_reply())
        self.assertIn("only they can start or submit it", self.last_reply())
        self.assertEqual(self.last_inbound().processing_status, "rejected")

    def test_unsatisfied_predecessor_is_refused(self):
        with self.session.begin():
            predecessor = self._task(self.project, "T000", "planned", date.today())
            self.session.add(TaskDependency(
                project_id=self.project.id, baseline_id=self.task.baseline_id,
                predecessor_task_id=predecessor.id, successor_task_id=self.task.id,
                dependency_type="finish_to_start", blocking=True,
            ))
        self.assertFalse(self.press(EMPLOYEE_CHAT, task_callback("rd", self.task.id)))
        self.assertEqual(self.status(self.task), "planned")
        self.assertIn("predecessor", self.last_reply())

    # ---- U6: early start asks for a real reason ---------------------------------------------

    def _make_early(self) -> date:
        planned = date.today() + timedelta(days=2)
        with self.session.begin():
            task = self.session.get(Task, self.task.id)
            task.lifecycle_status = "ready"
            task.planned_start_date = planned
        return planned

    def reply(self, chat_id: str, text: str, chat_type: str = "private") -> tuple[bool, bool]:
        """Simulates the webhook's text path (pending question first)."""
        self.update_id += 1
        return TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=chat_id, text=text, chat_type=chat_type,
        )

    def pending(self) -> TelegramPendingInput | None:
        self.session.expire_all()
        return self.session.scalar(select(TelegramPendingInput))

    def test_early_start_asks_for_a_reason_with_the_planned_date(self):
        planned = self._make_early()
        self.assertFalse(self.press(EMPLOYEE_CHAT, task_callback("st", self.task.id)))

        self.assertEqual(self.status(self.task), "ready")
        question = self.calls("sendMessage")[-1]
        self.assertIn("Start Early: T001 - Task T001", question["text"])
        self.assertIn(f"planned to start on {planned.strftime('%d %b %Y').lstrip('0')}", question["text"])
        self.assertIn("Please provide the reason for starting this task early.", question["text"])
        [[cancel]] = question["reply_markup"]["inline_keyboard"]
        self.assertEqual(cancel["text"], "Cancel")
        self.assertEqual(cancel["callback_data"], f"t1:ce:{self.task.id.hex}")
        self.assertEqual(self.calls("answerCallbackQuery")[-1]["text"], "Reason needed")
        pending = self.pending()
        self.assertEqual((pending.kind, pending.task_id, pending.approval_id), ("task_early_start_reason", self.task.id, None))

    def test_the_reply_starts_the_task_with_that_reason(self):
        self._make_early()
        self.press(EMPLOYEE_CHAT, task_callback("st", self.task.id))

        handled, acted = self.reply(EMPLOYEE_CHAT, "  Site   handed over a day early  ")

        self.assertEqual((handled, acted), (True, True))
        self.assertEqual(self.status(self.task), "in_progress")
        task = self.session.get(Task, self.task.id)
        self.assertEqual(task.early_start_reason, "Site handed over a day early")
        audit = self.session.scalar(
            select(V2AuditEvent).where(V2AuditEvent.entity_id == self.task.id).order_by(V2AuditEvent.occurred_at.desc())
        )
        self.assertEqual((audit.source, audit.actor_user_id), ("telegram", self.employee[0].id))
        self.assertIsNone(self.pending())
        self.assertEqual(self.last_inbound().processing_status, "processed")

    def test_cancel_leaves_the_task_ready_and_clears_the_question(self):
        self._make_early()
        self.press(EMPLOYEE_CHAT, task_callback("st", self.task.id))

        self.assertFalse(self.press(EMPLOYEE_CHAT, task_callback("ce", self.task.id), message_id=43))

        self.assertEqual(self.status(self.task), "ready")
        self.assertIsNone(self.pending())
        self.assertIn("Early start cancelled", self.last_reply())
        # The next text is an ordinary message again, not a reason.
        self.assertEqual(self.reply(EMPLOYEE_CHAT, "hello"), (False, False))

    def test_an_expired_question_does_not_use_the_reply(self):
        self._make_early()
        self.press(EMPLOYEE_CHAT, task_callback("st", self.task.id))
        with self.session.begin():
            self.session.scalar(select(TelegramPendingInput)).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        self.assertEqual(self.reply(EMPLOYEE_CHAT, "Late reason"), (True, False))

        self.assertEqual(self.status(self.task), "ready")
        self.assertIsNone(self.session.get(Task, self.task.id).early_start_reason)
        self.assertIn("This question has expired", self.last_reply())

    def test_a_reply_the_lifecycle_refuses_leaves_the_task_unchanged(self):
        self._make_early()
        self.press(EMPLOYEE_CHAT, task_callback("st", self.task.id))
        # The assignment ends before the answer arrives.
        with self.session.begin():
            self.session.query(TaskSupportAssignment).delete()
            self.session.add(TaskSupportAssignment(
                task_id=self.task.id, project_id=self.project.id, employee_id=self.other[1].id,
                responsibility="Execution", assigned_by=self.supervisor[0].id,
            ))

        self.assertEqual(self.reply(EMPLOYEE_CHAT, "Early access"), (True, False))

        self.assertEqual(self.status(self.task), "ready")
        self.assertIsNone(self.session.get(Task, self.task.id).early_start_reason)
        self.assertIn("Couldn't start this task", self.last_reply())
        self.assertIn("only they can start or submit it", self.last_reply())

    def test_an_answer_from_a_group_chat_is_not_used(self):
        self._make_early()
        self.press(EMPLOYEE_CHAT, task_callback("st", self.task.id))
        self.assertEqual(self.reply(EMPLOYEE_CHAT, "Early access", chat_type="group"), (True, False))
        self.assertEqual(self.status(self.task), "ready")

    def test_task_and_gate_questions_are_stored_by_the_same_rules(self):
        """KTD7's constraints: a task question saves with no approval and no
        health; a gate health note without a health value is still refused."""
        from sqlalchemy.exc import IntegrityError

        self._make_early()
        self.press(EMPLOYEE_CHAT, task_callback("st", self.task.id))
        self.assertIsNotNone(self.pending())
        self.session.add(TelegramPendingInput(
            chat_id="12345", kind="gate_health_note", approval_id=uuid.uuid4(),
            expires_at=datetime.now(timezone.utc),
        ))
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()
        self.session.add(TelegramPendingInput(
            chat_id="12346", kind="task_early_start_reason", approval_id=uuid.uuid4(), task_id=self.task.id,
            expires_at=datetime.now(timezone.utc),
        ))
        with self.assertRaises(IntegrityError):
            self.session.commit()  # a task question may not also point at a gate
        self.session.rollback()

    # ---- repeat and stale buttons ---------------------------------------------------------

    def test_same_button_twice_is_already_done(self):
        data = task_callback("rd", self.task.id)
        self.assertTrue(self.press(EMPLOYEE_CHAT, data, message_id=77))
        self.assertFalse(self.press(EMPLOYEE_CHAT, data, message_id=77))
        self.assertEqual(self.calls("answerCallbackQuery")[-1]["text"], "Already done")
        self.assertEqual(self.status(self.task), "ready")

    def test_unknown_or_malformed_task_button_is_no_longer_available(self):
        for data in (task_callback("zz", self.task.id), "t1:rd:nothex", task_callback("rd", uuid.uuid4())):
            with self.subTest(data=data):
                self.assertFalse(self.press(EMPLOYEE_CHAT, data))
                self.assertIn("This button is no longer available.", self.last_reply())
        self.assertEqual(self.status(self.task), "planned")

    # ---- channel guards (KTD22) -------------------------------------------------------------

    def test_group_chat_is_refused(self):
        self.assertFalse(self.press(EMPLOYEE_CHAT, task_callback("rd", self.task.id), chat_type="group"))
        self.assertEqual(self.status(self.task), "planned")
        self.assertIn("Use the bot in a private chat", self.last_reply())

    def test_someone_else_pressing_in_the_chat_is_refused(self):
        self.assertFalse(self.press(EMPLOYEE_CHAT, task_callback("rd", self.task.id), from_id="123456"))
        self.assertEqual(self.status(self.task), "planned")
        self.assertIn("Use the bot in a private chat", self.last_reply())

    def test_employee_removed_from_the_project_is_refused(self):
        self.assertFalse(self.press(REMOVED_CHAT, task_callback("rd", self.task.id)))
        self.assertEqual(self.status(self.task), "planned")
        self.assertIn("no longer a member", self.last_reply())

    def test_deactivated_or_unlinked_person_is_refused(self):
        with self.session.begin():
            self.session.get(User, self.employee[0].id).active = False
        for chat in (EMPLOYEE_CHAT, UNLINKED_CHAT):
            with self.subTest(chat=chat):
                self.assertFalse(self.press(chat, task_callback("rd", self.task.id)))
                self.assertIn("isn't linked to SiteOps", self.last_reply())
        self.assertEqual(self.status(self.task), "planned")


if __name__ == "__main__":
    unittest.main()
