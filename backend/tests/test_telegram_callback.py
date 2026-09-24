"""Inline-button presses for gate messages (app/services/telegram_callback.py).

Each press must run the same typed GATE* command through the shared handler
and gate services - so these tests assert on the real records the services
write (acknowledgement, status check, evidence session, decision) - and must
always give readable feedback: a toast, buttons removed after success, and a
readable message for wrong user, wrong state, duplicate press, unlinked chat
or an unknown/stale button. Reject changes nothing until the reason prompt
exists; it only replies with the ready-to-send command.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone
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
            V2VendorContact.__table__,
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

    def test_each_health_button_records_a_status_check_only(self):
        for index, health in enumerate(("on_track", "blocked", "need_help")):
            with self.subTest(health=health):
                self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("hs", health), message_id=100 + index))
        healths = [c.health for c in self.session.query(ProjectExternalApprovalStatusCheck).all()]
        self.assertCountEqual(healths, ["on_track", "blocked", "need_help"])
        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "assigned")

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

    # ---- reject (instructions only until the reason prompt exists) ---------------

    def test_reject_button_on_submitted_gate_gives_the_command_and_changes_nothing(self):
        self.set_status("submitted")

        self.assertFalse(self.press(ADMIN_CHAT, self.cb("rj")))

        self.assertEqual(self.session.get(ProjectExternalApproval, self.approval.id).status, "submitted")
        reply = self.calls("sendMessage")[0]["text"]
        self.assertIn("<b>Reject Fire NOC</b>", reply)
        self.assertIn(f"<code>GATEDECIDE {self.approval.id.hex[:8]} REJECT your reason</code>", reply)
        self.assertEqual(self.calls("answerCallbackQuery")[0]["text"], "Reason needed")
        self.assertEqual(self.calls("editMessageReplyMarkup"), [])  # Approve/Reject stay usable
        self.assertEqual(self.session.query(InboundMessage).count(), 0)  # no command ran

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
        self.assertFalse(self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked")))
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
        # e.g. Blocked pressed on the reminder after pressing it on an older
        # status message - a legitimate new status check, not a duplicate.
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked"), message_id=42))
        self.assertTrue(self.press(ASSIGNEE_CHAT, self.cb("hs", "blocked"), message_id=50))
        self.assertEqual(self.session.query(ProjectExternalApprovalStatusCheck).count(), 2)

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
