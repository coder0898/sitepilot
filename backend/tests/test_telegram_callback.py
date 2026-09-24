"""Inline-button presses for gate messages (app/services/telegram_callback.py).

Each press must run the same typed GATE* command through the shared handler
and gate services - so these tests assert on the real records the services
write (acknowledgement, status check, evidence session, decision) - and must
always give readable feedback: a toast, buttons removed after success, and a
readable message for wrong user, wrong state, duplicate press, unlinked chat
or an unknown/stale button. Reject and the health buttons first ask a
question (reason / optional note); the next text message answers it before
it can be read as a command or evidence text, and expired, cancelled or
already-answered questions are explained.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.execution_models import (
    FileObject,
    GateEvidenceSession,
    GateEvidenceSessionAttachment,
    InboundMessage,
    OutboxEvent,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalStatusCheck,
    ProjectExternalApprovalSubmission,
    ProjectExternalApprovalTask,
    ProjectGateAcknowledgement,
    Task,
    TelegramInboundUpdate,
    TelegramPendingInput,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_inbound import TelegramInboundService
from app.services.telegram_message import gate_callback
from app.template_models import V2TemplateVersion  # noqa: F401 - registers FK target for V2Project.template_version_id
from app.vendor_models import V2VendorContact


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
ASSIGNEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
OTHER_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
ADMIN_CHAT, ASSIGNEE_CHAT, OTHER_CHAT, UNLINKED_CHAT = "900", "555", "666", "999"


class _FakeResponse:
    status_code = 200
    content = b"x"

    def json(self):
        return {"ok": True, "result": {"message_id": 1}}


class TelegramCallbackTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            V2ProjectExternalGate.__table__, V2AuditEvent.__table__, ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__, ProjectExternalApprovalSubmission.__table__,
            ProjectExternalApprovalEvidence.__table__, ProjectExternalApprovalStatusCheck.__table__,
            ProjectGateAcknowledgement.__table__, GateEvidenceSession.__table__,
            GateEvidenceSessionAttachment.__table__, FileObject.__table__, Task.__table__,
            InboundMessage.__table__, TelegramInboundUpdate.__table__, OutboxEvent.__table__,
            V2VendorContact.__table__, TelegramPendingInput.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()
        self.project_id = uuid.uuid4()

        with self.session.begin():
            self.session.add_all([
                User(id=ADMIN_ID, name="Niddhi", email="admin@example.com", role=UserRole.admin, active=True),
                User(id=ASSIGNEE_ID, name="Rohan", email="rohan@example.com", role=UserRole.internal_employee, active=True),
                User(id=OTHER_ID, name="Chetan", email="chetan@example.com", role=UserRole.internal_employee, active=True),
            ])
            self.session.flush()
            admin_profile = EmployeeProfile(user_id=ADMIN_ID, employee_code="ADM", designation="Admin",
                                            availability="available", telegram_chat_id=ADMIN_CHAT)
            assignee_profile = EmployeeProfile(user_id=ASSIGNEE_ID, employee_code="E1", designation="Eng",
                                               availability="available", telegram_chat_id=ASSIGNEE_CHAT)
            other_profile = EmployeeProfile(user_id=OTHER_ID, employee_code="E2", designation="Eng",
                                            availability="available", telegram_chat_id=OTHER_CHAT)
            self.session.add_all([admin_profile, assignee_profile, other_profile])
            self.session.flush()
            self.session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="SIS Interior", client_name="Client", site_address="Mumbai",
                start_date=date(2026, 9, 1), status="active", created_by=ADMIN_ID,
            ))
            self.session.flush()
            for profile in (assignee_profile, other_profile):
                self.session.add(V2ProjectMembership(
                    project_id=self.project_id, employee_id=profile.id, project_role="internal_employee",
                    assigned_by=ADMIN_ID, assignment_reason="test",
                ))
            gate = V2ProjectExternalGate(
                id=uuid.uuid4(), project_id=self.project_id, original_code="E001", template_sequence=1,
                approval_name="Fire NOC", mapping_classification="exact", applicability_state="applicable",
                blocking=True, accountable_pm_user_id=ADMIN_ID, source_type="project_manual",
            )
            self.session.add(gate)
            self.session.flush()
            self.approval = ProjectExternalApproval(
                id=uuid.uuid4(), project_id=self.project_id, project_gate_id=gate.id,
                status="assigned", assigned_to_user_id=ASSIGNEE_ID, assigned_by=ADMIN_ID,
            )
            self.session.add(self.approval)

        self._original_token = settings.telegram_access_token
        settings.telegram_access_token = "test-token"
        self._http_patch = patch("app.services.telegram_provider.httpx.post", return_value=_FakeResponse())
        self.mock_post = self._http_patch.start()
        self.update_id = 5000

    def tearDown(self):
        self._http_patch.stop()
        settings.telegram_access_token = self._original_token
        self.session.close()

    # ---- helpers ----------------------------------------------------------------

    def press(self, chat_id: str, data: str, message_id: int = 42) -> bool:
        """Simulates the webhook: store the raw update, then hand it over."""
        self.update_id += 1
        self.session.add(TelegramInboundUpdate(
            update_id=self.update_id, chat_id=chat_id, callback_data=data,
            raw_payload={"callback_query": {"id": f"cb{self.update_id}", "data": data,
                                            "message": {"chat": {"id": chat_id}, "message_id": message_id}}},
        ))
        self.session.commit()
        return TelegramCallbackService(self.session).handle(
            update_id=self.update_id, chat_id=chat_id, message_id=message_id,
            callback_query_id=f"cb{self.update_id}", data=data,
        )

    def calls(self, method: str) -> list[dict]:
        return [c.kwargs["json"] for c in self.mock_post.call_args_list if c.args[0].endswith(f"/{method}")]

    def cb(self, code: str, arg: str | None = None) -> str:
        return gate_callback(code, self.approval.id, arg)

    def set_status(self, status: str) -> None:
        with self.session.begin():
            self.session.get(ProjectExternalApproval, self.approval.id).status = status

    def send_text(self, chat_id: str, text: str) -> tuple[bool, bool]:
        """Simulates the webhook's text path: pending question first,
        otherwise a normal command."""
        self.update_id += 1
        handled, acted = TelegramCallbackService(self.session).handle_text(
            update_id=self.update_id, chat_id=chat_id, text=text,
        )
        if not handled:
            TelegramInboundService(self.session).process(self.update_id, chat_id, text)
        return handled, acted

    def expire_pending(self, minutes_ago: int) -> None:
        with self.session.begin():
            pending = self.session.query(TelegramPendingInput).one()
            pending.expires_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)

    def last_inbound(self) -> InboundMessage:
        return self.session.query(InboundMessage).order_by(InboundMessage.created_at.desc()).first()

    # ---- success paths: same command, same services -------------------------------

    def test_acknowledge_button_runs_gateaccept_and_removes_buttons(self):
        acted = self.press(ASSIGNEE_CHAT, self.cb("ac"))

        self.assertTrue(acted)
        self.assertEqual(self.session.query(ProjectGateAcknowledgement).one().response, "accepted")
        self.assertEqual(self.last_inbound().raw_body, f"GATEACCEPT {self.approval.id.hex[:8]}")
        self.assertEqual(self.calls("answerCallbackQuery")[0]["text"], "Acknowledged")
        removed = self.calls("editMessageReplyMarkup")
        self.assertEqual(removed[0]["message_id"], 42)
        self.assertEqual(removed[0]["reply_markup"], {"inline_keyboard": []})
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "assigned")

    def test_decline_button_records_decline(self):
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("dc")))
        self.assertEqual(self.session.query(ProjectGateAcknowledgement).one().response, "declined")

    def test_health_button_asks_for_a_note_before_recording(self):
        self.assertFalse(self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked")))

        self.assertEqual(self.session.query(ProjectExternalApprovalStatusCheck).count(), 0)  # not yet
        pending = self.session.query(TelegramPendingInput).one()
        self.assertEqual((pending.kind, pending.health), ("gate_health_note", "blocked"))
        prompt = self.calls("sendMessage")[0]
        self.assertIn("<b>Status: Blocked</b>", prompt["text"])
        self.assertIn("Add a short note?", prompt["text"])
        self.assertEqual(
            prompt["reply_markup"]["inline_keyboard"],
            [[{"text": "Skip note", "callback_data": f"g1:sk:{self.approval.id.hex}"}]],
        )

    def test_health_note_typed_answer_records_status_with_note(self):
        self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked"))
        handled, acted = self.send_text(ASSIGNEE_CHAT, "Waiting for fire\ninspection date")

        self.assertEqual((handled, acted), (True, True))
        check = self.session.query(ProjectExternalApprovalStatusCheck).one()
        self.assertEqual((check.health, check.note), ("blocked", "Waiting for fire inspection date"))
        self.assertEqual(self.session.query(TelegramPendingInput).count(), 0)
        self.assertEqual(self.calls("editMessageReplyMarkup")[-1]["message_id"], 1)  # Skip removed from prompt
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "assigned")

    def test_skip_note_records_status_without_note(self):
        self.press(ASSIGNEE_CHAT, self.cb("hs", "need_help"))
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("sk"), message_id=1))
        check = self.session.query(ProjectExternalApprovalStatusCheck).one()
        self.assertEqual((check.health, check.note), ("need_help", None))

    def test_skip_twice_says_already_answered(self):
        self.press(ASSIGNEE_CHAT, self.cb("hs", "on_track"))
        self.press(ASSIGNEE_CHAT, self.cb("sk"), message_id=1)
        self.mock_post.reset_mock()
        self.assertFalse(self.press(ASSIGNEE_CHAT, self.cb("sk"), message_id=1))
        self.assertIn("expired or was already answered", self.calls("sendMessage")[0]["text"])
        self.assertEqual(self.session.query(ProjectExternalApprovalStatusCheck).count(), 1)

    def test_note_is_taken_before_evidence_session_text(self):
        # With an evidence session open, a health note must still go to the
        # question, not into the evidence.
        self.press(ASSIGNEE_CHAT, self.cb("op"))
        self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked"), message_id=60)
        self.send_text(ASSIGNEE_CHAT, "Inspector on leave")
        self.assertEqual(self.session.query(ProjectExternalApprovalStatusCheck).one().note, "Inspector on leave")
        self.assertIsNone(self.session.query(GateEvidenceSession).one().note)

    def test_text_with_no_question_is_processed_normally(self):
        handled, _ = self.send_text(ASSIGNEE_CHAT, f"GATEACCEPT {self.approval.id.hex[:8]}")
        self.assertFalse(handled)
        self.assertEqual(self.session.query(ProjectGateAcknowledgement).one().response, "accepted")

    def test_expired_question_does_not_use_the_answer(self):
        self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked"))
        self.expire_pending(minutes_ago=5)
        self.mock_post.reset_mock()

        handled, acted = self.send_text(ASSIGNEE_CHAT, "late note")

        self.assertEqual((handled, acted), (True, False))
        self.assertEqual(self.session.query(ProjectExternalApprovalStatusCheck).count(), 0)
        self.assertIn("This question has expired", self.calls("sendMessage")[0]["text"])
        self.assertEqual(self.session.query(TelegramPendingInput).count(), 0)

    def test_long_expired_question_is_dropped_and_message_processed_normally(self):
        self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked"))
        self.expire_pending(minutes_ago=60 * 48)
        handled, _ = self.send_text(ASSIGNEE_CHAT, f"GATEACCEPT {self.approval.id.hex[:8]}")
        self.assertFalse(handled)
        self.assertEqual(self.session.query(ProjectGateAcknowledgement).count(), 1)

    def test_submit_evidence_button_opens_the_existing_evidence_session(self):
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("op")))
        self.assertEqual(self.session.query(GateEvidenceSession).one().approval_id, self.approval.id)

    def test_submit_for_review_button_submits_the_open_session(self):
        self.press(ASSIGNEE_CHAT, self.cb("op"))
        TelegramInboundService(self.session).process(7000, ASSIGNEE_CHAT, "NOC applied, receipt FD-1234")

        self.assertTrue(self.press(ASSIGNEE_CHAT, gate_callback("cl"), message_id=43))

        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "submitted")
        self.assertEqual(self.session.query(ProjectExternalApprovalSubmission).one().note, "NOC applied, receipt FD-1234")

    def test_admin_approve_button_decides_a_submitted_gate(self):
        self.set_status("submitted")
        self.assertTrue(self.press(ADMIN_CHAT, self.cb("ap")))
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "approved")

    # ---- reject: reason question ---------------------------------------------------

    def test_reject_button_asks_for_a_reason_and_changes_nothing_yet(self):
        self.set_status("submitted")

        self.assertFalse(self.press(ADMIN_CHAT, self.cb("rj")))

        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "submitted")
        prompt = self.calls("sendMessage")[0]
        self.assertIn("<b>Reject Fire NOC</b>", prompt["text"])
        self.assertIn("Please enter the rejection reason for Fire NOC.", prompt["text"])
        self.assertEqual(
            prompt["reply_markup"]["inline_keyboard"],
            [[{"text": "Cancel", "callback_data": f"g1:cn:{self.approval.id.hex}"}]],
        )
        self.assertEqual(self.calls("answerCallbackQuery")[0]["text"], "Reason needed")
        self.assertEqual(self.session.query(TelegramPendingInput).one().kind, "gate_reject_reason")
        self.assertEqual(self.session.query(InboundMessage).count(), 0)  # no command ran

    def test_reject_reason_answer_runs_the_existing_reject(self):
        self.set_status("submitted")
        self.press(ADMIN_CHAT, self.cb("rj"))

        handled, acted = self.send_text(ADMIN_CHAT, "Updated NOC copy required.")

        self.assertEqual((handled, acted), (True, True))
        approval = self.session.get(ProjectExternalApproval, self.approval.id)
        # decide()'s reject loops the gate back to the assignee with the reason kept.
        self.assertEqual(approval.status, "assigned")
        self.assertEqual(approval.rejection_reason, "Updated NOC copy required.")
        self.assertEqual(self.last_inbound().raw_body, f"GATEDECIDE {self.approval.id.hex[:8]} REJECT Updated NOC copy required.")

    def test_cancel_withdraws_the_reject_question(self):
        self.set_status("submitted")
        self.press(ADMIN_CHAT, self.cb("rj"))
        self.mock_post.reset_mock()

        self.assertFalse(self.press(ADMIN_CHAT, self.cb("cn"), message_id=1))

        self.assertEqual(self.session.query(TelegramPendingInput).count(), 0)
        self.assertIn("Rejection cancelled", self.calls("sendMessage")[0]["text"])
        # The next text is an ordinary message again, not a reason.
        handled, _ = self.send_text(ADMIN_CHAT, "some text")
        self.assertFalse(handled)
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "submitted")

    def test_reject_reason_after_gate_already_decided_is_explained(self):
        self.set_status("submitted")
        self.press(ADMIN_CHAT, self.cb("rj"))
        self.press(ADMIN_CHAT, self.cb("ap"), message_id=70)  # approved meanwhile
        self.mock_post.reset_mock()

        handled, acted = self.send_text(ADMIN_CHAT, "Too late reason")

        self.assertEqual((handled, acted), (True, False))
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "approved")
        self.assertIn("Couldn't reject this approval", self.calls("sendMessage")[0]["text"])

    def test_non_admin_reason_is_refused_readably(self):
        self.set_status("submitted")
        self.press(ASSIGNEE_CHAT, self.cb("rj"))
        self.mock_post.reset_mock()
        self.send_text(ASSIGNEE_CHAT, "not my call")
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "submitted")
        self.assertIn("not available for your role", self.calls("sendMessage")[0]["text"])

    def test_asking_again_replaces_the_earlier_question(self):
        self.set_status("submitted")
        self.press(ADMIN_CHAT, self.cb("rj"))
        self.press(ADMIN_CHAT, self.cb("rj"), message_id=43)
        self.assertEqual(self.session.query(TelegramPendingInput).count(), 1)

    def test_skip_on_an_old_prompt_leaves_the_current_question_alone(self):
        self.set_status("submitted")
        self.press(ADMIN_CHAT, self.cb("rj"))  # current question: reject reason
        self.mock_post.reset_mock()
        self.assertFalse(self.press(ADMIN_CHAT, self.cb("sk"), message_id=9))
        self.assertIn("expired or was already answered", self.calls("sendMessage")[0]["text"])
        self.assertEqual(self.session.query(TelegramPendingInput).one().kind, "gate_reject_reason")

    def test_reject_button_on_already_decided_gate_is_explained(self):
        with self.session.begin():
            approval = self.session.get(ProjectExternalApproval, self.approval.id)
            approval.status, approval.decided_by, approval.decided_at = "approved", ADMIN_ID, datetime.now(timezone.utc)
        self.assertFalse(self.press(ADMIN_CHAT, self.cb("rj")))
        self.assertIn("no longer awaiting a decision (current status: approved)", self.calls("sendMessage")[0]["text"])

    def test_reject_button_from_unlinked_chat(self):
        self.set_status("submitted")
        self.assertFalse(self.press(UNLINKED_CHAT, self.cb("rj")))
        self.assertIn("isn't linked to SiteOps", self.calls("sendMessage")[0]["text"])

    # ---- readable failures ----------------------------------------------------------

    def test_wrong_user_gets_readable_reason_and_nothing_is_recorded(self):
        acted = self.press(OTHER_CHAT, self.cb("ac"))

        self.assertFalse(acted)
        self.assertEqual(self.session.query(ProjectGateAcknowledgement).count(), 0)
        reply = self.calls("sendMessage")[0]
        self.assertEqual(reply["parse_mode"], "HTML")
        self.assertIn("<b>Couldn't acknowledge this approval</b>", reply["text"])
        self.assertIn("assigned to", reply["text"])
        self.assertEqual(self.calls("editMessageReplyMarkup"), [])  # left in place

    def test_non_admin_approve_is_refused_readably(self):
        self.set_status("submitted")
        self.assertFalse(self.press(ASSIGNEE_CHAT, self.cb("ap")))
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "submitted")
        self.assertIn("not available for your role", self.calls("sendMessage")[0]["text"])

    def test_invalid_gate_state_is_explained(self):
        # Approve on a gate that isn't submitted: the decision service refuses.
        self.assertFalse(self.press(ADMIN_CHAT, self.cb("ap")))
        self.assertIn("Couldn't approve this approval", self.calls("sendMessage")[0]["text"])

    def test_stale_button_after_reassignment_is_explained(self):
        with self.session.begin():
            self.session.get(ProjectExternalApproval, self.approval.id).assigned_to_user_id = OTHER_ID
        self.assertFalse(self.press(ASSIGNEE_CHAT, self.cb("op")))
        self.assertEqual(self.session.query(GateEvidenceSession).count(), 0)
        self.assertIn("Couldn't start an evidence submission", self.calls("sendMessage")[0]["text"])

    def test_health_note_after_reassignment_is_refused_readably(self):
        self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked"))
        with self.session.begin():
            self.session.get(ProjectExternalApproval, self.approval.id).assigned_to_user_id = OTHER_ID
        self.mock_post.reset_mock()
        self.send_text(ASSIGNEE_CHAT, "note")
        self.assertEqual(self.session.query(ProjectExternalApprovalStatusCheck).count(), 0)
        self.assertIn("Couldn't update the status", self.calls("sendMessage")[0]["text"])

    def test_empty_evidence_submission_is_explained(self):
        self.press(ASSIGNEE_CHAT, self.cb("op"))
        self.mock_post.reset_mock()
        self.assertFalse(self.press(ASSIGNEE_CHAT, gate_callback("cl"), message_id=43))
        self.assertIn("This evidence session is empty", self.calls("sendMessage")[0]["text"])

    def test_duplicate_press_on_same_message_is_already_done(self):
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("ac")))
        self.mock_post.reset_mock()

        self.assertFalse(self.press(ASSIGNEE_CHAT, self.cb("ac")))

        self.assertEqual(self.session.query(ProjectGateAcknowledgement).count(), 1)
        self.assertEqual(self.calls("answerCallbackQuery")[0]["text"], "Already done")
        self.assertEqual(len(self.calls("editMessageReplyMarkup")), 1)

    def test_same_button_on_a_different_message_still_runs(self):
        # e.g. Acknowledge on a reassignment message after acknowledging an
        # older one - a legitimate new action, not a duplicate press.
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("ac"), message_id=42))
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("ac"), message_id=50))
        self.assertEqual(self.session.query(ProjectGateAcknowledgement).count(), 2)

    def test_unlinked_chat_is_told_to_reconnect(self):
        self.assertFalse(self.press(UNLINKED_CHAT, self.cb("ac")))
        self.assertIn("isn't linked to SiteOps", self.calls("sendMessage")[0]["text"])

    def test_unknown_or_malformed_button_is_stale(self):
        for data in ("g1:zz:" + "a" * 32, "g1:ac", "g1:hs:" + "a" * 32, "accept", ""):
            with self.subTest(data=data):
                self.mock_post.reset_mock()
                self.assertFalse(self.press(ASSIGNEE_CHAT, data))
                self.assertIn("no longer available", self.calls("sendMessage")[0]["text"])
        self.assertEqual(self.session.query(InboundMessage).count(), 0)  # nothing ran

    def test_typed_commands_still_work_alongside_buttons(self):
        ref = self.approval.id.hex[:8]
        TelegramInboundService(self.session).process(9001, ASSIGNEE_CHAT, f"GATEACCEPT {ref}")
        TelegramInboundService(self.session).process(9002, ASSIGNEE_CHAT, f"GATESTATUS {ref} blocked")
        self.assertEqual(self.session.query(ProjectGateAcknowledgement).one().response, "accepted")
        self.assertEqual(self.session.query(ProjectExternalApprovalStatusCheck).one().health, "blocked")


if __name__ == "__main__":
    unittest.main()
