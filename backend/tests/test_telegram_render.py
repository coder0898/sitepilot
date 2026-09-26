"""Telegram message readability layer (app/services/telegram_render.py).

Verifies the human-readable rendering added on top of the previous raw
key:value dump, for the event types covered by
docs/2026-09-19-001-telegram-phase1-status-phase2-test-plan.md's Phase 2
manual tests. Also verifies the renderer never breaks on a missing/unknown
id (degrades to a placeholder string) and that an uncovered event type
still gets the old raw dump.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import ProjectExternalApproval, Task, TaskBlocker, TaskDelayEvent, TaskSupportAssignment
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.telegram_render import render_telegram, render_telegram_message
from app.vendor_models import V2Vendor


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TelegramRenderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # V2ProjectExternalGate's broad_mapping_text CHECK constraint calls
            # Postgres' btrim() - SQLite has no such builtin, so every test
            # that creates this table registers a trivial stand-in (same
            # pattern test_project_gate_assignment_v2.py already uses).
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__,
            V2ProjectMembership.__table__, Task.__table__, V2Vendor.__table__,
            V2ProjectExternalGate.__table__, ProjectExternalApproval.__table__,
            TaskSupportAssignment.__table__, V2AuditEvent.__table__, TaskBlocker.__table__, TaskDelayEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()

        with self.db.begin():
            admin = User(id=uuid.uuid4(), name="Niddhi Admin", email="admin@example.com", role=UserRole.admin, active=True)
            supervisor_user = User(id=uuid.uuid4(), name="Deepak Solanki", email="deepak@example.com", role=UserRole.supervisor, active=True)
            self.db.add_all([admin, supervisor_user])
            self.db.flush()

            self.supervisor_profile = EmployeeProfile(
                user_id=supervisor_user.id, employee_code="EMP-SUP", designation="Supervisor", availability="available",
            )
            self.db.add(self.supervisor_profile)
            self.db.flush()

            self.project = V2Project(
                code="PRJ-1", name="Test Project 1", client_name="Test Client", site_address="Test Site",
                start_date=date(2026, 9, 21), status="active", created_by=admin.id,
            )
            self.db.add(self.project)
            self.db.flush()

            self.db.add(V2ProjectMembership(
                project_id=self.project.id, employee_id=self.supervisor_profile.id, project_role="site_supervisor",
                assigned_by=admin.id, assignment_reason="Initial assignment.",
            ))

            self.task = Task(
                project_id=self.project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T-014", template_sequence=1, title="Electrical Conduiting",
                schedule_classification="execution", planned_start_day=1, planned_end_day=3,
                applicability="mandatory",
            )
            self.db.add(self.task)

            self.vendor = V2Vendor(name="Acme Electricals", contact_person="Ramesh", phone="+911234567890")
            self.db.add(self.vendor)
            self.db.flush()

            self.gate = V2ProjectExternalGate(
                project_id=self.project.id, original_code="G-01", template_sequence=1,
                approval_name="Fire NOC", mapping_classification="unmapped", source_type="project_manual",
                accountable_pm_user_id=admin.id,
            )
            self.db.add(self.gate)
            self.db.flush()

            self.approval = ProjectExternalApproval(project_id=self.project.id, project_gate_id=self.gate.id)
            self.db.add(self.approval)

    def tearDown(self):
        self.db.close()

    # ---- project.activated ------------------------------------------------

    def test_project_activated_shows_name_role_and_no_action(self):
        text = render_telegram_message(
            self.db, "project.activated",
            {"project_id": str(self.project.id), "project_name": self.project.name},
            self.supervisor_profile.id,
        )
        self.assertIn("Test Project 1", text)
        self.assertIn("Site Supervisor", text)
        self.assertIn("Status: Active", text)
        self.assertIn("No action required.", text)
        self.assertNotIn(str(self.project.id), text)  # no raw UUID leaked

    def test_project_activated_falls_back_to_payload_name_when_project_missing(self):
        text = render_telegram_message(
            self.db, "project.activated",
            {"project_id": str(uuid.uuid4()), "project_name": "Ghost Project"},
            None,
        )
        self.assertIn("Ghost Project", text)
        self.assertIn("Team Member", text)  # no membership resolvable -> generic role

    # ---- project.member_added ---------------------------------------------

    def test_project_member_added_shows_readable_role(self):
        text = render_telegram_message(
            self.db, "project.member_added",
            {"project_id": str(self.project.id), "employee_id": str(uuid.uuid4()), "project_role": "internal_employee"},
            None,
        )
        self.assertIn("Test Project 1", text)
        self.assertIn("Internal Employee", text)

    # ---- task readiness/start checks --------------------------------------

    def test_task_start_check_is_readable_html_without_typed_commands(self):
        """Telegram task plan U4: readable HTML; typed STATUS hints are gone
        (buttons replace them from U5)."""
        message = render_telegram(
            self.db, "task.start_check",
            {"task_id": str(self.task.id), "project_id": str(self.project.id), "planned_start_date": "2026-09-21",
             "lifecycle_status": "ready"},
            self.supervisor_profile.id,
        )
        self.assertEqual(message.parse_mode, "HTML")
        self.assertIn("<b>Start Check</b>", message.text)
        self.assertIn("T-014 - Electrical Conduiting", message.text)
        self.assertIn("Planned start: 21 Sep 2026", message.text)
        self.assertNotIn("STATUS", message.text)

    # ---- task.support_assigned / task.support_ended -------------------------

    def _support_payload(self, employee_id):
        return {
            "task_id": str(self.task.id), "project_id": str(self.project.id),
            "assignment_id": str(uuid.uuid4()), "employee_id": str(employee_id), "responsibility": "Site assist",
        }

    def test_support_assigned_to_recipient_says_it_is_theirs(self):
        self.task.lifecycle_status = "ready"
        self.db.commit()
        message = render_telegram(
            self.db, "task.support_assigned", self._support_payload(self.supervisor_profile.id), self.supervisor_profile.id,
        )
        text = message.text_for_buttons()
        self.assertIn("Task Assigned to You", text)
        self.assertIn("T-014 - Electrical Conduiting", text)
        self.assertIn("Site assist", text)
        self.assertIn("You are responsible for doing this task", text)
        # Telegram task plan U5: a real button carrying the task id, never a
        # typed STATUS command (task codes repeat across projects).
        self.assertNotIn("STATUS", text)
        [[button]] = message.button_rows()
        self.assertEqual(button["text"], "Start Task")
        self.assertEqual(button["callback_data"], f"t1:st:{self.task.id.hex}")

    def test_support_assigned_to_someone_else_names_them_with_no_action(self):
        text = render_telegram_message(
            self.db, "task.support_assigned", self._support_payload(self.supervisor_profile.id), uuid.uuid4(),
        )
        self.assertIn("Employee Assigned to Task", text)
        self.assertIn("Employee: Deepak Solanki", text)
        self.assertIn("No action required.", text)

    def test_support_ended_names_previous_employee(self):
        text = render_telegram_message(
            self.db, "task.support_ended",
            {
                "task_id": str(self.task.id), "project_id": str(self.project.id),
                "previous_employee_id": str(self.supervisor_profile.id), "replacement_employee_id": None,
            },
            self.supervisor_profile.id,
        )
        # The recipient IS the previous employee: told it's no longer theirs.
        self.assertIn("No Longer Assigned to You", text)
        self.assertNotIn("Replaced by", text)

        others = render_telegram_message(
            self.db, "task.support_ended",
            {
                "task_id": str(self.task.id), "project_id": str(self.project.id),
                "previous_employee_id": str(self.supervisor_profile.id), "replacement_employee_id": None,
            },
            uuid.uuid4(),
        )
        self.assertIn("Task Assignment Ended", others)
        self.assertIn("Deepak Solanki", others)

    # ---- task.vendor_assigned ----------------------------------------------

    def test_task_vendor_assigned_shows_accept_decline_ref(self):
        assignment_id = uuid.uuid4()
        text = render_telegram_message(
            self.db, "task.vendor_assigned",
            {
                "task_id": str(self.task.id), "project_id": str(self.project.id),
                "assignment_id": str(assignment_id), "vendor_id": str(self.vendor.id),
            },
            None,
        )
        ref = str(assignment_id).replace("-", "")[:8]
        self.assertIn("Acme Electricals", text)
        self.assertIn(f"`ACCEPT {ref}` or `DECLINE {ref}`", text)

    # ---- gate assignment / acknowledgement ---------------------------------

    def test_gate_assigned_uses_payload_names_without_extra_lookup(self):
        text = render_telegram_message(
            self.db, "project_external_approval.assigned",
            {
                "approval_id": str(self.approval.id), "project_id": str(self.project.id),
                "gate_name": "Fire NOC", "project_name": "Test Project 1", "due_date": "2026-10-01",
                "assigned_to_user_id": str(uuid.uuid4()),
            },
            None,
        )
        # Recipient None is never the assignee, so this is the Admin/FYI copy -
        # full gate template coverage lives in test_telegram_gate_render.py.
        self.assertIn("Fire NOC", text)
        self.assertIn("External Approval Assigned", text)
        self.assertIn("No action required.", text)

    def test_gate_accepted_enriches_gate_name_from_db(self):
        text = render_telegram_message(
            self.db, "project_external_approval.accepted",
            {"approval_id": str(self.approval.id), "project_id": str(self.project.id), "response": "accepted", "note": None},
            None,
        )
        self.assertIn("Fire NOC", text)
        self.assertIn("Test Project 1", text)
        self.assertIn("No action required.", text)

    # ---- fallback / robustness ---------------------------------------------

    def test_unmapped_event_type_keeps_raw_dump(self):
        text = render_telegram_message(self.db, "task.attendance_recorded", {"task_id": "abc", "type": "material"}, None)
        self.assertIn("task_id: abc", text)
        self.assertIn("type: material", text)

    def test_missing_ids_never_raise(self):
        # No project_id/task_id/approval_id at all - every renderer must
        # degrade to a placeholder, never crash the dispatch loop.
        for event_type in (
            "project.activated", "project.member_added", "task.start_check",
            "task.vendor_assigned", "project_external_approval.assigned",
        ):
            with self.subTest(event_type=event_type):
                text = render_telegram_message(self.db, event_type, {}, None)
                self.assertIsInstance(text, str)
                self.assertTrue(text)


if __name__ == "__main__":
    unittest.main()
