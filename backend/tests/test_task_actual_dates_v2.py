"""U5: a task records when work really started and really finished.

These are observations written from the task's own lifecycle transitions,
never entered by anyone. Nothing here adds a condition to a transition -
`test_task_lifecycle_transitions_v2.py` passing unedited is the proof of
that, and it is a Verification Contract gate for this plan.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

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
    BaselineTask, ExecutionExcludedDependency, ExecutionGate, ExecutionGateTask, FileObject, OutboxEvent,
    ProjectBaseline, Task, TaskBlocker, TaskDependency, TaskEvidence,
    TaskProgressUpdate, TaskSupportAssignment, TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateTask,
    V2ProjectMembership, V2ProjectTask, V2ProjectTaskDependency,
)
from app.routes.execution_tasks_v2 import router as execution_tasks_router
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


class TaskActualDatesTests(unittest.TestCase):
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
                      TaskEvidence.__table__, TaskVerification.__table__, V2TemplateExternalGate.__table__,
                      V2TemplateExternalGateTask.__table__, V2ProjectExternalGateTask.__table__,
                      TaskBlocker.__table__,
                      ExecutionGate.__table__, ExecutionGateTask.__table__, ExecutionExcludedDependency.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(execution_tasks_router)

        def override_db():
            with self.Session() as session: yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self): self.client.close(); self.engine.dispose()

    def act_as(self, user): self._current_actor = user

    def act_as_admin(self):
        self.act_as(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))

    def act_as_supervisor(self):
        self.act_as(User(id=SUPERVISOR_ID, name="Supervisor", email="sup@example.com", role=UserRole.supervisor, active=True))

    def _seed(self):
        """T001 -> T002 (work, chained) -> T003 (milestone)."""
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
            template_tasks = []
            for i, (code, kind) in enumerate([("T001", "work"), ("T002", "work"), ("T003", "milestone")], start=1):
                template_tasks.append(V2TemplateTask(
                    template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                    applicability="mandatory", task_class="standard", task_kind=kind,
                    evidence_required=False, duration_days=1, phase="Setup", category="Site"))
            session.add_all(template_tasks); session.flush()
            for i in range(len(template_tasks) - 1):
                session.add(V2TemplateTaskDependency(
                    template_version_id=published.id, predecessor_task_id=template_tasks[i].id,
                    successor_task_id=template_tasks[i + 1].id, dependency_type="finish_to_start",
                    blocking=True, rule_text=f"Rule {i + 1}", sequence_no=i + 1))
            self.published_version_id = published.id

    def activate_project(self):
        payload = {"project_name": "Futurex Fitout", "client": "Example Client", "location": "Mumbai",
                   "proposed_start_date": "2026-08-01", "target_handover_date": "2026-09-14",
                   "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
                   "template_version_id": str(self.published_version_id)}
        project = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(project.status_code, 201, project.text)
        pid = project.json()["id"]
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-tasks").status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-dependencies").status_code, 200)
        activated = self.client.post(f"/api/v2/projects/{pid}/activate", json={"reason": "Go live."})
        self.assertEqual(activated.status_code, 200, activated.text)
        return pid

    def tasks_by_code(self, project_id):
        with self.Session() as session:
            return {t.original_code: t for t in session.scalars(
                select(Task).where(Task.project_id == uuid.UUID(project_id))).all()}

    def transition(self, project_id, task_id, target_status, reason=None):
        body = {"target_status": target_status}
        if reason is not None: body["reason"] = reason
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/status", json=body)

    def submit_progress(self, project_id, task_id, note="Work done."):
        previous = self._current_actor
        self.act_as_admin()
        try:
            return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/progress", data={"note": note})
        finally:
            self.act_as(previous)

    def verify(self, project_id, task_id):
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/verify",
                                json={"decision": "verified", "remarks": None})

    def drive_to_completed(self, project_id, task):
        self.assertEqual(self.transition(project_id, task.id, "ready").status_code, 200)
        self.assertEqual(self.transition(project_id, task.id, "in_progress").status_code, 200)
        self.assertEqual(self.submit_progress(project_id, task.id).status_code, 200)
        self.assertEqual(self.transition(project_id, task.id, "submitted").status_code, 200)
        response = self.verify(project_id, task.id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["task"]["lifecycle_status"], "completed")

    # ---- the writes -----------------------------------------------------

    def test_a_task_that_has_never_started_reads_null_for_both(self):
        task = self.tasks_by_code(self.activate_project())["T001"]
        self.assertIsNone(task.actual_start_at)
        self.assertIsNone(task.actual_finish_at)

    def test_starting_records_an_actual_start_and_completing_records_a_finish(self):
        project_id = self.activate_project()
        t001 = self.tasks_by_code(project_id)["T001"]
        self.act_as_supervisor()

        self.assertEqual(self.transition(project_id, t001.id, "ready").status_code, 200)
        self.assertIsNone(self.tasks_by_code(project_id)["T001"].actual_start_at,
                          "scheduling a task is not starting it")

        self.assertEqual(self.transition(project_id, t001.id, "in_progress").status_code, 200)
        started = self.tasks_by_code(project_id)["T001"]
        self.assertIsNotNone(started.actual_start_at)
        self.assertIsNone(started.actual_finish_at)

        self.assertEqual(self.submit_progress(project_id, t001.id).status_code, 200)
        self.assertEqual(self.transition(project_id, t001.id, "submitted").status_code, 200)
        self.assertEqual(self.verify(project_id, t001.id).status_code, 200)

        finished = self.tasks_by_code(project_id)["T001"]
        self.assertIsNotNone(finished.actual_finish_at)
        self.assertEqual(finished.actual_start_at, started.actual_start_at,
                         "completing a task must not move the date it started")

    def test_a_rejected_and_resumed_task_keeps_its_first_actual_start(self):
        """The date work actually began, not the date it restarted."""
        project_id = self.activate_project()
        t001 = self.tasks_by_code(project_id)["T001"]
        self.act_as_supervisor()
        self.assertEqual(self.transition(project_id, t001.id, "ready").status_code, 200)
        self.assertEqual(self.transition(project_id, t001.id, "in_progress").status_code, 200)
        first_start = self.tasks_by_code(project_id)["T001"].actual_start_at
        self.assertIsNotNone(first_start)

        self.assertEqual(self.submit_progress(project_id, t001.id).status_code, 200)
        self.assertEqual(self.transition(project_id, t001.id, "submitted").status_code, 200)
        rejected = self.client.post(f"/api/v2/projects/{project_id}/tasks/{t001.id}/verify",
                                    json={"decision": "rejected", "remarks": "Redo the joints."})
        self.assertEqual(rejected.status_code, 200, rejected.text)

        # Rejection does not rest at `rejected` - TaskVerificationService
        # cascades the task straight back to `in_progress` so the crew can
        # resume. That cascade goes through transition(), so it is exactly
        # the path that would clobber the original start date.
        resumed = self.tasks_by_code(project_id)["T001"]
        self.assertEqual(resumed.lifecycle_status, "in_progress")
        self.assertEqual(resumed.actual_start_at, first_start)
        self.assertIsNone(resumed.actual_finish_at)

    def test_a_cancelled_task_records_no_actual_finish(self):
        """It did not finish, it stopped. A finish date here would make
        abandoned work look delivered to everything downstream."""
        project_id = self.activate_project()
        t001 = self.tasks_by_code(project_id)["T001"]
        self.act_as_supervisor()
        self.assertEqual(self.transition(project_id, t001.id, "ready").status_code, 200)
        self.assertEqual(self.transition(project_id, t001.id, "in_progress").status_code, 200)
        self.act_as_admin()
        cancelled = self.transition(project_id, t001.id, "cancelled", reason="Scope removed.")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)

        task = self.tasks_by_code(project_id)["T001"]
        self.assertEqual(task.lifecycle_status, "cancelled")
        self.assertIsNotNone(task.actual_start_at, "it did start")
        self.assertIsNone(task.actual_finish_at)

    def test_an_auto_completed_milestone_records_an_actual_finish(self):
        """`_auto_complete_successor_milestones` bypasses transition() by
        design, so it needs the write of its own."""
        project_id = self.activate_project()
        tasks = self.tasks_by_code(project_id)
        self.act_as_supervisor()
        for code in ("T001", "T002"):
            self.drive_to_completed(project_id, tasks[code])

        milestone = self.tasks_by_code(project_id)["T003"]
        self.assertEqual(milestone.lifecycle_status, "completed")
        self.assertIsNotNone(milestone.actual_finish_at)
        self.assertIsNone(milestone.actual_start_at, "a milestone is reached, not worked on")

    # ---- nothing else moved ---------------------------------------------

    def test_the_existing_audit_and_outbox_behaviour_is_unchanged(self):
        project_id = self.activate_project()
        t001 = self.tasks_by_code(project_id)["T001"]
        self.act_as_supervisor()
        self.assertEqual(self.transition(project_id, t001.id, "ready").status_code, 200)
        self.assertEqual(self.transition(project_id, t001.id, "in_progress").status_code, 200)
        with self.Session() as session:
            events = session.scalars(select(V2AuditEvent).where(
                V2AuditEvent.entity_type == "task", V2AuditEvent.entity_id == t001.id)).all()
            self.assertEqual(len(events), 2)
            self.assertTrue(all(e.action == "TASK_STATUS_CHANGED" for e in events))
            outbox = session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == t001.id)).all()
            self.assertEqual(len(outbox), 2)
            self.assertTrue(all(e.event_type == "task.status_changed" for e in outbox))

    def test_the_payload_carries_both_actual_fields(self):
        project_id = self.activate_project()
        t001 = self.tasks_by_code(project_id)["T001"]
        self.act_as_supervisor()
        self.assertEqual(self.transition(project_id, t001.id, "ready").status_code, 200)
        self.assertEqual(self.transition(project_id, t001.id, "in_progress").status_code, 200)
        response = self.client.get(f"/api/v2/projects/{project_id}/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        row = {r["original_code"]: r for r in response.json()}["T001"]
        self.assertIsNotNone(row["actual_start_at"])
        self.assertIsNone(row["actual_finish_at"])

    def test_historical_tasks_are_not_backfilled(self):
        """Resolves Q5 toward leaving them null: the TASK_STATUS_CHANGED
        audit trail stays the provenance record, and nothing downstream
        reads a null finish as 'today'."""
        project_id = self.activate_project()
        with self.Session.begin() as session:
            session.scalars(select(Task).where(Task.original_code == "T001")).one().lifecycle_status = "completed"
        task = self.tasks_by_code(project_id)["T001"]
        self.assertEqual(task.lifecycle_status, "completed")
        self.assertIsNone(task.actual_finish_at)


if __name__ == "__main__":
    unittest.main()
