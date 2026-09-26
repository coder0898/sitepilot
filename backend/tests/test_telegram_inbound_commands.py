"""U14 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD7): every WhatsApp inbound command has a working Telegram equivalent,
via `TelegramInboundService` reusing `InboundMessageService`'s shared
dispatch rather than duplicating it.

Full valid-state coverage (proving the new channel-parameterization
actually works end to end) is given for vendor ACCEPT/DECLINE/CLARIFY and
employee STATUS - the two places `inbound_message.py` used to hardcode
"whatsapp". The six GATE* commands have zero channel-specific code (never
did, before or after this unit) - `test_inbound_message_matching_v2.py`'s
existing 1680-line suite already proves their business logic exhaustively
via WhatsApp, unchanged by this unit. What's genuinely new for them is
"does a Telegram-matched identity reach the same handler method", proven
here by confirming dispatch reaches each gate handler's own ref-resolution
rejection path (a distinguishable outcome from "unmatched"/"unrecognized
command", which would mean dispatch never got that far) - not a full
re-proof of gate business rules WhatsApp's suite already covers.

The plan's own Verification field ("send a real Telegram message... before
moving to the next command") could not be performed here - there is no
live bot session in this environment. This automated coverage is the
substitute; a real end-to-end check with the actual bot remains a manual
step.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, timedelta

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import (
    GateEvidenceSession,
    InboundMessage,
    ProjectExternalApproval,
    ProjectGateAcknowledgement,
    OutboxEvent,
    Task,
    TaskDependency,
    TaskSupportAssignment,
    TelegramInboundUpdate,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.telegram_inbound import TelegramInboundService
from app.template_models import V2TemplateVersion  # noqa: F401 - registers FK target for V2Project.template_version_id
from app.vendor_models import TaskVendorAssignment, V2Vendor, V2VendorContact, VendorAcknowledgement

PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_USER_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
UNKNOWN_CHAT_ID = "999999"


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TelegramInboundCommandsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # V2ProjectExternalGate's broad_mapping_text CHECK constraint
            # calls btrim() (a Postgres-ism) - SQLite has no such builtin.
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            V2ProjectExternalGate.__table__, V2AuditEvent.__table__, ProjectExternalApproval.__table__,
            Task.__table__, V2Vendor.__table__, V2VendorContact.__table__, TaskVendorAssignment.__table__,
            VendorAcknowledgement.__table__, InboundMessage.__table__, TelegramInboundUpdate.__table__,
            TaskSupportAssignment.__table__, TaskDependency.__table__, OutboxEvent.__table__,
            GateEvidenceSession.__table__, ProjectGateAcknowledgement.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()
        self.project_id = uuid.uuid4()

        with self.session.begin():
            self.session.add(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))
            self.session.add(User(id=SUPERVISOR_USER_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True))
            self.session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            self.session.flush()
            pm_profile = EmployeeProfile(user_id=PM_ID, employee_code="EMP-PM", designation="PM", availability="available")
            self.supervisor_profile = EmployeeProfile(
                user_id=SUPERVISOR_USER_ID, employee_code="EMP-SUP", designation="Supervisor",
                availability="available", telegram_chat_id="555",
            )
            admin_profile = EmployeeProfile(user_id=ADMIN_ID, employee_code="EMP-ADM", designation="Admin", availability="available")
            self.session.add_all([pm_profile, self.supervisor_profile, admin_profile])
            self.session.flush()

            self.session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Test Project", client_name="Client", site_address="Mumbai",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))
            self.session.flush()
            self.session.add_all([
                V2ProjectMembership(
                    project_id=self.project_id, employee_id=pm_profile.id, project_role="project_manager",
                    assigned_by=ADMIN_ID, assignment_reason="test setup",
                ),
                V2ProjectMembership(
                    project_id=self.project_id, employee_id=self.supervisor_profile.id, project_role="site_supervisor",
                    assigned_by=ADMIN_ID, assignment_reason="test setup",
                ),
            ])

            vendor = V2Vendor(name="Acme Electric", contact_person="Acme Owner", phone="+911111111111")
            self.session.add(vendor)
            self.session.flush()
            self.vendor_contact = V2VendorContact(
                vendor_id=vendor.id, name="Jane Doe", phone="+911234567890", telegram_chat_id="777",
            )
            self.session.add(self.vendor_contact)
            self.session.flush()
            self.assignment = TaskVendorAssignment(
                task_id=uuid.uuid4(), project_id=self.project_id, vendor_id=vendor.id, assigned_by=PM_ID,
            )
            self.session.add(self.assignment)

            self.task = Task(
                id=uuid.uuid4(), project_id=self.project_id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Task T001",
                schedule_classification="execution", applicability="mandatory", lifecycle_status="ready",
            )
            self.session.add(self.task)

            gate = V2ProjectExternalGate(
                id=uuid.uuid4(), project_id=self.project_id, original_code="E001", template_sequence=1,
                approval_name="Fire NOC", mapping_classification="exact", applicability_state="applicable",
                blocking=True, accountable_pm_user_id=PM_ID, source_type="project_manual",
            )
            self.session.add(gate)
            self.session.flush()
            self.approval = ProjectExternalApproval(
                id=uuid.uuid4(), project_id=self.project_id, project_gate_id=gate.id,
                status="assigned", assigned_to_user_id=SUPERVISOR_USER_ID, assigned_by=PM_ID,
            )
            self.session.add(self.approval)

        self.service = TelegramInboundService(self.session)

    def tearDown(self):
        self.session.close()

    def _last_message(self) -> InboundMessage:
        return self.session.query(InboundMessage).order_by(InboundMessage.created_at.desc()).first()

    # ---- identity matching -------------------------------------------------

    def test_unmatched_chat_id_is_rejected_like_whatsapp(self):
        self.service.process(1, UNKNOWN_CHAT_ID, "STATUS T001 in_progress")
        outcome = self._last_message()
        self.assertEqual(outcome.processing_status, "unmatched")

    def test_retried_update_does_not_reexecute_the_command(self):
        self.service.process(100, "555", "STATUS T001 in_progress")
        first = self._last_message()
        self.service.process(100, "555", "STATUS T001 in_progress")
        second = self._last_message()
        self.assertEqual(first.id, second.id)

    # ---- employee STATUS (was hardcoded to "Reported via WhatsApp.") -------

    def test_status_command_transitions_task_with_telegram_reason(self):
        self.service.process(1, "555", "STATUS T001 in_progress")

        outcome = self._last_message()
        self.assertEqual(outcome.processing_status, "processed")
        task = self.session.get(Task, self.task.id)
        self.assertEqual(task.lifecycle_status, "in_progress")

    # ---- Telegram task plan U3: no cancel, no invented early-start reason --

    def test_pm_cannot_cancel_a_task_from_telegram(self):
        """The PM may cancel in the Web App; a messaging channel used to pass
        "Reported via Telegram." as the required cancellation reason."""
        pm_profile = self.session.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == PM_ID))
        pm_profile.telegram_chat_id = "556"
        self.session.commit()

        self.service.process(1, "556", "STATUS T001 cancelled")

        outcome = self._last_message()
        self.assertEqual(outcome.processing_status, "rejected")
        self.assertEqual(outcome.rejection_reason, "Cancellation is only available in the Web App.")
        self.assertEqual(self.session.get(Task, self.task.id).lifecycle_status, "ready")

    def test_typed_early_start_is_refused_and_records_no_reason(self):
        self.task.planned_start_date = date.today() + timedelta(days=1)
        self.session.commit()

        self.service.process(1, "555", "STATUS T001 in_progress")

        outcome = self._last_message()
        self.assertEqual(outcome.processing_status, "rejected")
        self.assertIn("reason is required", outcome.rejection_reason)
        task = self.session.get(Task, self.task.id)
        self.session.refresh(task)
        self.assertEqual(task.lifecycle_status, "ready")
        self.assertIsNone(task.early_start_reason)

    def test_typed_on_time_start_is_audited_as_telegram(self):
        self.task.planned_start_date = date.today()
        self.session.commit()

        self.service.process(1, "555", "STATUS T001 in_progress")

        self.assertEqual(self._last_message().processing_status, "processed")
        audit = self.session.scalar(select(V2AuditEvent).where(V2AuditEvent.entity_id == self.task.id))
        self.assertEqual(audit.source, "telegram")
        self.assertNotIn("Reported via", audit.reason)
        self.assertIsNone(self.session.get(Task, self.task.id).early_start_reason)

    # ---- vendor ACCEPT/DECLINE/CLARIFY (was hardcoded channel="whatsapp") --

    def _assignment_ref(self) -> str:
        return str(self.assignment.id).replace("-", "")[:8]

    def test_accept_records_acknowledgement_with_telegram_channel(self):
        self.service.process(1, "777", f"ACCEPT {self._assignment_ref()}")

        outcome = self._last_message()
        self.assertEqual(outcome.processing_status, "processed")
        ack = self.session.query(VendorAcknowledgement).one()
        self.assertEqual(ack.response, "accepted")
        self.assertEqual(ack.channel, "telegram")

    def test_decline_records_acknowledgement_with_telegram_channel(self):
        self.service.process(1, "777", f"DECLINE {self._assignment_ref()}")
        ack = self.session.query(VendorAcknowledgement).one()
        self.assertEqual(ack.response, "declined")
        self.assertEqual(ack.channel, "telegram")

    def test_clarify_records_acknowledgement_with_telegram_channel_and_note(self):
        self.service.process(1, "777", f"CLARIFY {self._assignment_ref()} need more info")
        ack = self.session.query(VendorAcknowledgement).one()
        self.assertEqual(ack.response, "clarification_requested")
        self.assertEqual(ack.channel, "telegram")
        self.assertEqual(ack.note, "need more info")

    # ---- gate commands: dispatch reaches the same handler as WhatsApp ------
    # (business logic itself is unchanged and already covered by
    # test_inbound_message_matching_v2.py - see module docstring)

    def test_gateaccept_reaches_gate_acknowledgement_handler(self):
        self.service.process(1, "555", "GATEACCEPT badref")
        outcome = self._last_message()
        self.assertEqual(outcome.processing_status, "rejected")
        self.assertEqual(outcome.rejection_reason, "No unique assignment matched this reference.")

    def test_gatedecline_reaches_gate_acknowledgement_handler(self):
        self.service.process(1, "555", "GATEDECLINE badref")
        outcome = self._last_message()
        self.assertEqual(outcome.rejection_reason, "No unique assignment matched this reference.")

    def test_gatestatus_reaches_gate_status_handler(self):
        self.service.process(1, "555", "GATESTATUS badref on_track")
        outcome = self._last_message()
        self.assertEqual(outcome.rejection_reason, "No unique assignment matched this reference.")

    def test_gateopen_reaches_gate_evidence_session_handler(self):
        self.service.process(1, "555", "GATEOPEN badref")
        outcome = self._last_message()
        self.assertEqual(outcome.rejection_reason, "No unique assignment matched this reference.")

    def test_gateclose_reaches_gate_evidence_session_handler(self):
        self.service.process(1, "555", "GATECLOSE")
        outcome = self._last_message()
        self.assertEqual(outcome.rejection_reason, "You have no open evidence session to close.")

    def test_gatedecide_reaches_role_gate_for_non_admin(self):
        self.service.process(1, "555", "GATEDECIDE badref APPROVE")
        outcome = self._last_message()
        self.assertEqual(outcome.rejection_reason, "This command is not available for your role.")

    def test_gateaccept_succeeds_end_to_end_for_the_assigned_employee(self):
        ref = str(self.approval.id).replace("-", "")[:8]
        self.service.process(1, "555", f"GATEACCEPT {ref}")

        outcome = self._last_message()
        self.assertEqual(outcome.processing_status, "processed")


if __name__ == "__main__":
    unittest.main()
