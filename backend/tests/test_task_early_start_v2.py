"""U9: starting work before its planned date records why.

WHY THIS FILE HAS TO EXIST SEPARATELY. The Verification Contract requires
`test_task_lifecycle_transitions_v2.py` to pass unedited as the proof that
no transition changed. But that file cannot exercise this branch at all:
every project it builds uses `"proposed_start_date": "2026-08-01"`, a fixed
past date, so every task is already past its planned start and the
early-start path never runs. A green run there is not evidence U9 works -
these tests are.

This is the one place in the plan where the portal permits *less* than it
did. That is deliberate and R22-authorised: it adds no transition, removes
none, releases nothing new, and is satisfied by supplying a reason.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import (
    BaselineTask, ExecutionExcludedDependency, ExecutionGate, ExecutionGateTask, FileObject,
    OutboxEvent, ProjectBaseline, Task, TaskBlocker, TaskDependency, TaskEvidence,
    TaskProgressUpdate, TaskSupportAssignment, TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateTask,
    V2ProjectMembership, V2ProjectTask, V2ProjectTaskDependency,
)
from app.routes.execution_tasks_v2 import router as execution_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import (
    V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask,
    V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw): return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


class TaskEarlyStartTests(unittest.TestCase):
    """Starts the project *in the future* so its tasks really are early -
    the shape the existing lifecycle suite structurally cannot produce."""

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda v: v.strip() if v is not None else None)

        for table in (User.__table__, EmployeeProfile.__table__, V2Template.__table__, V2TemplateVersion.__table__,
                      V2TemplateTask.__table__, V2TemplateTaskDependency.__table__, V2Project.__table__,
                      V2ProjectMembership.__table__, V2ProjectTask.__table__, V2ProjectTaskDependency.__table__,
                      V2ProjectExternalGate.__table__, V2AuditEvent.__table__, ProjectBaseline.__table__,
                      BaselineTask.__table__, Task.__table__, TaskDependency.__table__, OutboxEvent.__table__,
                      TaskSupportAssignment.__table__, TaskProgressUpdate.__table__, FileObject.__table__,
                      TaskEvidence.__table__, TaskVerification.__table__, TaskBlocker.__table__,
                      V2TemplateExternalGate.__table__, V2TemplateExternalGateTask.__table__,
                      V2ProjectExternalGateTask.__table__, ExecutionGate.__table__,
                      ExecutionGateTask.__table__, ExecutionExcludedDependency.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(execution_router)

        def override_db():
            with self.Session() as session: yield session

        self.app.dependency_overrides[get_db] = override_db
        self._actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.app.dependency_overrides[current_user] = lambda: self._actor
        self.client = TestClient(self.app)

    def tearDown(self): self.client.close(); self.engine.dispose()

    def act_as_supervisor(self):
        self._actor = User(id=SUPERVISOR_ID, name="Supervisor", email="sup@example.com",
                           role=UserRole.supervisor, active=True)

    def _seed(self):
        with self.Session.begin() as session:
            session.add_all([
                User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True),
                User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True),
                User(id=SUPERVISOR_ID, name="Supervisor", email="sup@example.com", role=UserRole.supervisor, active=True),
            ])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available"),
            ])
            template = V2Template(code="WORKVED-45", name="Workved 45 Day"); session.add(template); session.flush()
            published = V2TemplateVersion(template_id=template.id, version_no=1, status="published", duration_days=45,
                                          content_hash="h", is_current_published=True, created_by=ADMIN_ID,
                                          published_by=ADMIN_ID, published_at=datetime.now(timezone.utc))
            session.add(published); session.flush()
            # T001 on day 1, T002 on day 30 - far enough out that it stays
            # early regardless of when this suite runs.
            for seq, (code, day) in enumerate([("T001", 1), ("T002", 30)], start=1):
                session.add(V2TemplateTask(
                    template_version_id=published.id, code=code, sequence_no=seq, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=day, planned_end_day=day,
                    applicability="mandatory", task_class="standard", task_kind="work",
                    evidence_required=False, duration_days=1, phase="Setup", category="Site"))
            # A pre-activation task with no planned days at all - R53.
            session.add(V2TemplateTask(
                template_version_id=published.id, code="T000", sequence_no=3, title="Pre-activation",
                schedule_classification="pre_activation", planned_start_day=None, planned_end_day=None,
                applicability="mandatory", task_class="standard", task_kind="work",
                evidence_required=False, phase="Pre", category="Admin"))
            self.published_version_id = published.id

    def activate(self, start_date: date):
        payload = {"project_name": "Futurex Fitout", "client": "Example Client", "location": "Mumbai",
                   "proposed_start_date": start_date.isoformat(),
                   "target_handover_date": (start_date + timedelta(days=44)).isoformat(),
                   "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
                   "template_version_id": str(self.published_version_id)}
        created = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        pid = created.json()["id"]
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-tasks").status_code, 200)
        activated = self.client.post(f"/api/v2/projects/{pid}/activate", json={"reason": "Go live."})
        self.assertEqual(activated.status_code, 200, activated.text)
        return pid

    def task(self, pid, code):
        with self.Session() as session:
            return session.scalars(select(Task).where(
                Task.project_id == uuid.UUID(pid), Task.original_code == code)).one()

    def start(self, pid, code, reason=None):
        task = self.task(pid, code)
        if task.lifecycle_status == "planned":
            self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/tasks/{task.id}/status",
                                              json={"target_status": "ready"}).status_code, 200)
        body = {"target_status": "in_progress"}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(f"/api/v2/projects/{pid}/tasks/{task.id}/status", json=body)

    # ---- the branch the existing suite cannot reach -------------------------

    def test_starting_before_the_planned_date_without_a_reason_is_refused(self):
        pid = self.activate(date.today() + timedelta(days=10))
        self.act_as_supervisor()
        refused = self.start(pid, "T001")
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertIn("early start", refused.json()["detail"].lower())

        task = self.task(pid, "T001")
        self.assertEqual(task.lifecycle_status, "ready", "the refused start must change nothing")
        self.assertIsNone(task.actual_start_at)
        self.assertIsNone(task.early_start_reason)

    def test_starting_before_the_planned_date_with_a_reason_succeeds_and_records_it(self):
        """Covers AE1."""
        pid = self.activate(date.today() + timedelta(days=10))
        self.act_as_supervisor()
        response = self.start(pid, "T001", reason="Scaffold crew arrived a week early.")
        self.assertEqual(response.status_code, 200, response.text)

        task = self.task(pid, "T001")
        self.assertEqual(task.lifecycle_status, "in_progress")
        self.assertEqual(task.early_start_reason, "Scaffold crew arrived a week early.")
        self.assertIsNotNone(task.actual_start_at)

    def test_an_early_start_leaves_the_baseline_untouched(self):
        pid = self.activate(date.today() + timedelta(days=10))
        with self.Session() as session:
            before = {b.original_code: (b.planned_start_day, b.planned_end_day) for b in
                      session.scalars(select(BaselineTask).where(BaselineTask.project_id == uuid.UUID(pid))).all()}
        self.act_as_supervisor()
        self.assertEqual(self.start(pid, "T001", reason="Crew arrived early.").status_code, 200)
        with self.Session() as session:
            after = {b.original_code: (b.planned_start_day, b.planned_end_day) for b in
                     session.scalars(select(BaselineTask).where(BaselineTask.project_id == uuid.UUID(pid))).all()}
        self.assertEqual(before, after)

    def test_the_reason_reaches_the_audit_trail_with_actor_and_timestamp(self):
        pid = self.activate(date.today() + timedelta(days=10))
        self.act_as_supervisor()
        self.assertEqual(self.start(pid, "T001", reason="Crew arrived early.").status_code, 200)
        with self.Session() as session:
            events = session.scalars(select(V2AuditEvent).where(
                V2AuditEvent.entity_id == self.task(pid, "T001").id,
                V2AuditEvent.action == "TASK_STATUS_CHANGED")).all()
            started = [e for e in events if e.after_json["lifecycle_status"] == "in_progress"]
            self.assertEqual(len(started), 1)
            self.assertEqual(started[0].reason, "Crew arrived early.")
            self.assertEqual(started[0].actor_user_id, SUPERVISOR_ID)
            self.assertIsNotNone(started[0].occurred_at)

    def test_an_empty_or_whitespace_reason_is_refused(self):
        pid = self.activate(date.today() + timedelta(days=10))
        self.act_as_supervisor()
        for reason in ("", "   ", "\n\t"):
            with self.subTest(reason=repr(reason)):
                self.assertEqual(self.start(pid, "T001", reason=reason).status_code, 422)

    # ---- everything that must still behave exactly as before ----------------

    def test_starting_on_or_after_the_planned_date_needs_no_reason(self):
        """The overwhelmingly common case, and the one the rest of the suite
        already exercises. It must be untouched."""
        pid = self.activate(date.today() - timedelta(days=5))
        self.act_as_supervisor()
        response = self.start(pid, "T001")
        self.assertEqual(response.status_code, 200, response.text)
        task = self.task(pid, "T001")
        self.assertIsNone(task.early_start_reason, "an on-time start is not an early start")
        self.assertIsNotNone(task.actual_start_at)

    def test_a_task_with_no_planned_start_date_starts_without_a_reason(self):
        """The pre-activation case. Demanding a reason for work that was
        never scheduled would be nonsense."""
        pid = self.activate(date.today() + timedelta(days=10))
        self.assertIsNone(self.task(pid, "T000").planned_start_at)
        self.act_as_supervisor()
        response = self.start(pid, "T000")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(self.task(pid, "T000").early_start_reason)

    def test_resuming_a_rejected_task_is_not_treated_as_a_fresh_early_start(self):
        """Once a task has an actual start it is not starting again, so a
        rework cycle must not start demanding reasons."""
        pid = self.activate(date.today() + timedelta(days=10))
        self.act_as_supervisor()
        self.assertEqual(self.start(pid, "T001", reason="Crew arrived early.").status_code, 200)
        task_id = self.task(pid, "T001").id

        self._actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/tasks/{task_id}/progress",
                                          data={"note": "Framing up."}).status_code, 200)
        self.act_as_supervisor()
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/tasks/{task_id}/status",
                                          json={"target_status": "submitted"}).status_code, 200)
        rejected = self.client.post(f"/api/v2/projects/{pid}/tasks/{task_id}/verify",
                                    json={"decision": "rejected", "remarks": "Redo the joints."})
        self.assertEqual(rejected.status_code, 200, rejected.text)
        # The rejection cascade returns the task to in_progress through
        # transition() with no reason - it must not have been refused.
        self.assertEqual(self.task(pid, "T001").lifecycle_status, "in_progress")

    def test_the_payload_carries_the_early_start_reason(self):
        pid = self.activate(date.today() + timedelta(days=10))
        self.act_as_supervisor()
        self.assertEqual(self.start(pid, "T001", reason="Crew arrived early.").status_code, 200)
        response = self.client.get(f"/api/v2/projects/{pid}/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        rows = {r["original_code"]: r for r in response.json()}
        self.assertEqual(rows["T001"]["early_start_reason"], "Crew arrived early.")
        self.assertIsNone(rows["T002"]["early_start_reason"])


if __name__ == "__main__":
    unittest.main()
