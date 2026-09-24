"""Readable, recipient-specific Telegram templates for external-approval gate
events (app/services/telegram_gate_render.py, via telegram_render).

Verifies: the responsible employee gets the actionable copy and Admins get an
FYI copy; the previous assignee on reassign/unassign gets the "responsibility
removed" copy; every template is HTML-safe; and no user-facing text leaks a
UUID, an internal event name, or a raw payload key.
"""

from __future__ import annotations

import re
import unittest
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import (
    FileObject,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectExternalGate
from app.services.telegram_gate_render import GATE_RENDERERS
from app.services.telegram_render import render_telegram, render_telegram_message


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RAW_KEYS = (
    "approval_id", "project_id", "assigned_to_user_id", "previous_assignee_id", "submission_id",
    "decided_by", "project_external_approval", "gate_confirmation", "None",
)


class TelegramGateRenderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectExternalGate.__table__,
            ProjectExternalApproval.__table__, ProjectExternalApprovalSubmission.__table__,
            FileObject.__table__, ProjectExternalApprovalEvidence.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()

        with self.db.begin():
            self.admin = User(id=uuid.uuid4(), name="Niddhi", email="admin@example.com", role=UserRole.admin, active=True)
            self.employee = User(id=uuid.uuid4(), name="Rohan Kumar", email="rohan@example.com", role=UserRole.internal_employee, active=True)
            self.new_employee = User(id=uuid.uuid4(), name="Chetan", email="chetan@example.com", role=UserRole.internal_employee, active=True)
            self.db.add_all([self.admin, self.employee, self.new_employee])
            self.db.flush()
            self.admin_profile = EmployeeProfile(user_id=self.admin.id, employee_code="ADM", designation="Admin", availability="available")
            self.employee_profile = EmployeeProfile(user_id=self.employee.id, employee_code="EMP1", designation="Engineer", availability="available")
            self.new_employee_profile = EmployeeProfile(user_id=self.new_employee.id, employee_code="EMP2", designation="Engineer", availability="available")
            self.db.add_all([self.admin_profile, self.employee_profile, self.new_employee_profile])

            self.project = V2Project(
                code="PRJ-1", name="SIS Interior", client_name="Client", site_address="Site",
                start_date=date(2026, 9, 21), status="active", created_by=self.admin.id,
            )
            self.db.add(self.project)
            self.db.flush()
            self.gate = V2ProjectExternalGate(
                project_id=self.project.id, original_code="G-01", template_sequence=1,
                approval_name="Fire NOC & Society", mapping_classification="unmapped", source_type="project_manual",
                accountable_pm_user_id=self.admin.id,
            )
            self.db.add(self.gate)
            self.db.flush()
            self.approval = ProjectExternalApproval(
                project_id=self.project.id, project_gate_id=self.gate.id,
                status="assigned", assigned_to_user_id=self.employee.id, due_at=date(2026, 10, 5),
            )
            self.db.add(self.approval)
            self.db.flush()
            self.submission = ProjectExternalApprovalSubmission(
                approval_id=self.approval.id, submitted_by=self.employee.id, note="NOC copy attached",
                submitted_at=datetime(2026, 9, 24, 9, 30, tzinfo=timezone.utc),
            )
            self.db.add(self.submission)
            self.db.flush()
            for mime in ("image/jpeg", "application/pdf"):
                file_object = FileObject(
                    storage_key=f"k-{mime}", original_filename="f", mime_type=mime, size_bytes=1,
                    checksum="x", uploaded_by=self.employee.id,
                )
                self.db.add(file_object)
                self.db.flush()
                self.db.add(ProjectExternalApprovalEvidence(submission_id=self.submission.id, file_id=file_object.id))

        self.ref = str(self.approval.id).replace("-", "")[:8]

    def tearDown(self):
        self.db.close()

    def payload(self, **extra):
        return {"approval_id": str(self.approval.id), "project_id": str(self.project.id), **extra}

    def render(self, event_type, payload, profile):
        return render_telegram(self.db, event_type, payload, profile.id if profile else None)

    def assert_clean(self, text):
        self.assertIsNone(UUID_PATTERN.search(text), text)
        for key in RAW_KEYS:
            self.assertNotIn(key, text)

    # ---- assignment -------------------------------------------------------

    def test_assigned_employee_gets_acknowledge_and_decline(self):
        message = self.render(
            "project_external_approval.assigned",
            self.payload(gate_name="Fire NOC & Society", project_name="SIS Interior", due_date="2026-10-05",
                         assigned_to_user_id=str(self.employee.id)),
            self.employee_profile,
        )
        self.assertEqual(message.parse_mode, "HTML")
        self.assertIn("<b>External Approval Assigned</b>", message.text)
        self.assertIn("Fire NOC &amp; Society", message.text)  # escaped
        self.assertIn("Due: 5 Oct 2026", message.text)
        self.assertIn("This may take time depending on the external authority.", message.text)
        commands = [a.command for row in message.actions for a in row]
        self.assertEqual(commands, [f"GATEACCEPT {self.ref}", f"GATEDECLINE {self.ref}"])
        self.assert_clean(message.text)

    def test_assigned_admin_copy_is_fyi_without_actions(self):
        message = self.render(
            "project_external_approval.assigned",
            self.payload(assigned_to_user_id=str(self.employee.id), due_date="No due date set"),
            self.admin_profile,
        )
        self.assertIn("Assigned to: Rohan Kumar", message.text)
        self.assertIn("Due: No due date set", message.text)
        self.assertIn("No action required.", message.text)
        self.assertEqual(message.actions, ())
        self.assert_clean(message.text)

    def test_reassigned_three_recipients_get_three_copies(self):
        payload = self.payload(
            assigned_to_user_id=str(self.new_employee.id), previous_assignee_id=str(self.employee.id),
        )
        new_copy = self.render("project_external_approval.reassigned", payload, self.new_employee_profile)
        previous_copy = self.render("project_external_approval.reassigned", payload, self.employee_profile)
        admin_copy = self.render("project_external_approval.reassigned", payload, self.admin_profile)

        self.assertIn("External Approval Assigned", new_copy.text)
        self.assertTrue(new_copy.actions)
        self.assertIn("External Approval Responsibility Removed", previous_copy.text)
        self.assertIn("You are no longer responsible for this approval.", previous_copy.text)
        self.assertEqual(previous_copy.actions, ())
        self.assertIn("From: Rohan Kumar", admin_copy.text)
        self.assertIn("To: Chetan", admin_copy.text)
        for m in (new_copy, previous_copy, admin_copy):
            self.assert_clean(m.text)

    def test_unassigned_previous_assignee_and_admin(self):
        payload = self.payload(previous_assignee_id=str(self.employee.id))
        previous_copy = self.render("project_external_approval.unassigned", payload, self.employee_profile)
        admin_copy = self.render("project_external_approval.unassigned", payload, self.admin_profile)
        self.assertIn("Responsibility Removed", previous_copy.text)
        self.assertIn("Previously assigned to: Rohan Kumar", admin_copy.text)
        self.assertIn("Web App", admin_copy.text)

    # ---- acknowledgement / health -------------------------------------------

    def test_accepted_employee_gets_progress_options(self):
        message = self.render("project_external_approval.accepted", self.payload(response="accepted"), self.employee_profile)
        self.assertIn("Approval Acknowledged", message.text)
        self.assertIn("Responsibility has been acknowledged.", message.text)
        commands = [a.command for row in message.actions for a in row]
        self.assertIn(f"GATESTATUS {self.ref} on_track", commands)
        self.assertIn(f"GATESTATUS {self.ref} blocked", commands)
        self.assertIn(f"GATESTATUS {self.ref} need_help", commands)
        self.assertIn(f"GATEOPEN {self.ref}", commands)
        admin_copy = self.render("project_external_approval.accepted", self.payload(response="accepted"), self.admin_profile)
        self.assertIn("Acknowledged by: Rohan Kumar", admin_copy.text)
        self.assertEqual(admin_copy.actions, ())

    def test_declined_employee_and_admin(self):
        employee_copy = self.render("project_external_approval.declined", self.payload(note="On leave"), self.employee_profile)
        admin_copy = self.render("project_external_approval.declined", self.payload(note="On leave"), self.admin_profile)
        self.assertIn("Your decline has been recorded.", employee_copy.text)
        self.assertIn("No further Telegram action required.", employee_copy.text)
        self.assertEqual(employee_copy.actions, ())
        self.assertIn("Declined by: Rohan Kumar", admin_copy.text)
        self.assertIn("Note: On leave", admin_copy.text)

    def test_status_checked_says_progress_only(self):
        payload = self.payload(health="blocked", note="Waiting for <inspection> date")
        employee_copy = self.render("project_external_approval.status_checked", payload, self.employee_profile)
        self.assertIn("<b>Status Updated</b>", employee_copy.text)
        self.assertIn("Status: Blocked", employee_copy.text)
        self.assertIn("Note: Waiting for &lt;inspection&gt; date", employee_copy.text)
        self.assertIn("The approval has not been submitted for Admin decision.", employee_copy.text)
        self.assertTrue(employee_copy.actions)
        admin_copy = self.render("project_external_approval.status_checked", payload, self.admin_profile)
        self.assertIn("From: Rohan Kumar", admin_copy.text)
        self.assertEqual(admin_copy.actions, ())

    # ---- submission / decision -------------------------------------------------

    def test_submitted_employee_sees_item_count(self):
        payload = self.payload(submission_id=str(self.submission.id), submitted_by=str(self.employee.id))
        message = self.render("project_external_approval.submitted", payload, self.employee_profile)
        self.assertIn("Submitted for Review", message.text)
        self.assertIn("Submitted items: 3", message.text)  # photo + PDF + note
        self.assertEqual(message.actions, ())
        self.assert_clean(message.text)

    def test_submitted_admin_gets_review_message_with_decision_actions(self):
        payload = self.payload(submission_id=str(self.submission.id), submitted_by=str(self.employee.id))
        message = self.render("project_external_approval.submitted", payload, self.admin_profile)
        self.assertIn("External Approval Ready for Review", message.text)
        self.assertIn("Submitted by: Rohan Kumar", message.text)
        self.assertIn("Submitted: 24 Sep 2026, 3:00 PM IST", message.text)
        self.assertIn("Evidence: 1 photo, 1 PDF, note", message.text)
        commands = [a.command for row in message.actions for a in row]
        self.assertEqual(commands, [f"GATEDECIDE {self.ref} APPROVE", f"GATEDECIDE {self.ref} REJECT <reason>"])
        self.assert_clean(message.text)

    def test_decided_approved(self):
        payload = self.payload(decision="approved", reason=None, decided_by=str(self.admin.id))
        employee_copy = self.render("project_external_approval.decided", payload, self.employee_profile)
        self.assertIn("External Approval Approved", employee_copy.text)
        self.assertIn("Approved by: Niddhi", employee_copy.text)
        self.assertIn("The approval is complete.", employee_copy.text)
        self.assertEqual(employee_copy.actions, ())

    def test_decided_rejected_shows_reason_and_resubmit(self):
        payload = self.payload(decision="rejected", reason="Updated NOC copy required.", decided_by=str(self.admin.id))
        employee_copy = self.render("project_external_approval.decided", payload, self.employee_profile)
        self.assertIn("External Approval Rejected", employee_copy.text)
        self.assertIn("Reason: Updated NOC copy required.", employee_copy.text)
        self.assertIn("submit the updated evidence again", employee_copy.text)
        commands = [a.command for row in employee_copy.actions for a in row]
        self.assertIn(f"GATEOPEN {self.ref}", commands)
        admin_copy = self.render("project_external_approval.decided", payload, self.admin_profile)
        self.assertIn("Returned to Rohan Kumar for correction", admin_copy.text)
        self.assertEqual(admin_copy.actions, ())
        self.assert_clean(employee_copy.text)
        self.assert_clean(admin_copy.text)

    # ---- reminders ---------------------------------------------------------------

    def test_due_reminder_and_overdue(self):
        payload = self.payload(assigned_to_user_id=str(self.employee.id), due_at="2026-10-05")
        reminder = self.render("project_external_approval.due_reminder", payload, self.employee_profile)
        self.assertIn("Due Tomorrow", reminder.text)
        self.assertIn("Please update the status if anything has changed.", reminder.text)
        overdue = self.render("project_external_approval.followup_required", payload, self.employee_profile)
        self.assertIn("External Approval Overdue", overdue.text)
        self.assertIn("This approval has not yet been submitted.", overdue.text)
        overdue_commands = [a.command for row in overdue.actions for a in row]
        self.assertNotIn(f"GATESTATUS {self.ref} on_track", overdue_commands)
        escalation_admin = self.render("project_external_approval.escalated_to_admin", payload, self.admin_profile)
        self.assertIn("Escalation", escalation_admin.text)
        self.assertIn("Assigned to: Rohan Kumar", escalation_admin.text)

    # ---- confirmations / fallback / robustness --------------------------------------

    def test_session_opened_confirmation(self):
        message = self.render("gate_confirmation.session_opened", self.payload(gate_name="Fire NOC", project_name="SIS Interior"), self.employee_profile)
        self.assertIn("Submit Evidence", message.text)
        self.assertEqual([a.command for row in message.actions for a in row], ["GATECLOSE"])

    def test_typed_fallback_lists_commands_until_buttons_exist(self):
        text = render_telegram_message(
            self.db, "project_external_approval.assigned",
            self.payload(assigned_to_user_id=str(self.employee.id)), self.employee_profile.id,
        )
        self.assertIn("<b>Reply with:</b>", text)
        self.assertIn(f"<code>GATEACCEPT {self.ref}</code> - Acknowledge", text)

    def test_every_gate_event_renders_clean_for_every_recipient_and_empty_payload(self):
        full_payload = self.payload(
            assigned_to_user_id=str(self.employee.id), previous_assignee_id=str(self.new_employee.id),
            submission_id=str(self.submission.id), submitted_by=str(self.employee.id),
            decision="rejected", reason="Fix it", decided_by=str(self.admin.id), health="on_track",
            due_at="2026-10-05",
        )
        for event_type in GATE_RENDERERS:
            for profile in (self.employee_profile, self.new_employee_profile, self.admin_profile, None):
                with self.subTest(event_type=event_type, profile=profile and profile.employee_code):
                    message = self.render(event_type, full_payload, profile)
                    self.assertEqual(message.parse_mode, "HTML")
                    self.assert_clean(message.text_with_typed_fallback())
                    empty = self.render(event_type, {}, profile)
                    self.assertTrue(empty.text)

    def test_non_gate_events_keep_plain_text(self):
        message = render_telegram(self.db, "task.blocker_created", {"type": "material"}, None)
        self.assertIsNone(message.parse_mode)
        self.assertIn("type: material", message.text)


if __name__ == "__main__":
    unittest.main()
