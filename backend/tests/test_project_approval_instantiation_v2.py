"""U8: instantiating planning-layer gates as execution-layer approvals.

Activation is the one moment the execution layer may read the planning layer,
and it copies across everything readiness will later need - coverage,
blocking, prose - precisely so readiness never has to go back for it (KTD8).

The rules pinned here:

- Only `applicable` gates become approvals. A gate still under review, or one
  ruled not applicable to this project, has nothing to grant.
- Coverage is resolved from *explicit* task references only. A `broad_text`
  gate describes its coverage in prose and an `unmapped` gate names nothing;
  neither is parsed, guessed at, expanded to every task, or quietly reduced
  to none. Both produce an approval marked `unresolved` carrying whatever
  prose there was, for a human to scope (R10).
- The PM's `blocking` decision travels with the approval. A non-blocking gate
  arriving as blocking would stop every task it covers, the opposite of what
  was set.
- Re-running is safe. A gate that already has an approval is skipped whole:
  its status may since have been decided, and re-deriving would overwrite a
  real decision.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import (
    BaselineTask,
    ProjectBaseline,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
)
from app.models import User
from app.project_models import (
    V2Project,
    V2ProjectExternalGate,
    V2ProjectExternalGateTask,
    V2ProjectTask,
)
from app.services.project_baseline import ProjectApprovalInstantiationService
from app.template_models import V2Template, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class ProjectApprovalInstantiationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # The gate table's broad-text check uses Postgres's btrim().
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

        for table in (
            User.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            V2ProjectTask.__table__,
            V2ProjectExternalGate.__table__,
            V2ProjectExternalGateTask.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
        ):
            table.create(bind=self.engine, checkfirst=True)

        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()
        self.service = ProjectApprovalInstantiationService(self.db)
        self._sequence = 0
        # Both columns are NOT NULL but irrelevant to what this unit does;
        # SQLite does not enforce the foreign keys, so a bare id satisfies
        # the schema without dragging in template and user fixtures.
        self.template_version_id = uuid.uuid4()
        self.pm_id = uuid.uuid4()
        self.project = self._project()
        self.baseline = self._baseline(self.project)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # ---- fixtures ------------------------------------------------------

    def _project(self) -> V2Project:
        project = V2Project(
            id=uuid.uuid4(), code="P001", name="Project", client_name="Client",
            site_address="Somewhere", start_date=date(2026, 8, 1), status="active",
            created_by=uuid.uuid4(),
        )
        self.db.add(project)
        self.db.flush()
        return project

    def _baseline(self, project) -> ProjectBaseline:
        baseline = ProjectBaseline(
            id=uuid.uuid4(), project_id=project.id, task_count=1,
            dependency_count=0, gate_count=0, locked_by=uuid.uuid4(),
        )
        self.db.add(baseline)
        self.db.flush()
        return baseline

    def _task_pair(self) -> tuple[V2ProjectTask, Task]:
        """A planning task and the execution task instantiated from it."""
        self._sequence += 1
        code = f"T{self._sequence:03d}"
        planning = V2ProjectTask(
            id=uuid.uuid4(), project_id=self.project.id, original_code=code,
            template_sequence=self._sequence, title=f"Task {code}",
            schedule_classification="execution", applicability="mandatory",
            source_type="project_manual", included=True, template_version_id=self.template_version_id,
        )
        self.db.add(planning)
        self.db.flush()
        baseline_task = BaselineTask(
            id=uuid.uuid4(), baseline_id=self.baseline.id, project_id=self.project.id,
            project_task_id=planning.id, original_code=code,
            template_sequence=self._sequence, title=f"Task {code}",
            schedule_classification="execution", applicability="mandatory",
            content_hash="hash",
        )
        self.db.add(baseline_task)
        self.db.flush()
        execution = Task(
            id=uuid.uuid4(), project_id=self.project.id, baseline_id=self.baseline.id,
            baseline_task_id=baseline_task.id, original_code=code,
            template_sequence=self._sequence, title=f"Task {code}",
            schedule_classification="execution", applicability="mandatory",
            lifecycle_status="planned",
        )
        self.db.add(execution)
        self.db.flush()
        return planning, execution

    def _gate(self, classification="exact", *, applicability="applicable",
              blocking=True, broad_text=None) -> V2ProjectExternalGate:
        self._sequence += 1
        gate = V2ProjectExternalGate(
            id=uuid.uuid4(), project_id=self.project.id,
            original_code=f"E{self._sequence:03d}", template_sequence=self._sequence,
            approval_name=f"Approval {self._sequence}",
            mapping_classification=classification, broad_mapping_text=broad_text,
            applicability_state=applicability, blocking=blocking, accountable_pm_user_id=self.pm_id,
            source_type="project_manual",
        )
        self.db.add(gate)
        self.db.flush()
        return gate

    def _cover(self, gate, planning_task) -> None:
        self.db.add(V2ProjectExternalGateTask(
            id=uuid.uuid4(), project_gate_id=gate.id, project_task_id=planning_task.id,
        ))
        self.db.flush()

    def _approvals(self) -> list[ProjectExternalApproval]:
        return list(self.db.scalars(
            select(ProjectExternalApproval)
            .where(ProjectExternalApproval.project_id == self.project.id)
        ))

    def _links(self, approval) -> list[ProjectExternalApprovalTask]:
        return list(self.db.scalars(
            select(ProjectExternalApprovalTask)
            .where(ProjectExternalApprovalTask.approval_id == approval.id)
        ))

    # ---- which gates become approvals ----------------------------------

    def test_an_applicable_gate_becomes_an_unassigned_approval(self):
        self._gate()
        report = self.service.instantiate_for_project(self.project)
        self.assertEqual(report["approvals_created"], 1)
        approval = self._approvals()[0]
        self.assertEqual(approval.status, "unassigned")
        self.assertIsNone(approval.decided_by)
        self.assertIsNone(approval.decided_at)

    def test_a_gate_not_applicable_to_this_project_is_skipped(self):
        self._gate(applicability="not_applicable")
        report = self.service.instantiate_for_project(self.project)
        self.assertEqual(report["approvals_created"], 0)
        self.assertEqual(self._approvals(), [])

    def test_a_gate_still_pending_review_is_skipped(self):
        self._gate(applicability="pending_review")
        self.service.instantiate_for_project(self.project)
        self.assertEqual(self._approvals(), [])

    # ---- coverage -------------------------------------------------------

    def test_an_exact_gate_links_exactly_the_tasks_it_names(self):
        planning_a, execution_a = self._task_pair()
        planning_b, execution_b = self._task_pair()
        self._task_pair()  # a third task the gate does not name
        gate = self._gate("exact")
        self._cover(gate, planning_a)
        self._cover(gate, planning_b)

        self.service.instantiate_for_project(self.project)
        approval = self._approvals()[0]
        self.assertEqual(approval.coverage_state, "exact")
        covered = {link.task_id for link in self._links(approval)}
        self.assertEqual(covered, {execution_a.id, execution_b.id})

    def test_a_broad_text_gate_is_unresolved_and_keeps_its_prose(self):
        planning, _ = self._task_pair()
        gate = self._gate("broad_text", broad_text="Relevant procurement and finish tasks")
        self._cover(gate, planning)

        report = self.service.instantiate_for_project(self.project)
        approval = self._approvals()[0]
        self.assertEqual(approval.coverage_state, "unresolved")
        self.assertEqual(approval.coverage_text, "Relevant procurement and finish tasks")
        self.assertEqual(report["unresolved_count"], 1)

    def test_an_unmapped_gate_is_unresolved(self):
        self._gate("unmapped")
        self.service.instantiate_for_project(self.project)
        self.assertEqual(self._approvals()[0].coverage_state, "unresolved")

    def test_an_unresolved_approval_links_no_tasks(self):
        """Not an expansion to none: `coverage_state` says the scope is
        unknown, which is why it is a stored column rather than something
        read off the absence of links."""
        planning, _ = self._task_pair()
        gate = self._gate("broad_text", broad_text="Affected activities")
        self._cover(gate, planning)

        self.service.instantiate_for_project(self.project)
        approval = self._approvals()[0]
        self.assertEqual(self._links(approval), [])
        self.assertEqual(approval.coverage_state, "unresolved")

    def test_a_named_task_excluded_from_the_baseline_is_skipped_without_losing_exactness(self):
        """The template was explicit; the task simply is not in this plan."""
        planning_in, execution_in = self._task_pair()
        excluded = V2ProjectTask(
            id=uuid.uuid4(), project_id=self.project.id, original_code="T900",
            template_sequence=900, title="Excluded", schedule_classification="execution",
            applicability="conditional", source_type="project_manual", included=False,
            decision_state="excluded", template_version_id=self.template_version_id,
        )
        self.db.add(excluded)
        self.db.flush()
        gate = self._gate("exact")
        self._cover(gate, planning_in)
        self._cover(gate, excluded)

        self.service.instantiate_for_project(self.project)
        approval = self._approvals()[0]
        self.assertEqual(approval.coverage_state, "exact")
        self.assertEqual([link.task_id for link in self._links(approval)], [execution_in.id])

    # ---- the blocking decision travels ---------------------------------

    def test_a_non_blocking_gate_produces_a_non_blocking_approval(self):
        self._gate(blocking=False)
        self.service.instantiate_for_project(self.project)
        self.assertFalse(self._approvals()[0].blocking)

    def test_a_blocking_gate_produces_a_blocking_approval(self):
        self._gate(blocking=True)
        self.service.instantiate_for_project(self.project)
        self.assertTrue(self._approvals()[0].blocking)

    # ---- re-running ------------------------------------------------------

    def test_a_second_run_creates_nothing(self):
        planning, _ = self._task_pair()
        gate = self._gate("exact")
        self._cover(gate, planning)

        self.assertEqual(self.service.instantiate_for_project(self.project)["approvals_created"], 1)
        second = self.service.instantiate_for_project(self.project)
        self.assertEqual(second["approvals_created"], 0)
        self.assertEqual(second["coverage_links_created"], 0)
        self.assertEqual(len(self._approvals()), 1)

    def test_a_second_run_does_not_overwrite_a_recorded_decision(self):
        """The gate is skipped whole once it has an approval - re-deriving
        status would discard a real decision someone made."""
        self._gate()
        self.service.instantiate_for_project(self.project)
        approval = self._approvals()[0]
        approval.status = "approved"
        approval.assigned_to_user_id = uuid.uuid4()
        approval.assigned_by = uuid.uuid4()
        from datetime import datetime, timezone
        approval.assigned_at = datetime.now(timezone.utc)
        approval.decided_by = uuid.uuid4()
        approval.decided_at = datetime.now(timezone.utc)
        self.db.flush()

        self.service.instantiate_for_project(self.project)
        self.assertEqual(self._approvals()[0].status, "approved")

    def test_a_new_gate_added_later_is_picked_up_on_the_next_run(self):
        self._gate()
        self.service.instantiate_for_project(self.project)
        self._gate()
        report = self.service.instantiate_for_project(self.project)
        self.assertEqual(report["approvals_created"], 1)
        self.assertEqual(len(self._approvals()), 2)

    # ---- backfill --------------------------------------------------------

    def test_backfill_instantiates_for_a_project_activated_before_this_unit(self):
        planning, execution = self._task_pair()
        gate = self._gate("exact")
        self._cover(gate, planning)

        report = self.service.backfill()
        self.assertEqual(report["projects_scanned"], 1)
        approval = self._approvals()[0]
        self.assertEqual([link.task_id for link in self._links(approval)], [execution.id])

    def test_re_running_the_backfill_creates_nothing(self):
        self._gate()
        self.service.backfill()
        second = self.service.backfill()
        self.assertEqual(second["projects_updated"], 0)
        self.assertEqual(len(self._approvals()), 1)


if __name__ == "__main__":
    unittest.main()
