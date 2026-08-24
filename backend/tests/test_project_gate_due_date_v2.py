"""Phase 5: resolving external-approval due dates.

Pins the pure conversion rule (`resolve_gate_due_at`), that activation
(`ProjectApprovalInstantiationService.instantiate_for_project`, via
`project_baseline.py`) writes `due_at` onto the `ProjectExternalApproval` it
builds, and that `ProjectGateDueDateService.backfill()` populates the column
for approvals that predate this unit without touching one that already has
a value.

Never invents a date: a gate with no `required_by_type` (or an unresolvable
`project_day` rule with no `project.start_date` yet) must resolve to `None`,
not a guess.
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
from app.services.project_gate_due_date import ProjectGateDueDateService, resolve_gate_due_at
from app.template_models import V2Template, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class ResolveGateDueAtTests(unittest.TestCase):
    """The pure conversion, with no database in the way."""

    START = date(2026, 8, 1)

    def test_a_date_type_gate_resolves_to_that_exact_date(self):
        due_at = resolve_gate_due_at("date", "2026-09-14", self.START)
        self.assertEqual(due_at, date(2026, 9, 14))

    def test_a_project_day_type_gate_resolves_via_the_day_offset_resolver(self):
        # Day 1 is the start date itself (KTD4), matching
        # project_schedule_dates.py's planned_date_for_day.
        due_at = resolve_gate_due_at("project_day", "10", self.START)
        self.assertEqual(due_at, date(2026, 8, 10))

    def test_a_null_required_by_type_resolves_to_none(self):
        self.assertIsNone(resolve_gate_due_at(None, None, self.START))

    def test_a_null_required_by_value_resolves_to_none(self):
        self.assertIsNone(resolve_gate_due_at("date", None, self.START))

    def test_project_day_with_no_project_start_date_resolves_to_none(self):
        """Never invented: activation can run before start_date exists on
        the row being built, and this must not raise or guess."""
        self.assertIsNone(resolve_gate_due_at("project_day", "10", None))

    def test_an_unrecognized_required_by_type_resolves_to_none(self):
        self.assertIsNone(resolve_gate_due_at("something_else", "10", self.START))

    def test_a_malformed_date_string_resolves_to_none_rather_than_raising(self):
        self.assertIsNone(resolve_gate_due_at("date", "not-a-date", self.START))

    def test_a_malformed_project_day_string_resolves_to_none_rather_than_raising(self):
        self.assertIsNone(resolve_gate_due_at("project_day", "not-a-number", self.START))


class ProjectGateDueDateIntegrationTests(unittest.TestCase):
    """Activation (via `ProjectApprovalInstantiationService`) and the
    backfill, against the same SQLite-with-ATTACHed-schema harness as
    `test_project_approval_instantiation_v2.py`."""

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
        self.template_version_id = uuid.uuid4()
        self.pm_id = uuid.uuid4()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # ---- fixtures ------------------------------------------------------

    def _project(self, start_date: date | None = date(2026, 8, 1)) -> V2Project:
        self._sequence += 1
        project = V2Project(
            id=uuid.uuid4(), code=f"P{self._sequence:03d}", name="Project", client_name="Client",
            site_address="Somewhere", start_date=start_date, status="active",
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

    def _gate(self, project, *, required_by_type=None, required_by_value=None) -> V2ProjectExternalGate:
        self._sequence += 1
        gate = V2ProjectExternalGate(
            id=uuid.uuid4(), project_id=project.id,
            original_code=f"E{self._sequence:03d}", template_sequence=self._sequence,
            approval_name=f"Approval {self._sequence}",
            mapping_classification="unmapped",
            applicability_state="applicable", blocking=True, accountable_pm_user_id=self.pm_id,
            source_type="project_manual",
            required_by_type=required_by_type, required_by_value=required_by_value,
        )
        self.db.add(gate)
        self.db.flush()
        return gate

    def _approval_for(self, project, gate) -> ProjectExternalApproval:
        return self.db.scalar(
            select(ProjectExternalApproval).where(
                ProjectExternalApproval.project_id == project.id,
                ProjectExternalApproval.project_gate_id == gate.id,
            )
        )

    # ---- activation wiring ----------------------------------------------

    def test_a_date_type_gate_populates_due_at_on_activation(self):
        project = self._project(date(2026, 8, 1))
        self._baseline(project)
        gate = self._gate(project, required_by_type="date", required_by_value="2026-09-14")

        self.service.instantiate_for_project(project)
        approval = self._approval_for(project, gate)
        self.assertEqual(approval.due_at, date(2026, 9, 14))

    def test_a_project_day_type_gate_resolves_against_project_start_date_on_activation(self):
        project = self._project(date(2026, 8, 1))
        self._baseline(project)
        gate = self._gate(project, required_by_type="project_day", required_by_value="10")

        self.service.instantiate_for_project(project)
        approval = self._approval_for(project, gate)
        self.assertEqual(approval.due_at, date(2026, 8, 10))

    def test_a_gate_with_no_required_by_type_leaves_due_at_null(self):
        project = self._project(date(2026, 8, 1))
        self._baseline(project)
        gate = self._gate(project)  # manually-created gate, no rule set

        self.service.instantiate_for_project(project)
        approval = self._approval_for(project, gate)
        self.assertIsNone(approval.due_at)

    # ---- backfill ---------------------------------------------------------

    def test_backfill_populates_due_at_for_an_approval_that_predates_this_unit(self):
        project = self._project(date(2026, 8, 1))
        self._baseline(project)
        gate = self._gate(project, required_by_type="date", required_by_value="2026-09-14")
        # Simulate a pre-Phase-5 approval: instantiated before due_at existed,
        # so it was written without one.
        approval = ProjectExternalApproval(
            id=uuid.uuid4(), project_id=project.id, project_gate_id=gate.id,
            status="unassigned", blocking=True, coverage_state="unresolved",
        )
        self.db.add(approval)
        self.db.flush()

        report = ProjectGateDueDateService(self.db).backfill()
        self.assertEqual(report["approvals_updated"], 1)
        self.db.refresh(approval)
        self.assertEqual(approval.due_at, date(2026, 9, 14))

    def test_backfill_does_not_overwrite_an_approval_that_already_has_a_due_date(self):
        project = self._project(date(2026, 8, 1))
        self._baseline(project)
        gate = self._gate(project, required_by_type="date", required_by_value="2026-09-14")
        approval = ProjectExternalApproval(
            id=uuid.uuid4(), project_id=project.id, project_gate_id=gate.id,
            status="unassigned", blocking=True, coverage_state="unresolved",
            due_at=date(2026, 1, 1),
        )
        self.db.add(approval)
        self.db.flush()

        report = ProjectGateDueDateService(self.db).backfill()
        self.assertEqual(report["approvals_updated"], 0)
        self.db.refresh(approval)
        self.assertEqual(approval.due_at, date(2026, 1, 1))

    def test_backfill_leaves_an_unresolvable_approval_untouched(self):
        """A manually-created gate with no rule at all resolves to None
        both at activation and on a later backfill pass - never invented."""
        project = self._project(date(2026, 8, 1))
        self._baseline(project)
        gate = self._gate(project)
        approval = ProjectExternalApproval(
            id=uuid.uuid4(), project_id=project.id, project_gate_id=gate.id,
            status="unassigned", blocking=True, coverage_state="unresolved",
        )
        self.db.add(approval)
        self.db.flush()

        report = ProjectGateDueDateService(self.db).backfill()
        self.assertEqual(report["approvals_updated"], 0)
        self.db.refresh(approval)
        self.assertIsNone(approval.due_at)

    def test_a_second_backfill_run_updates_nothing(self):
        project = self._project(date(2026, 8, 1))
        self._baseline(project)
        gate = self._gate(project, required_by_type="date", required_by_value="2026-09-14")
        approval = ProjectExternalApproval(
            id=uuid.uuid4(), project_id=project.id, project_gate_id=gate.id,
            status="unassigned", blocking=True, coverage_state="unresolved",
        )
        self.db.add(approval)
        self.db.flush()

        first = ProjectGateDueDateService(self.db).backfill()
        self.assertEqual(first["approvals_updated"], 1)
        second = ProjectGateDueDateService(self.db).backfill()
        self.assertEqual(second["approvals_updated"], 0)

    def test_backfill_can_be_scoped_to_one_project(self):
        first_project = self._project(date(2026, 8, 1))
        second_project = self._project(date(2026, 9, 1))
        self._baseline(first_project)
        self._baseline(second_project)
        first_gate = self._gate(first_project, required_by_type="date", required_by_value="2026-09-14")
        second_gate = self._gate(second_project, required_by_type="date", required_by_value="2026-10-14")
        first_approval = ProjectExternalApproval(
            id=uuid.uuid4(), project_id=first_project.id, project_gate_id=first_gate.id,
            status="unassigned", blocking=True, coverage_state="unresolved",
        )
        second_approval = ProjectExternalApproval(
            id=uuid.uuid4(), project_id=second_project.id, project_gate_id=second_gate.id,
            status="unassigned", blocking=True, coverage_state="unresolved",
        )
        self.db.add_all([first_approval, second_approval])
        self.db.flush()

        report = ProjectGateDueDateService(self.db).backfill(project_id=first_project.id)
        self.assertEqual(report["approvals_scanned"], 1)
        self.db.refresh(first_approval)
        self.db.refresh(second_approval)
        self.assertEqual(first_approval.due_at, date(2026, 9, 14))
        self.assertIsNone(second_approval.due_at)


if __name__ == "__main__":
    unittest.main()
