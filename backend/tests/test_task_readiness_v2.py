"""U6/U7: computed readiness - what can start, and what is holding the rest up.

Readiness is advisory. Where it disagrees with the transition guard that is
a defect, with exactly one accepted exception: Start-to-Start overlap,
which the template describes and the guard does not yet honour (KTD8).
"""
from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

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
    BaselineTask, ExecutionExcludedDependency, ExecutionGate, ExecutionGateStatusHistory,
    ExecutionGateTask, FileObject, OutboxEvent, ProjectBaseline, Task, TaskBlocker, TaskDependency,
    TaskEvidence, TaskProgressUpdate, TaskSupportAssignment, TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateApplicabilityDecision,
    V2ProjectExternalGateTask, V2ProjectMembership, V2ProjectTask, V2ProjectTaskDependency,
)
from app.routes.execution_tasks_v2 import router as execution_router
from app.routes.projects_v2 import router as projects_router
from app.services.task_readiness import TaskReadinessService
from app.template_models import (
    V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask,
    V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw): return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
EMPLOYEE_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")
# Every id here keeps hex letters on purpose. An all-numeric UUID hexes to
# an all-digit string, and SQLite's dynamic typing then stores it as a REAL
# instead of TEXT - it reads back as 9.999999999995e+31 and blows up on the
# way into uuid.UUID(). A harness trap, not a production one.
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd7")
START = date(2026, 8, 1)

ALL_TABLES = (
    User.__table__, EmployeeProfile.__table__, V2Template.__table__, V2TemplateVersion.__table__,
    V2TemplateTask.__table__, V2TemplateTaskDependency.__table__, V2Project.__table__,
    V2ProjectMembership.__table__, V2ProjectTask.__table__, V2ProjectTaskDependency.__table__,
    V2ProjectExternalGate.__table__, V2AuditEvent.__table__, ProjectBaseline.__table__,
    BaselineTask.__table__, Task.__table__, TaskDependency.__table__, OutboxEvent.__table__,
    TaskSupportAssignment.__table__, TaskProgressUpdate.__table__, FileObject.__table__,
    TaskEvidence.__table__, TaskVerification.__table__, TaskBlocker.__table__,
    V2TemplateExternalGate.__table__, V2TemplateExternalGateTask.__table__,
    V2ProjectExternalGateTask.__table__, V2ProjectExternalGateApplicabilityDecision.__table__,
    ExecutionGate.__table__, ExecutionGateTask.__table__, ExecutionExcludedDependency.__table__,
    ExecutionGateStatusHistory.__table__,
)


class ReadinessTestBase(unittest.TestCase):
    """Builds a real activated project by driving the actual endpoints, so
    readiness is computed against rows the production paths created."""

    task_specs = [("T001", "work", "mandatory"), ("T002", "work", "mandatory")]
    dependency_specs = [("T001", "T002", "finish_to_start")]
    gate_specs = []
    exclude_codes = ()

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda v: v.strip() if v is not None else None)

        for table in ALL_TABLES:
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(execution_router)

        def override_db():
            with self.Session() as session: yield session

        self.app.dependency_overrides[get_db] = override_db
        self._actor = self.user(ADMIN_ID, UserRole.admin)
        self.app.dependency_overrides[current_user] = lambda: self._actor
        self.client = TestClient(self.app)
        self.project_id = self._activate(exclude_codes=self.exclude_codes)

    def tearDown(self): self.client.close(); self.engine.dispose()

    @staticmethod
    def user(user_id, role):
        return User(id=user_id, name=str(role), email=f"{user_id}@example.com", role=role, active=True)

    def act_as(self, user_id, role): self._actor = self.user(user_id, role)

    def _seed(self):
        with self.Session.begin() as session:
            session.add_all([
                self.user(ADMIN_ID, UserRole.admin), self.user(PM_ID, UserRole.project_manager),
                self.user(SUPERVISOR_ID, UserRole.supervisor), self.user(EMPLOYEE_ID, UserRole.internal_employee),
                self.user(OUTSIDER_ID, UserRole.project_manager),
            ])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available"),
                EmployeeProfile(user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Fitter", availability="available"),
                EmployeeProfile(user_id=OUTSIDER_ID, employee_code="PM-999", designation="PM", availability="available"),
            ])
            template = V2Template(code="WORKVED-45", name="Workved 45 Day"); session.add(template); session.flush()
            published = V2TemplateVersion(template_id=template.id, version_no=1, status="published", duration_days=45,
                                          content_hash="h", is_current_published=True, created_by=ADMIN_ID,
                                          published_by=ADMIN_ID, published_at=datetime.now(timezone.utc))
            session.add(published); session.flush()

            tasks = {}
            for i, (code, kind, applicability) in enumerate(self.task_specs, start=1):
                tt = V2TemplateTask(template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                                    applicability=applicability, task_class="standard", task_kind=kind,
                                    evidence_required=False, duration_days=1, phase="Setup", category="Site")
                session.add(tt); session.flush(); tasks[code] = tt
            for i, (pred, succ, dep_type) in enumerate(self.dependency_specs, start=1):
                session.add(V2TemplateTaskDependency(
                    template_version_id=published.id, predecessor_task_id=tasks[pred].id,
                    successor_task_id=tasks[succ].id, dependency_type=dep_type, blocking=True,
                    rule_text=f"{succ} waits on {pred}.", sequence_no=i))
            for seq, (code, name, classification, mapped) in enumerate(self.gate_specs, start=1):
                gate = V2TemplateExternalGate(
                    template_version_id=published.id, code=code, sequence_no=seq, approval_name=name,
                    external_party="Landlord", mapping_classification=classification,
                    broad_mapping_text="Relevant procurement tasks" if classification == "broad_text" else None,
                    requires_configuration=classification != "exact",
                    required_by_type="project_day", required_by_value="5")
                session.add(gate); session.flush()
                if mapped:
                    session.add(V2TemplateExternalGateTask(gate_id=gate.id, template_task_id=tasks[mapped].id))
            self.published_version_id = published.id

    def _activate(self, exclude_codes=()):
        payload = {"project_name": "Futurex Fitout", "client": "Example Client", "location": "Mumbai",
                   "proposed_start_date": START.isoformat(), "target_handover_date": "2026-09-14",
                   "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
                   "template_version_id": str(self.published_version_id)}
        created = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        pid = created.json()["id"]
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-tasks").status_code, 200)
        for code in exclude_codes:
            with self.Session() as session:
                task_id = session.scalar(select(V2ProjectTask.id).where(
                    V2ProjectTask.project_id == uuid.UUID(pid), V2ProjectTask.original_code == code))
            self.assertEqual(self.client.post(
                f"/api/v2/projects/{pid}/tasks/{task_id}/applicability-decisions",
                json={"decision": "excluded", "reason": "Out of scope."}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-dependencies").status_code, 200)
        if self.gate_specs:
            self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-gates").status_code, 200)
            with self.Session() as session:
                gate_ids = [g.id for g in session.scalars(select(V2ProjectExternalGate).where(
                    V2ProjectExternalGate.project_id == uuid.UUID(pid))).all()]
            for gate_id in gate_ids:
                self.assertEqual(self.client.post(
                    f"/api/v2/projects/{pid}/gates/{gate_id}/applicability-decisions",
                    json={"decision": "applicable"}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/activate",
                                          json={"reason": "Go live."}).status_code, 200)
        return pid

    # ---- helpers -----------------------------------------------------------

    def readiness(self):
        with self.Session() as session:
            return TaskReadinessService(session).summarize(uuid.UUID(self.project_id), self._actor)

    def by_code(self):
        return {item.original_code: item for item in self.readiness().items}

    def set_status(self, code, status):
        with self.Session.begin() as session:
            session.scalars(select(Task).where(
                Task.project_id == uuid.UUID(self.project_id), Task.original_code == code)).one().lifecycle_status = status

    def set_gate_status(self, code, status):
        with self.Session.begin() as session:
            session.scalars(select(ExecutionGate).where(
                ExecutionGate.project_id == uuid.UUID(self.project_id),
                ExecutionGate.original_code == code)).one().status = status


class DependencyReadinessTests(ReadinessTestBase):
    task_specs = [("T001", "work", "mandatory"), ("T002", "work", "mandatory")]
    dependency_specs = [("T001", "T002", "finish_to_start")]

    def test_a_task_with_no_predecessors_is_startable(self):
        self.assertTrue(self.by_code()["T001"].startable)
        self.assertEqual(self.by_code()["T001"].reasons, [])

    def test_an_unfinished_finish_to_start_predecessor_blocks_and_is_named(self):
        item = self.by_code()["T002"]
        self.assertFalse(item.startable)
        self.assertEqual(item.state, "blocked")
        self.assertEqual([r.code for r in item.reasons], ["T001"])
        self.assertIn("Task T001", item.reasons[0].detail)
        self.assertIn("be finished", item.reasons[0].detail)

    def test_a_completed_predecessor_releases_the_successor(self):
        self.set_status("T001", "completed")
        self.assertTrue(self.by_code()["T002"].startable)

    def test_a_verified_standard_predecessor_satisfies_only_with_a_verification_on_record(self):
        """Mirrors the transition guard's per-kind rule rather than
        reimplementing it - `verified` alone is not enough, there has to be
        an unrejected decision behind it."""
        self.set_status("T001", "verified")
        self.assertFalse(self.by_code()["T002"].startable)

        with self.Session.begin() as session:
            task = session.scalars(select(Task).where(Task.original_code == "T001")).one()
            update = TaskProgressUpdate(project_id=uuid.UUID(self.project_id), task_id=task.id,
                                        note="Done.", update_type="note", submitted_by=SUPERVISOR_ID)
            session.add(update); session.flush()
            session.add(TaskVerification(task_id=task.id, submission_update_id=update.id,
                                         decision="verified", verified_by=SUPERVISOR_ID))
        self.assertTrue(self.by_code()["T002"].startable)

    def test_a_rejected_verification_leaves_the_successor_blocked(self):
        self.set_status("T001", "verified")
        with self.Session.begin() as session:
            task = session.scalars(select(Task).where(Task.original_code == "T001")).one()
            update = TaskProgressUpdate(project_id=uuid.UUID(self.project_id), task_id=task.id,
                                        note="Done.", update_type="note", submitted_by=SUPERVISOR_ID)
            session.add(update); session.flush()
            session.add(TaskVerification(task_id=task.id, submission_update_id=update.id,
                                         decision="rejected", verified_by=SUPERVISOR_ID))
        self.assertFalse(self.by_code()["T002"].startable)

    def test_a_completed_and_a_cancelled_task_are_not_startable_and_carry_no_reasons(self):
        self.set_status("T001", "completed")
        self.set_status("T002", "cancelled")
        for code, state in (("T001", "completed"), ("T002", "cancelled")):
            with self.subTest(code=code):
                item = self.by_code()[code]
                self.assertFalse(item.startable)
                self.assertEqual(item.state, state)
                self.assertEqual(item.reasons, [])

    def test_a_task_already_underway_is_not_startable(self):
        self.set_status("T001", "in_progress")
        item = self.by_code()["T001"]
        self.assertFalse(item.startable)
        self.assertEqual(item.state, "in_progress")


class StartToStartReadinessTests(ReadinessTestBase):
    task_specs = [("T001", "work", "mandatory"), ("T002", "work", "mandatory")]
    dependency_specs = [("T001", "T002", "start_to_start")]

    def test_a_started_start_to_start_predecessor_releases_the_successor(self):
        """Covers AE2, and the one place readiness is allowed to disagree
        with the guard."""
        self.set_status("T001", "in_progress")
        item = self.by_code()["T002"]
        self.assertTrue(item.startable)
        self.assertTrue(item.guard_diverges, "the guard still wants T001 finished; the UI must say so")

    def test_an_unstarted_start_to_start_predecessor_still_blocks(self):
        item = self.by_code()["T002"]
        self.assertFalse(item.startable)
        self.assertIn("have started", item.reasons[0].detail)

    def test_a_finished_start_to_start_predecessor_does_not_report_divergence(self):
        self.set_status("T001", "completed")
        item = self.by_code()["T002"]
        self.assertTrue(item.startable)
        self.assertFalse(item.guard_diverges, "the guard agrees once the predecessor is finished")


class GateReadinessTests(ReadinessTestBase):
    task_specs = [("T001", "work", "mandatory")]
    dependency_specs = []
    gate_specs = [("E001", "Landlord approval", "exact", "T001"),
                  ("E002", "Relevant procurement tasks", "broad_text", None)]

    def test_a_pending_gate_blocks_and_names_itself(self):
        """Covers AE3."""
        item = self.by_code()["T001"]
        self.assertFalse(item.startable)
        gate_reasons = [r for r in item.reasons if r.kind == "gate"]
        self.assertEqual([r.code for r in gate_reasons], ["E001"])
        self.assertIn("Landlord approval", gate_reasons[0].detail)
        self.assertIn("pending_review", gate_reasons[0].detail)

    def test_a_rejected_gate_blocks_exactly_as_a_pending_one_does(self):
        """Covers AE6. From the site's point of view an approval under
        review and one that was refused are both permission not granted."""
        self.set_gate_status("E001", "rejected")
        item = self.by_code()["T001"]
        self.assertFalse(item.startable)
        self.assertIn("rejected", [r.status for r in item.reasons if r.kind == "gate"])

    def test_an_approved_or_not_required_gate_stops_blocking(self):
        for status in ("approved", "not_required"):
            with self.subTest(status=status):
                self.set_gate_status("E001", status)
                self.assertTrue(self.by_code()["T001"].startable)

    def test_a_gate_covering_no_task_is_reported_as_unresolved(self):
        """Covers AE10. The demo lets these be toggled while they release
        nothing; naming them is the difference."""
        unresolved = self.readiness().unresolved_gates
        self.assertEqual([r.code for r in unresolved], ["E002"])
        self.assertFalse(unresolved[0].enforced)
        self.assertIn("releases nothing", unresolved[0].detail)

    def test_several_unsatisfied_conditions_are_all_reported(self):
        self.set_gate_status("E001", "submitted")
        item = self.by_code()["T001"]
        self.assertGreaterEqual(len(item.reasons), 1)
        self.assertTrue(all(r.detail for r in item.reasons))


class ExcludedPredecessorReadinessTests(ReadinessTestBase):
    task_specs = [("T001", "work", "conditional"), ("T002", "work", "mandatory")]
    dependency_specs = [("T001", "T002", "finish_to_start")]
    exclude_codes = ("T001",)

    def test_a_successor_of_an_excluded_predecessor_says_so_without_being_blocked(self):
        """Covers AE9. The edge was dropped at baseline lock, so the guard
        will let T002 start. Silence would show it as unconditionally
        startable; the advisory reason is the half-step."""
        item = self.by_code()["T002"]
        self.assertTrue(item.startable, "the guard permits it, so readiness must not claim otherwise")
        advisory = [r for r in item.reasons if r.kind == "excluded_predecessor"]
        self.assertEqual([r.code for r in advisory], ["T001"])
        self.assertFalse(advisory[0].enforced)
        self.assertIn("excluded from this project's scope", advisory[0].detail)


class ReadinessAccessTests(ReadinessTestBase):
    task_specs = [("T001", "work", "mandatory"), ("T002", "work", "mandatory")]
    dependency_specs = [("T001", "T002", "finish_to_start")]

    def test_an_internal_employee_sees_only_their_assigned_tasks(self):
        """`get_project`'s can_view admits this role to the whole project,
        but the sibling task endpoints narrow it to its own assignments.
        Readiness reasons carry project-wide titles and gate names, so an
        unscoped result would hand the role a view it does not have."""
        with self.Session.begin() as session:
            employee_id = session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == EMPLOYEE_ID))
            task = session.scalars(select(Task).where(Task.original_code == "T002")).one()
            # Membership is what gets them through `can_view` at all; the
            # support assignment is what narrows them once inside.
            session.add(V2ProjectMembership(
                project_id=uuid.UUID(self.project_id), employee_id=employee_id, project_role="internal_employee",
                assigned_by=ADMIN_ID, assignment_reason="Fit-out support"))
            session.flush()
            session.add(TaskSupportAssignment(
                project_id=uuid.UUID(self.project_id), task_id=task.id, employee_id=employee_id,
                responsibility="execution", status="active", assigned_by=ADMIN_ID))

        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        summary = self.readiness()
        self.assertEqual([i.original_code for i in summary.items], ["T002"])
        # T001 is their blocking predecessor but they may not see it, so it
        # must not be named back to them.
        self.assertEqual([r.code for r in summary.items[0].reasons], [])

    def test_the_endpoint_refuses_a_non_member_and_an_unknown_project(self):
        self.act_as(OUTSIDER_ID, UserRole.project_manager)
        refused = self.client.get(f"/api/v2/projects/{self.project_id}/task-readiness")
        self.assertEqual(refused.status_code, 403, refused.text)
        self.act_as(ADMIN_ID, UserRole.admin)
        missing = self.client.get(f"/api/v2/projects/{uuid.uuid4()}/task-readiness")
        self.assertEqual(missing.status_code, 404)

    def test_the_endpoint_returns_readiness_with_readable_reasons(self):
        response = self.client.get(f"/api/v2/projects/{self.project_id}/task-readiness")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["startable_count"], 1)
        blocked = {i["original_code"]: i for i in body["items"]}["T002"]
        self.assertEqual(blocked["reasons"][0]["code"], "T001")
        self.assertTrue(blocked["reasons"][0]["title"], "reasons carry names, not bare ids")

    def test_a_draft_project_returns_an_empty_result_rather_than_an_error(self):
        payload = {"project_name": "Not Yet Live", "client": "C", "location": "Mumbai",
                   "proposed_start_date": START.isoformat(), "target_handover_date": "2026-09-14",
                   "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
                   "template_version_id": str(self.published_version_id)}
        draft = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(draft.status_code, 201, draft.text)
        response = self.client.get(f"/api/v2/projects/{draft.json()['id']}/task-readiness")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [])


class ReadinessQueryBudgetTests(ReadinessTestBase):
    """KTD1: the query count must not grow with the size of the project.
    Asserted by counting queries, not by timing them."""

    task_specs = [(f"T{i:03d}", "work", "mandatory") for i in range(1, 31)]
    dependency_specs = [(f"T{i:03d}", f"T{i + 1:03d}", "finish_to_start") for i in range(1, 30)]
    gate_specs = [("E001", "Landlord approval", "exact", "T005")]

    def _count_queries(self):
        counter = {"n": 0}

        @event.listens_for(self.engine, "before_cursor_execute")
        def count(*_args, **_kwargs):
            counter["n"] += 1

        with self.Session() as session:
            TaskReadinessService(session).summarize(uuid.UUID(self.project_id), self._actor)
        event.remove(self.engine, "before_cursor_execute", count)
        return counter["n"]

    def test_a_thirty_task_project_resolves_in_a_bounded_query_count(self):
        self.assertLessEqual(self._count_queries(), 12)

    def test_the_count_does_not_grow_when_predecessors_need_a_verification_check(self):
        """The trap KTD7 exists for: calling the guard's own
        `_predecessor_satisfied` in a loop issues one query per predecessor
        sitting at `verified`, which only shows up in this shape."""
        baseline = self._count_queries()
        with self.Session.begin() as session:
            for task in session.scalars(select(Task).where(Task.project_id == uuid.UUID(self.project_id))).all():
                task.lifecycle_status = "verified"
                update = TaskProgressUpdate(project_id=uuid.UUID(self.project_id), task_id=task.id,
                                            note="Done.", update_type="note", submitted_by=SUPERVISOR_ID)
                session.add(update); session.flush()
                session.add(TaskVerification(task_id=task.id, submission_update_id=update.id,
                                             decision="verified", verified_by=SUPERVISOR_ID))
        self.assertEqual(self._count_queries(), baseline)


if __name__ == "__main__":
    unittest.main()
