from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import (
    BaselineTask,
    OutboxEvent,
    ProjectBaseline,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDelayEvent,
    TaskDependency,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    ProjectRoleChange,
    V2AuditEvent,
    V2Project,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.services.project_visibility import ProjectVisibilityService
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


class ProjectVisibilitySummaryTests(unittest.TestCase):
    """U1: `ProjectVisibilityService.summarize` (R1-R3).

    Builds execution-layer `Task` rows directly against a SQLite harness
    (mirroring the ATTACHed-schema pattern used by
    test_task_blockers_delays_v2.py) rather than driving the full
    baseline-lock/activation HTTP flow, since this unit only needs realistic
    `tasks` rows, not a real activation history.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2ProjectTaskDependency.__table__,
            ProjectRoleChange.__table__,
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            TaskVerification.__table__,
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            TaskApprovalDecision.__table__,
            TaskSupportAssignment.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.project_id = uuid.uuid4()

        with self.Session.begin() as session:
            session.add(self.admin)
            session.add(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))
            session.flush()
            session.add(EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"))
            session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Project 1", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))

    def tearDown(self):
        self.engine.dispose()

    def make_task(self, session, code: str, lifecycle_status: str = "planned", **overrides) -> Task:
        baseline_id = uuid.uuid4()
        baseline_task_id = uuid.uuid4()
        task = Task(
            id=uuid.uuid4(), project_id=self.project_id, baseline_id=baseline_id, baseline_task_id=baseline_task_id,
            original_code=code, template_sequence=1, title=f"Task {code}",
            schedule_classification="execution", applicability="mandatory", lifecycle_status=lifecycle_status,
            **overrides,
        )
        session.add(task)
        return task

    def summarize(self):
        with self.Session() as session:
            return ProjectVisibilityService(session).summarize(self.project_id, self.admin)

    # ---- happy paths -----------------------------------------------------

    def test_status_counts_across_a_mix_of_lifecycle_states(self):
        with self.Session.begin() as session:
            self.make_task(session, "T001", "planned")
            self.make_task(session, "T002", "in_progress")
            self.make_task(session, "T003", "completed")
            self.make_task(session, "T004", "cancelled")

        summary = self.summarize()
        self.assertEqual(summary.total_count, 4)
        self.assertEqual(summary.planned_count, 1)
        self.assertEqual(summary.active_count, 1)
        self.assertEqual(summary.completed_count, 1)
        self.assertEqual(summary.cancelled_count, 1)
        self.assertEqual(summary.status_counts["planned"], 1)

    def test_blocked_and_overdue_can_apply_to_the_same_task_simultaneously(self):
        now = datetime.now(timezone.utc)
        with self.Session.begin() as session:
            task = self.make_task(session, "T001", "in_progress", due_at=now - timedelta(days=1))
            session.flush()
            session.add(TaskBlocker(
                task_id=task.id, project_id=self.project_id, type="material", description="Waiting on rebar.",
            ))

        summary = self.summarize()
        self.assertEqual([t.original_code for t in summary.blocked_tasks], ["T001"])
        self.assertEqual([t.original_code for t in summary.overdue_tasks], ["T001"])

    # ---- edge cases --------------------------------------------------------

    def test_project_with_zero_tasks_returns_all_zero_summary(self):
        summary = self.summarize()
        self.assertEqual(summary.total_count, 0)
        self.assertEqual(summary.planned_count, 0)
        self.assertEqual(summary.blocked_tasks, [])
        self.assertEqual(summary.overdue_tasks, [])
        self.assertEqual(summary.no_update_tasks, [])
        self.assertEqual(summary.reassignment_required, [])

    def test_resolved_blocker_does_not_count_as_blocked(self):
        with self.Session.begin() as session:
            task = self.make_task(session, "T001", "in_progress")
            session.flush()
            session.add(TaskBlocker(
                task_id=task.id, project_id=self.project_id, type="material", description="Resolved already.",
                resolved_at=datetime.now(timezone.utc), resolved_by=ADMIN_ID,
            ))

        summary = self.summarize()
        self.assertEqual(summary.blocked_tasks, [])

    def test_completed_task_never_counts_as_overdue_even_past_due_at(self):
        now = datetime.now(timezone.utc)
        with self.Session.begin() as session:
            self.make_task(session, "T001", "completed", due_at=now - timedelta(days=5))

        summary = self.summarize()
        self.assertEqual(summary.overdue_tasks, [])

    def test_no_update_task_without_progress_updates_uses_created_at(self):
        now = datetime.now(timezone.utc)
        with self.Session.begin() as session:
            self.make_task(
                session, "T001", "in_progress", update_sla_hours=24,
                created_at=now - timedelta(hours=48),
            )

        summary = self.summarize()
        self.assertEqual([t.original_code for t in summary.no_update_tasks], ["T001"])

    def test_recent_progress_update_clears_no_update_condition(self):
        now = datetime.now(timezone.utc)
        with self.Session.begin() as session:
            task = self.make_task(
                session, "T001", "in_progress", update_sla_hours=24,
                created_at=now - timedelta(hours=48),
            )
            session.flush()
            session.add(TaskProgressUpdate(
                task_id=task.id, project_id=self.project_id, update_type="note", note="Still going.",
                submitted_by=PM_ID, created_at=now - timedelta(hours=1),
            ))

        summary = self.summarize()
        self.assertEqual(summary.no_update_tasks, [])

    def test_approval_gate_past_due_without_decision_is_at_risk(self):
        now = datetime.now(timezone.utc)
        with self.Session.begin() as session:
            self.make_task(
                session, "G001", "approval_pending", task_kind="approval_gate", due_at=now - timedelta(days=1),
            )

        summary = self.summarize()
        self.assertEqual([t.original_code for t in summary.approval_gates_at_risk], ["G001"])

    def test_approval_gate_decided_on_time_is_not_at_risk(self):
        now = datetime.now(timezone.utc)
        with self.Session.begin() as session:
            task = self.make_task(
                session, "G001", "completed", task_kind="approval_gate", due_at=now + timedelta(days=5),
            )
            session.flush()
            session.add(TaskApprovalDecision(
                task_id=task.id, decision="approved", decided_by=ADMIN_ID, decided_at=now,
            ))

        summary = self.summarize()
        self.assertEqual(summary.approval_gates_at_risk, [])

    # ---- integration -------------------------------------------------------

    def test_summary_is_identical_across_repeated_calls_at_the_same_instant(self):
        with self.Session.begin() as session:
            self.make_task(session, "T001", "in_progress")

        first = self.summarize()
        second = self.summarize()
        self.assertEqual(first.status_counts, second.status_counts)
        self.assertEqual(len(first.blocked_tasks), len(second.blocked_tasks))


if __name__ == "__main__":
    unittest.main()
