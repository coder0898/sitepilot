"""U3: activation copies applicable approvals into the execution layer.

Until this unit there was nothing in the execution layer to approve, so a
gate could be recorded as approved and release no work at all. The backfill
half is the part that silently matters: without it every already-activated
project reports each gate-blocked task as startable, because the readiness
advisor reads execution gate rows and finds none.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import (
    BaselineTask, ExecutionExcludedDependency, ExecutionGate, ExecutionGateTask,
    ProjectBaseline, Task, TaskDependency,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateApplicabilityDecision,
    V2ProjectExternalGateTask, V2ProjectMembership, V2ProjectTask, V2ProjectTaskDependency,
)
from app.routes.projects_v2 import router
from app.services.execution_gate_backfill import ExecutionGateBackfillService
from app.services.project_schedule_dates import required_by_at
from app.template_models import (
    V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask,
    V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw): return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
START = date(2026, 8, 1)

EXECUTION_TABLES = (ExecutionGate.__table__, ExecutionGateTask.__table__, ExecutionExcludedDependency.__table__)


class ExecutionGateInstantiationTests(unittest.TestCase):
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
                      BaselineTask.__table__, Task.__table__, TaskDependency.__table__,
                      V2TemplateExternalGate.__table__, V2TemplateExternalGateTask.__table__,
                      V2ProjectExternalGateTask.__table__, V2ProjectExternalGateApplicabilityDecision.__table__,
                      *EXECUTION_TABLES):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self.app = FastAPI(); self.app.include_router(router)

        def override_db():
            with self.Session() as session: yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.client = TestClient(self.app)

    def tearDown(self): self.client.close(); self.engine.dispose()

    def _seed(self):
        """T001 mandatory, T002 conditional (excluded at review), T003
        mandatory and depending on T002 - the excluded-predecessor case.

        Three template gates: E001 exact-mapped to T001, E002 exact-mapped
        to the conditional T002, and E003 broad-text with no task mapping
        at all.
        """
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

            tasks = {}
            for i, (code, applicability) in enumerate([("T001", "mandatory"), ("T002", "conditional"), ("T003", "mandatory")], start=1):
                tt = V2TemplateTask(template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                                    applicability=applicability, task_class="standard", task_kind="work",
                                    evidence_required=False, duration_days=1, phase="Setup", category="Site")
                session.add(tt); session.flush(); tasks[code] = tt

            # T002 (conditional, about to be excluded) -> T003 (mandatory).
            session.add(V2TemplateTaskDependency(
                template_version_id=published.id, predecessor_task_id=tasks["T002"].id,
                successor_task_id=tasks["T003"].id, dependency_type="finish_to_start", blocking=True,
                rule_text="T003 waits on T002.", sequence_no=1))

            for seq, (code, name, classification, mapped) in enumerate([
                ("E001", "Landlord approval", "exact", "T001"),
                ("E002", "HVAC sign-off", "exact", "T002"),
                ("E003", "Relevant procurement tasks", "broad_text", None),
            ], start=1):
                gate = V2TemplateExternalGate(
                    template_version_id=published.id, code=code, sequence_no=seq, approval_name=name,
                    external_party="Landlord", mapping_classification=classification,
                    broad_mapping_text="Relevant procurement and finish tasks" if classification == "broad_text" else None,
                    # A non-exact gate must declare it needs configuring -
                    # ck_v2_template_external_gates_configuration.
                    requires_configuration=classification != "exact",
                    required_by_type="project_day", required_by_value="5")
                session.add(gate); session.flush()
                if mapped:
                    session.add(V2TemplateExternalGateTask(gate_id=gate.id, template_task_id=tasks[mapped].id))
            self.published_version_id = published.id

    # ---- driving a project to activation ---------------------------------

    def create_and_generate(self):
        payload = {"project_name": "Futurex Fitout", "client": "Example Client", "location": "Mumbai",
                   "proposed_start_date": START.isoformat(), "target_handover_date": "2026-09-14",
                   "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
                   "template_version_id": str(self.published_version_id)}
        created = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        pid = created.json()["id"]
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-tasks").status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-dependencies").status_code, 200)
        gates = self.client.post(f"/api/v2/projects/{pid}/generate-gates")
        self.assertEqual(gates.status_code, 200, gates.text)
        return pid

    def exclude_conditional_task(self, pid):
        with self.Session() as session:
            task = session.scalar(select(V2ProjectTask).where(
                V2ProjectTask.project_id == uuid.UUID(pid), V2ProjectTask.original_code == "T002"))
        response = self.client.post(
            f"/api/v2/projects/{pid}/tasks/{task.id}/applicability-decisions",
            json={"decision": "excluded", "reason": "No HVAC scope on this project."})
        self.assertEqual(response.status_code, 200, response.text)

    def decide_gates(self, pid, not_applicable_codes=()):
        with self.Session() as session:
            gates = session.scalars(select(V2ProjectExternalGate).where(
                V2ProjectExternalGate.project_id == uuid.UUID(pid))).all()
            gate_ids = {g.original_code: g.id for g in gates}
        for code, gate_id in gate_ids.items():
            body = ({"decision": "not_applicable", "reason": "Out of scope for this project."}
                    if code in not_applicable_codes else {"decision": "applicable"})
            response = self.client.post(f"/api/v2/projects/{pid}/gates/{gate_id}/applicability-decisions", json=body)
            self.assertEqual(response.status_code, 200, f"{code}: {response.text}")
        return gate_ids

    def activate(self, pid):
        response = self.client.post(f"/api/v2/projects/{pid}/activate", json={"reason": "Go live."})
        self.assertEqual(response.status_code, 200, response.text)
        return pid

    def execution_gates(self, pid):
        with self.Session() as session:
            return {g.original_code: g for g in session.scalars(
                select(ExecutionGate).where(ExecutionGate.project_id == uuid.UUID(pid))).all()}

    def linked_task_codes(self, pid, code):
        with self.Session() as session:
            rows = session.execute(
                select(Task.original_code)
                .join(ExecutionGateTask, ExecutionGateTask.task_id == Task.id)
                .join(ExecutionGate, ExecutionGate.id == ExecutionGateTask.execution_gate_id)
                .where(ExecutionGate.project_id == uuid.UUID(pid), ExecutionGate.original_code == code)
            ).all()
            return {r[0] for r in rows}

    # ---- instantiation ----------------------------------------------------

    def test_activation_instantiates_one_gate_per_applicable_planning_gate(self):
        pid = self.create_and_generate()
        self.decide_gates(pid, not_applicable_codes={"E002"})
        self.activate(pid)

        gates = self.execution_gates(pid)
        self.assertEqual(set(gates), {"E001", "E003"})
        self.assertNotIn("E002", gates, "a gate marked not applicable must not reach the execution layer")
        self.assertEqual(gates["E001"].approval_name, "Landlord approval")
        self.assertEqual(gates["E001"].status, "pending_review")
        self.assertEqual(gates["E001"].accountable_pm_user_id, PM_ID)

    def test_gate_task_links_resolve_to_execution_task_ids(self):
        pid = self.create_and_generate()
        self.decide_gates(pid)
        self.activate(pid)
        self.assertEqual(self.linked_task_codes(pid, "E001"), {"T001"})

    def test_a_gate_with_no_task_links_instantiates_and_links_nothing(self):
        """The six broad-text gates in the real template take this path.
        They must exist to be surfaced as unresolved, not be dropped."""
        pid = self.create_and_generate()
        self.decide_gates(pid)
        self.activate(pid)
        self.assertIn("E003", self.execution_gates(pid))
        self.assertEqual(self.linked_task_codes(pid, "E003"), set())
        self.assertEqual(self.execution_gates(pid)["E003"].mapping_classification, "broad_text")

    def test_a_link_whose_task_was_excluded_produces_no_row(self):
        pid = self.create_and_generate()
        self.exclude_conditional_task(pid)
        self.decide_gates(pid)
        self.activate(pid)
        # E002 maps only to T002, which is out of scope, so the gate exists
        # but holds nothing back.
        self.assertIn("E002", self.execution_gates(pid))
        self.assertEqual(self.linked_task_codes(pid, "E002"), set())

    def test_the_required_by_day_resolves_to_a_real_date(self):
        pid = self.create_and_generate()
        self.decide_gates(pid)
        self.activate(pid)
        gate = self.execution_gates(pid)["E001"]
        self.assertEqual(gate.required_by_at.replace(tzinfo=timezone.utc),
                         required_by_at(START, "project_day", "5"))

    def test_a_malformed_required_by_does_not_take_activation_down(self):
        """Gate content is authored outside this codebase. One bad value in
        32 gates must not stop a project going live."""
        for bad in ("not-a-day", "", None):
            with self.subTest(value=bad):
                self.assertIsNone(required_by_at(START, "project_day", bad))
        self.assertIsNone(required_by_at(START, "date", "31st of never"))

    def test_the_baseline_gate_count_is_unchanged_by_this_unit(self):
        pid = self.create_and_generate()
        self.decide_gates(pid, not_applicable_codes={"E002"})
        self.activate(pid)
        with self.Session() as session:
            baseline = session.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == uuid.UUID(pid)))
            self.assertEqual(baseline.gate_count, 2)

    def test_an_execution_gate_accepts_all_five_statuses_and_rejects_a_sixth(self):
        pid = self.create_and_generate()
        self.decide_gates(pid)
        self.activate(pid)
        gate_id = self.execution_gates(pid)["E001"].id
        for status in ("not_required", "pending_review", "submitted", "approved", "rejected"):
            with self.subTest(status=status):
                with self.Session.begin() as session:
                    session.get(ExecutionGate, gate_id).status = status
                with self.Session() as session:
                    self.assertEqual(session.get(ExecutionGate, gate_id).status, status)
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as session:
                session.get(ExecutionGate, gate_id).status = "pending"

    # ---- the excluded-predecessor snapshot --------------------------------

    def test_an_edge_dropped_for_an_excluded_predecessor_is_recorded(self):
        """Covers AE9. Baseline lock keeps only edges with both endpoints
        included, so T003 would otherwise look unblocked with no reason."""
        pid = self.create_and_generate()
        self.exclude_conditional_task(pid)
        self.decide_gates(pid)
        self.activate(pid)

        with self.Session() as session:
            recorded = session.scalars(select(ExecutionExcludedDependency).where(
                ExecutionExcludedDependency.project_id == uuid.UUID(pid))).all()
            self.assertEqual(len(recorded), 1)
            edge = recorded[0]
            self.assertEqual(edge.excluded_predecessor_code, "T002")
            self.assertEqual(edge.dependency_type, "finish_to_start")
            self.assertEqual(edge.rule_text, "T003 waits on T002.")
            successor = session.get(Task, edge.successor_task_id)
            self.assertEqual(successor.original_code, "T003")

            # The guard must not see it. Creating a TaskDependency row here
            # would change what the portal permits, on an edge nobody has
            # validated against real site practice.
            self.assertEqual(session.scalar(select(func.count()).select_from(TaskDependency)), 0)

    def test_no_excluded_edge_is_recorded_when_nothing_was_dropped(self):
        pid = self.create_and_generate()
        self.decide_gates(pid)
        self.activate(pid)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ExecutionExcludedDependency)), 0)
            # Both endpoints included, so the edge is a real dependency.
            self.assertEqual(session.scalar(select(func.count()).select_from(TaskDependency)), 1)

    # ---- the backfill ------------------------------------------------------

    def _strip_execution_gates(self, pid):
        """Reproduce a project activated before U3 existed."""
        with self.Session.begin() as session:
            for row in session.scalars(select(ExecutionGateTask)).all(): session.delete(row)
            for row in session.scalars(select(ExecutionGate)).all(): session.delete(row)
            for row in session.scalars(select(ExecutionExcludedDependency)).all(): session.delete(row)

    def test_the_backfill_populates_a_project_activated_before_this_unit(self):
        pid = self.create_and_generate()
        self.exclude_conditional_task(pid)
        self.decide_gates(pid)
        self.activate(pid)
        self._strip_execution_gates(pid)
        self.assertEqual(self.execution_gates(pid), {})

        with self.Session() as session:
            result = ExecutionGateBackfillService(session).backfill_project(
                session.get(V2Project, uuid.UUID(pid)), ADMIN_ID)
        self.assertEqual(result.gates_created, 3)
        self.assertEqual(result.excluded_edges_recorded, 1)
        self.assertEqual(set(self.execution_gates(pid)), {"E001", "E002", "E003"})
        self.assertEqual(self.linked_task_codes(pid, "E001"), {"T001"})

    def test_running_the_backfill_twice_changes_nothing(self):
        pid = self.create_and_generate()
        self.decide_gates(pid)
        self.activate(pid)
        with self.Session() as session:
            project = session.get(V2Project, uuid.UUID(pid))
            first = ExecutionGateBackfillService(session).backfill_project(project, ADMIN_ID)
            second = ExecutionGateBackfillService(session).backfill_project(project, ADMIN_ID)
        # Activation already created them, so the backfill creates none.
        self.assertEqual((first.gates_created, second.gates_created), (0, 0))
        self.assertEqual(len(self.execution_gates(pid)), 3)

    def test_a_backfill_interrupted_partway_and_rerun_produces_no_duplicates(self):
        """Proves the unique key rather than the sequencing - a partial run
        followed by a full one is the realistic operational failure."""
        pid = self.create_and_generate()
        self.decide_gates(pid)
        self.activate(pid)
        with self.Session.begin() as session:
            # Simulate a run that got one gate in before dying.
            for row in session.scalars(select(ExecutionGateTask)).all(): session.delete(row)
            for row in session.scalars(
                    select(ExecutionGate).where(ExecutionGate.original_code != "E001")).all():
                session.delete(row)
        with self.Session() as session:
            result = ExecutionGateBackfillService(session).backfill_project(
                session.get(V2Project, uuid.UUID(pid)), ADMIN_ID)
        self.assertEqual(result.gates_created, 2)
        gates = self.execution_gates(pid)
        self.assertEqual(len(gates), 3)
        self.assertEqual(len({g.original_code for g in gates.values()}), 3)

    def test_the_backfill_skips_a_project_that_was_never_activated(self):
        pid = self.create_and_generate()
        self.decide_gates(pid)
        with self.Session() as session:
            result = ExecutionGateBackfillService(session).backfill_project(
                session.get(V2Project, uuid.UUID(pid)), ADMIN_ID)
        self.assertEqual(result.gates_created, 0)
        self.assertIsNotNone(result.skipped_reason)

    def test_the_backfill_audits_what_it_touched(self):
        pid = self.create_and_generate()
        self.decide_gates(pid)
        self.activate(pid)
        self._strip_execution_gates(pid)
        with self.Session() as session:
            ExecutionGateBackfillService(session).backfill_project(session.get(V2Project, uuid.UUID(pid)), ADMIN_ID)
        with self.Session() as session:
            event_row = session.scalar(select(V2AuditEvent).where(
                V2AuditEvent.action == "PROJECT_EXECUTION_GATES_BACKFILLED"))
            self.assertIsNotNone(event_row)
            self.assertEqual(event_row.after_json["gates_created"], 3)
            self.assertTrue(event_row.reason)

    def test_the_backfill_module_registers_no_router(self):
        import app.services.execution_gate_backfill as backfill_module
        self.assertFalse([name for name in dir(backfill_module) if "router" in name.lower()])


if __name__ == "__main__":
    unittest.main()
