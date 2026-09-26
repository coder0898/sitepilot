"""Readable Telegram messages for internal task execution (Telegram task plan U4,
app/services/telegram_task_render.py).

Every in-scope task event renders as HTML with no raw payload lines and no
ids, and reads differently for the people doing the work than for reviewers
and the rest of the team.
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

from app.execution_models import Task, TaskBlocker, TaskDelayEvent, TaskSupportAssignment
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.telegram_render import render_telegram
from app.services.telegram_task_render import TASK_RENDERERS
from app.template_models import V2TemplateVersion  # noqa: F401 - FK target for V2Project

UUID_PATTERN = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.I)
PAYLOAD_KEY_LINE = re.compile(r"^[a-z_]+: ", re.M)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TelegramTaskRenderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            Task.__table__, TaskSupportAssignment.__table__, V2AuditEvent.__table__, TaskBlocker.__table__,
            TaskDelayEvent.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()

        with self.db.begin():
            self.admin = self._user("Niddhi Admin", UserRole.admin)
            self.pm, self.pm_profile = self._member("Prachit PM", UserRole.project_manager, None)
            self.supervisor, self.supervisor_profile = self._member("Deepak Supervisor", UserRole.supervisor, None)
            self.employee, self.employee_profile = self._member("Rohan Employee", UserRole.internal_employee, None)
            self.project = V2Project(
                code="PRJ-1", name="SIS Interior", client_name="Client", site_address="Site",
                start_date=date(2026, 9, 21), status="active", created_by=self.admin.id,
            )
            self.db.add(self.project)
            self.db.flush()
            for profile, role in (
                (self.pm_profile, "project_manager"),
                (self.supervisor_profile, "site_supervisor"),
                (self.employee_profile, "internal_employee"),
            ):
                self.db.add(V2ProjectMembership(
                    project_id=self.project.id, employee_id=profile.id, project_role=role,
                    assigned_by=self.admin.id, assignment_reason="seed",
                ))
            self.task = self._task("T008", "Formal site handover", task_class="standard", task_kind="work")
            self.class_a = self._task("T020", "Structural check", task_class="class_a", task_kind="work")
            self.gate_task = self._task("T014", "Issue delivery schedule", task_class=None, task_kind="approval_gate")
            self.db.add(TaskSupportAssignment(
                task_id=self.task.id, project_id=self.project.id, employee_id=self.employee_profile.id,
                responsibility="Execution", assigned_by=self.supervisor.id,
            ))

    def tearDown(self):
        self.db.close()

    # ---- fixtures ------------------------------------------------------------

    def _user(self, name, role) -> User:
        user = User(id=uuid.uuid4(), name=name, email=f"{uuid.uuid4().hex[:6]}@example.com", role=role, active=True)
        self.db.add(user)
        self.db.flush()
        return user

    def _member(self, name, role, _unused):
        user = self._user(name, role)
        profile = EmployeeProfile(user_id=user.id, employee_code=f"E-{uuid.uuid4().hex[:6]}", designation=name, availability="available")
        self.db.add(profile)
        self.db.flush()
        return user, profile

    def _task(self, code, title, *, task_class, task_kind) -> Task:
        task = Task(
            project_id=self.project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
            original_code=code, template_sequence=1, title=title, schedule_classification="execution",
            applicability="mandatory", task_class=task_class, task_kind=task_kind, lifecycle_status="in_progress",
            planned_start_date=date(2026, 9, 24),
        )
        self.db.add(task)
        self.db.flush()
        return task

    def _submitted_by(self, task: Task, user: User) -> None:
        self.db.add(V2AuditEvent(
            actor_user_id=user.id, action="TASK_STATUS_CHANGED", entity_type="task", entity_id=task.id,
            project_id=self.project.id, source="portal", before_json={"lifecycle_status": "in_progress"},
            after_json={"lifecycle_status": "submitted"}, reason="Submitted.",
        ))
        self.db.commit()

    def _render(self, event_type, payload, recipient_profile=None, task=None):
        task = task or self.task
        full = {"task_id": str(task.id), "project_id": str(self.project.id), **payload}
        return render_telegram(self.db, event_type, full, recipient_profile.id if recipient_profile else None)

    # ---- every in-scope event is readable ---------------------------------------

    def test_every_task_event_renders_readable_html_with_no_ids_or_payload_keys(self):
        blocker = TaskBlocker(task_id=self.task.id, project_id=self.project.id, type="Material", description="Tiles late")
        self.db.add(blocker)
        self.db.flush()
        delay = TaskDelayEvent(
            task_id=self.task.id, project_id=self.project.id, responsibility_type="internal", reason="Truck broke down",
            impact_days=2, recorded_by=self.supervisor.id,
        )
        self.db.add(delay)
        self.db.commit()
        payloads = {
            "task.status_changed": {"before_status": "ready", "target_status": "in_progress", "actor_user_id": str(self.employee.id)},
            "task.verification_recorded": {"decision": "rejected", "remarks": "Gaps", "verified_by": str(self.supervisor.id)},
            "task.approval_recorded": {"decision": "approved", "decided_by": str(self.pm.id)},
            "task.support_assigned": {"employee_id": str(self.employee_profile.id), "responsibility": "Execution"},
            "task.support_ended": {"previous_employee_id": str(self.employee_profile.id), "reason_code": "workload"},
            "task.blocker_created": {"blocker_id": str(blocker.id), "type": "Material", "description": "Tiles late"},
            "task.blocker_resolved": {"blocker_id": str(blocker.id), "resolved_by": str(self.supervisor.id)},
            "task.delay_recorded": {"delay_id": str(delay.id), "responsibility_type": "internal", "impact_days": 2},
            "task.rescheduled": {
                "before_planned_start_date": "2026-09-24", "planned_start_date": "2026-09-28",
                "before_planned_end_date": "2026-09-26", "planned_end_date": "2026-09-30", "reason": "Client delay",
            },
            "task.readiness_check": {"lifecycle_status": "planned", "planned_start_date": "2026-09-24"},
            "task.start_check": {"lifecycle_status": "ready", "planned_start_date": "2026-09-24"},
            "task.midday_check": {"lifecycle_status": "in_progress", "planned_start_date": "2026-09-24"},
            "task.eod_check": {"lifecycle_status": "in_progress", "planned_start_date": "2026-09-24"},
            "task.eod_followup_required": {"lifecycle_status": "in_progress", "update_sla_hours": 24},
            "task.escalated_to_admin": {"lifecycle_status": "in_progress", "update_sla_hours": 24},
        }
        self.assertEqual(set(payloads), set(TASK_RENDERERS))
        for event_type, payload in payloads.items():
            for recipient in (self.employee_profile, self.supervisor_profile, None):
                with self.subTest(event_type=event_type, recipient=getattr(recipient, "designation", None)):
                    message = self._render(event_type, payload, recipient)
                    self.assertEqual(message.parse_mode, "HTML")
                    self.assertTrue(message.text.startswith("<b>"))
                    self.assertIsNone(UUID_PATTERN.search(message.text), message.text)
                    self.assertIsNone(PAYLOAD_KEY_LINE.search(message.text), message.text)
                    self.assertNotIn("STATUS ", message.text)
                    self.assertIn("T008 - Formal site handover", message.text)

    def test_dynamic_values_are_html_escaped(self):
        message = self._render(
            "task.verification_recorded",
            {"decision": "rejected", "remarks": "<script>x</script> & more", "verified_by": str(self.supervisor.id)},
            self.employee_profile,
        )
        self.assertIn("&lt;script&gt;x&lt;/script&gt; &amp; more", message.text)
        self.assertNotIn("<script>", message.text)

    # ---- review outcomes ----------------------------------------------------------

    def test_rejection_tells_the_executor_who_rejected_why_and_what_to_do(self):
        message = self._render(
            "task.verification_recorded",
            {"decision": "rejected", "remarks": "Joint gaps at the door frame", "verified_by": str(self.supervisor.id)},
            self.employee_profile,
        )
        self.assertIn("<b>Rework Required</b>", message.text)
        self.assertIn("Rejected by: Deepak Supervisor", message.text)
        self.assertIn("Reason: Joint gaps at the door frame", message.text)
        self.assertIn("Add new progress and submit the task for review again.", message.text)

    def test_rejection_copy_for_the_pm_is_information_only(self):
        message = self._render(
            "task.verification_recorded",
            {"decision": "rejected", "remarks": "Gaps", "verified_by": str(self.supervisor.id)},
            self.pm_profile,
        )
        self.assertIn("Rework Required", message.text)
        self.assertNotIn("Add new progress", message.text)
        self.assertIn("No action required.", message.text)

    def test_pm_rejection_is_also_rework_required(self):
        message = self._render(
            "task.approval_recorded",
            {"decision": "rejected", "remarks": "Wrong grade", "decided_by": str(self.pm.id)},
            self.employee_profile,
        )
        self.assertIn("<b>Rework Required</b>", message.text)
        self.assertIn("Rejected by: Prachit PM", message.text)

    def test_verified_standard_work_is_completed_for_the_executor(self):
        message = self._render(
            "task.verification_recorded", {"decision": "verified", "verified_by": str(self.supervisor.id)},
            self.employee_profile,
        )
        self.assertIn("<b>Task Completed</b>", message.text)
        self.assertIn("Verified by: Deepak Supervisor", message.text)

    def test_verified_class_a_work_awaits_pm_approval(self):
        self._submitted_by(self.class_a, self.employee)
        executor = self._render(
            "task.verification_recorded", {"decision": "verified", "verified_by": str(self.supervisor.id)},
            self.employee_profile, task=self.class_a,
        )
        self.assertIn("<b>Verified - Awaiting PM Approval</b>", executor.text)
        self.assertIn("waiting for PM approval", executor.text)
        pm = self._render(
            "task.verification_recorded", {"decision": "verified", "verified_by": str(self.supervisor.id)},
            self.pm_profile, task=self.class_a,
        )
        self.assertIn("approve or reject it in the Web App", pm.text)

    # ---- submissions (KTD23 routing) -----------------------------------------------

    def test_work_submission_reads_as_a_review_request_for_the_supervisor(self):
        self._submitted_by(self.task, self.employee)
        payload = {"before_status": "in_progress", "target_status": "submitted", "actor_user_id": str(self.employee.id)}
        supervisor = self._render("task.status_changed", payload, self.supervisor_profile)
        self.assertIn("<b>Task Submitted for Review</b>", supervisor.text)
        self.assertIn("Submitted by: Rohan Employee", supervisor.text)
        self.assertIn("Review it in the Web App.", supervisor.text)
        submitter = self._render("task.status_changed", payload, self.employee_profile)
        self.assertIn("<b>Submitted for Review</b>", submitter.text)
        self.assertIn("You will be told the outcome.", submitter.text)

    def test_approval_gate_submission_never_asks_the_supervisor_to_verify(self):
        self._submitted_by(self.gate_task, self.employee)
        payload = {"before_status": "in_progress", "target_status": "submitted", "actor_user_id": str(self.employee.id)}
        supervisor = self._render("task.status_changed", payload, self.supervisor_profile, task=self.gate_task)
        self.assertIn("<b>Submitted - Awaiting PM Approval</b>", supervisor.text)
        self.assertNotIn("verif", supervisor.text.lower())
        self.assertNotIn("Review it", supervisor.text)
        self.assertIn("No action required.", supervisor.text)
        pm = self._render("task.status_changed", payload, self.pm_profile, task=self.gate_task)
        self.assertIn("approve or reject it in the Web App", pm.text)

    # ---- other status messages -------------------------------------------------------

    def test_early_start_reason_is_shown(self):
        self.task.actual_start_at = datetime.now(timezone.utc)
        self.task.early_start_reason = "Site handed over early"
        self.db.commit()
        message = self._render(
            "task.status_changed",
            {"before_status": "ready", "target_status": "in_progress", "actor_user_id": str(self.employee.id)},
            self.pm_profile,
        )
        self.assertIn("Early start reason: Site handed over early", message.text)

    def test_milestone_completion_is_named_as_such(self):
        milestone = self._task("T099", "Handover milestone", task_class=None, task_kind="milestone")
        self.db.commit()
        message = self._render(
            "task.status_changed", {"before_status": "planned", "target_status": "completed"}, self.pm_profile,
            task=milestone,
        )
        self.assertIn("<b>Milestone Completed</b>", message.text)

    def test_support_assignment_reads_differently_for_the_assignee(self):
        payload = {"employee_id": str(self.employee_profile.id), "responsibility": "Execution"}
        self.assertIn("Task Assigned to You", self._render("task.support_assigned", payload, self.employee_profile).text)
        other = self._render("task.support_assigned", payload, self.pm_profile).text
        self.assertIn("Employee Assigned to Task", other)
        self.assertIn("Employee: Rohan Employee", other)

    # ---- U5 buttons: shown only to people the lifecycle rules would allow -----------

    def _buttons(self, event_type, payload, recipient, task=None) -> list[str]:
        message = self._render(event_type, payload, recipient, task=task)
        return [button["text"] for row in message.button_rows() for button in row]

    def test_start_task_goes_only_to_the_assigned_employee(self):
        self.task.lifecycle_status = "ready"
        self.db.commit()
        payload = {"before_status": "planned", "target_status": "ready"}
        self.assertEqual(self._buttons("task.status_changed", payload, self.employee_profile), ["Start Task"])
        # An employee is assigned, so the Supervisor/PM may not start it.
        self.assertEqual(self._buttons("task.status_changed", payload, self.supervisor_profile), [])
        self.assertEqual(self._buttons("task.status_changed", payload, self.pm_profile), [])

    def test_mark_ready_for_a_planned_task_on_assignment_and_checks(self):
        self.task.lifecycle_status = "planned"
        self.db.commit()
        assigned = {"employee_id": str(self.employee_profile.id), "responsibility": "Execution"}
        self.assertEqual(self._buttons("task.support_assigned", assigned, self.employee_profile), ["Mark Task Ready"])
        self.assertEqual(self._buttons("task.support_assigned", assigned, self.supervisor_profile), ["Mark Task Ready"])
        check = {"lifecycle_status": "planned", "planned_start_date": "2026-09-24"}
        self.assertEqual(self._buttons("task.readiness_check", check, self.employee_profile), ["Mark Task Ready"])
        # The midday check carries no start buttons.
        self.assertEqual(self._buttons("task.midday_check", check, self.employee_profile), [])

    def test_unassigned_work_can_be_started_by_the_supervisor(self):
        self.class_a.lifecycle_status = "ready"
        self.db.commit()
        check = {"lifecycle_status": "ready", "planned_start_date": "2026-09-24"}
        self.assertEqual(self._buttons("task.start_check", check, self.supervisor_profile, task=self.class_a), ["Start Task"])

    def test_nobody_can_self_start_an_unassigned_approval_gate_task(self):
        self.gate_task.lifecycle_status = "ready"
        self.db.commit()
        check = {"lifecycle_status": "ready", "planned_start_date": "2026-09-24"}
        for recipient in (self.supervisor_profile, self.pm_profile):
            self.assertEqual(self._buttons("task.start_check", check, recipient, task=self.gate_task), [])

    def test_no_buttons_once_the_task_has_moved_on(self):
        self.task.lifecycle_status = "in_progress"
        self.db.commit()
        payload = {"before_status": "planned", "target_status": "ready"}
        self.assertEqual(self._buttons("task.status_changed", payload, self.employee_profile), [])

    def test_missing_ids_degrade_to_placeholders(self):
        for event_type in TASK_RENDERERS:
            with self.subTest(event_type=event_type):
                message = render_telegram(self.db, event_type, {"task_id": "not-a-uuid"}, None)
                self.assertIn("Unknown task", message.text)


if __name__ == "__main__":
    unittest.main()
