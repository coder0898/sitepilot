"""U12: readiness computed from the facts rather than declared by a user.

Pins the three things that make this engine trustworthy:

- **Nothing outside `planned`/`ready` is ever reported ready.** The naive
  ladder reports `submitted`, `verified`, `approval_pending`, `rejected`
  and `cancelled` as ready, which would put cancelled and under-review work
  on an acceleration list. There is a test per status, plus one that fails
  if a tenth lifecycle status is added without an answer.
- **Every unsatisfied fact is reported, not the first** (R4), each naming
  its specific predecessor or approval.
- **Asking the question changes nothing** (R5, KTD1): no write, no
  lifecycle transition, no status move.

There is deliberately no `not_applicable` test: excluded tasks are never
instantiated into `tasks` at all (`ProjectBaselineService.lock_and_instantiate`
filters on `V2ProjectTask.included.is_(True)`), so no execution row exists to
report it against.

Unresolved approval coverage is asserted at project level, not per task: an
unresolved approval has no coverage links, so no task is ever mapped to one.

These assertions run against SQLite built from ORM metadata, so they prove
the service's behaviour, not the migration's constraints.
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

from app.execution_models import (
    TASK_LIFECYCLE_STATUSES,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
    TaskDependency,
    TaskProgressUpdate,
    TaskVerification,
)
from app.models import User
from app.project_models import V2Project, V2ProjectExternalGate
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateVersion
from app.services.task_readiness import (
    AWAITING_APPROVAL,
    AWAITING_VERIFICATION,
    BLOCKED,
    CANCELLED,
    COMPLETED,
    COMPUTED_STATUSES,
    IN_PROGRESS,
    READY,
    REASON_APPROVAL,
    REASON_DEPENDENCY,
    REJECTED,
    TaskReadinessService,
    _STATE_BY_LIFECYCLE_STATUS,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TaskReadinessTestCase(unittest.TestCase):
    """Shared in-memory harness: one project, tasks, edges and approvals."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # The gate tables' broad-text CHECK uses Postgres's btrim(), which
            # SQLite has no builtin for. Same shim as
            # test_project_approval_record_v2.py.
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

        for table in (
            User.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateExternalGate.__table__,
            V2Project.__table__,
            V2ProjectExternalGate.__table__,
            Task.__table__,
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            TaskVerification.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
        ):
            table.create(bind=self.engine, checkfirst=True)

        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()
        self.service = TaskReadinessService(self.db)
        self._sequence = 0
        self.project = self._project()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # ---- fixtures ----------------------------------------------------

    def _project(self) -> V2Project:
        self._sequence += 1
        project = V2Project(
            id=uuid.uuid4(),
            code=f"P{self._sequence:03d}",
            name=f"Project {self._sequence}",
            client_name="Client",
            site_address="Somewhere",
            start_date=date(2026, 8, 1),
            status="active",
            created_by=uuid.uuid4(),
        )
        self.db.add(project)
        self.db.flush()
        return project

    def _task(self, *, status="planned", task_class="standard", task_kind="work", **overrides) -> Task:
        self._sequence += 1
        values = {
            "planned_start_date": None,
            "planned_end_date": None,
        }
        values.update(overrides)
        task = Task(
            id=uuid.uuid4(),
            project_id=self.project.id,
            baseline_id=uuid.uuid4(),
            baseline_task_id=uuid.uuid4(),
            original_code=f"T{self._sequence:03d}",
            template_sequence=self._sequence,
            title=f"Task {self._sequence}",
            schedule_classification="execution",
            applicability="mandatory",
            task_class=task_class,
            task_kind=task_kind,
            lifecycle_status=status,
            **values,
        )
        self.db.add(task)
        self.db.flush()
        return task

    def _dependency(self, predecessor, successor, *, dependency_type="finish_to_start", blocking=True):
        dependency = TaskDependency(
            id=uuid.uuid4(),
            project_id=self.project.id,
            baseline_id=uuid.uuid4(),
            predecessor_task_id=predecessor.id,
            successor_task_id=successor.id,
            dependency_type=dependency_type,
            blocking=blocking,
        )
        self.db.add(dependency)
        self.db.flush()
        return dependency

    def _approval(self, *, status="unassigned", blocking=True, coverage_state="exact", coverage_text=None):
        decided = status in ("approved", "rejected")
        approval = ProjectExternalApproval(
            id=uuid.uuid4(),
            project_id=self.project.id,
            project_gate_id=uuid.uuid4(),
            status=status,
            assigned_to_user_id=uuid.uuid4() if status != "unassigned" else None,
            assigned_by=uuid.uuid4() if status != "unassigned" else None,
            assigned_at=datetime(2026, 8, 9, tzinfo=timezone.utc) if status != "unassigned" else None,
            blocking=blocking,
            coverage_state=coverage_state,
            coverage_text=coverage_text,
            decided_by=uuid.uuid4() if decided else None,
            decided_at=datetime(2026, 8, 10, tzinfo=timezone.utc) if decided else None,
        )
        self.db.add(approval)
        self.db.flush()
        return approval

    def _cover(self, approval, task):
        link = ProjectExternalApprovalTask(
            id=uuid.uuid4(),
            project_id=self.project.id,
            approval_id=approval.id,
            task_id=task.id,
        )
        self.db.add(link)
        self.db.flush()
        return link

    def _readiness(self, task) -> object:
        return self.service.for_project(self.project.id).tasks[task.id]


class DependencyReadinessTests(TaskReadinessTestCase):
    def test_a_task_with_no_dependencies_and_no_approvals_is_ready(self):
        task = self._task()
        readiness = self._readiness(task)
        self.assertEqual(readiness.state, READY)
        self.assertTrue(readiness.is_ready)
        self.assertEqual(readiness.reasons, ())
        self.assertEqual(readiness.advisories, ())

    def test_an_unsatisfied_finish_to_start_predecessor_blocks_and_is_named(self):
        predecessor = self._task(status="in_progress")
        successor = self._task()
        self._dependency(predecessor, successor)
        readiness = self._readiness(successor)
        self.assertEqual(readiness.state, BLOCKED)
        self.assertEqual(len(readiness.reasons), 1)
        reason = readiness.reasons[0]
        self.assertEqual(reason.kind, REASON_DEPENDENCY)
        self.assertEqual(reason.subject_id, predecessor.id)
        self.assertIn(predecessor.original_code, reason.detail)
        self.assertIn(predecessor.title, reason.detail)

    def test_a_completed_finish_to_start_predecessor_releases_the_successor(self):
        predecessor = self._task(status="completed")
        successor = self._task()
        self._dependency(predecessor, successor)
        self.assertEqual(self._readiness(successor).state, READY)

    def test_a_started_start_to_start_predecessor_releases_the_successor(self):
        predecessor = self._task(status="in_progress")
        successor = self._task()
        self._dependency(predecessor, successor, dependency_type="start_to_start")
        readiness = self._readiness(successor)
        self.assertEqual(readiness.state, READY)
        self.assertEqual(readiness.reasons, ())

    def test_an_unstarted_start_to_start_predecessor_still_blocks(self):
        predecessor = self._task(status="ready")
        successor = self._task()
        self._dependency(predecessor, successor, dependency_type="start_to_start")
        self.assertEqual(self._readiness(successor).state, BLOCKED)

    def test_a_cancelled_predecessor_satisfies_the_edge(self):
        """U1's rule: cancelled work can never become satisfied any other
        way, and stranding the successor forever has no recovery."""
        predecessor = self._task(status="cancelled")
        successor = self._task()
        self._dependency(predecessor, successor)
        self.assertEqual(self._readiness(successor).state, READY)

    def test_a_verified_standard_predecessor_with_a_verification_satisfies_the_edge(self):
        """Reuses TaskLifecycleService's per-kind BR-008 rule, verification
        row and all - it is called, not reimplemented."""
        predecessor = self._task(status="verified", task_class="standard")
        successor = self._task()
        self._dependency(predecessor, successor)
        update = TaskProgressUpdate(
            id=uuid.uuid4(),
            task_id=predecessor.id,
            project_id=self.project.id,
            update_type="note",
            note="submitted",
            submitted_by=uuid.uuid4(),
            source="portal",
        )
        self.db.add(update)
        self.db.flush()
        self.db.add(TaskVerification(
            id=uuid.uuid4(),
            task_id=predecessor.id,
            submission_update_id=update.id,
            decision="verified",
            verified_by=uuid.uuid4(),
            verified_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        ))
        self.db.flush()
        self.assertEqual(self._readiness(successor).state, READY)

    def test_a_verified_class_a_predecessor_still_blocks_pending_pm_approval(self):
        predecessor = self._task(status="verified", task_class="class_a")
        successor = self._task()
        self._dependency(predecessor, successor)
        self.assertEqual(self._readiness(successor).state, BLOCKED)

    def test_every_unsatisfied_predecessor_gets_its_own_reason(self):
        first = self._task(status="planned")
        second = self._task(status="in_progress")
        third = self._task(status="ready")
        successor = self._task()
        for predecessor in (first, second, third):
            self._dependency(predecessor, successor)
        readiness = self._readiness(successor)
        self.assertEqual(
            [reason.subject_id for reason in readiness.reasons],
            [first.id, second.id, third.id],
        )

    def test_a_non_blocking_unsatisfied_edge_is_advisory_not_blocking(self):
        predecessor = self._task(status="planned")
        successor = self._task()
        self._dependency(predecessor, successor, blocking=False)
        readiness = self._readiness(successor)
        self.assertEqual(readiness.state, READY)
        self.assertEqual(readiness.reasons, ())
        self.assertEqual(len(readiness.advisories), 1)
        self.assertFalse(readiness.advisories[0].blocking)

    def test_only_the_successor_side_of_an_edge_is_blocked(self):
        predecessor = self._task()
        successor = self._task()
        self._dependency(predecessor, successor)
        self.assertEqual(self._readiness(predecessor).state, READY)
        self.assertEqual(self._readiness(successor).state, BLOCKED)


class ApprovalReadinessTests(TaskReadinessTestCase):
    def test_a_pending_blocking_approval_blocks_and_is_named(self):
        task = self._task()
        approval = self._approval(status="unassigned")
        self._cover(approval, task)
        readiness = self._readiness(task)
        self.assertEqual(readiness.state, BLOCKED)
        self.assertEqual(len(readiness.reasons), 1)
        reason = readiness.reasons[0]
        self.assertEqual(reason.kind, REASON_APPROVAL)
        self.assertEqual(reason.subject_id, approval.id)
        self.assertIn(str(approval.id), reason.detail)
        self.assertIn("unassigned", reason.detail)

    def test_a_rejected_blocking_approval_blocks(self):
        task = self._task()
        approval = self._approval(status="rejected")
        self._cover(approval, task)
        readiness = self._readiness(task)
        self.assertEqual(readiness.state, BLOCKED)
        self.assertIn("rejected", readiness.reasons[0].detail)

    def test_an_approved_approval_does_not_block(self):
        task = self._task()
        approval = self._approval(status="approved")
        self._cover(approval, task)
        readiness = self._readiness(task)
        self.assertEqual(readiness.state, READY)
        self.assertEqual(readiness.reasons, ())
        self.assertEqual(readiness.advisories, ())

    def test_a_pending_non_blocking_approval_does_not_block(self):
        """The PM deliberately marked this gate non-blocking; reporting every
        task it covers as blocked would override that decision."""
        task = self._task()
        approval = self._approval(status="unassigned", blocking=False)
        self._cover(approval, task)
        readiness = self._readiness(task)
        self.assertEqual(readiness.state, READY)
        self.assertEqual(readiness.reasons, ())
        self.assertEqual(len(readiness.advisories), 1)
        self.assertEqual(readiness.advisories[0].subject_id, approval.id)

    def test_an_approval_only_blocks_the_tasks_it_actually_covers(self):
        covered = self._task()
        uncovered = self._task()
        approval = self._approval(status="unassigned")
        self._cover(approval, covered)
        self.assertEqual(self._readiness(covered).state, BLOCKED)
        self.assertEqual(self._readiness(uncovered).state, READY)

    def test_every_unapproved_approval_gets_its_own_reason(self):
        task = self._task()
        for status in ("unassigned", "rejected"):
            self._cover(self._approval(status=status), task)
        self._cover(self._approval(status="approved"), task)
        readiness = self._readiness(task)
        self.assertEqual(len(readiness.reasons), 2)

    def test_a_dependency_and_an_approval_both_report_their_own_reason(self):
        predecessor = self._task(status="planned")
        task = self._task()
        self._dependency(predecessor, task)
        approval = self._approval(status="unassigned")
        self._cover(approval, task)
        readiness = self._readiness(task)
        self.assertEqual(readiness.state, BLOCKED)
        self.assertEqual(
            {reason.kind for reason in readiness.reasons},
            {REASON_DEPENDENCY, REASON_APPROVAL},
        )
        self.assertEqual(
            {reason.subject_id for reason in readiness.reasons},
            {predecessor.id, approval.id},
        )

    def test_approving_the_last_outstanding_approval_flips_the_task_to_ready(self):
        task = self._task()
        approval = self._approval(status="unassigned")
        self._cover(approval, task)
        self.assertEqual(self._readiness(task).state, BLOCKED)
        approval.status = "approved"
        approval.assigned_to_user_id = uuid.uuid4()
        approval.assigned_by = uuid.uuid4()
        approval.assigned_at = datetime(2026, 8, 11, tzinfo=timezone.utc)
        approval.decided_by = uuid.uuid4()
        approval.decided_at = datetime(2026, 8, 12, tzinfo=timezone.utc)
        self.db.flush()
        self.assertEqual(self._readiness(task).state, READY)


class LifecycleStatusReadinessTests(TaskReadinessTestCase):
    """One answer per lifecycle status - nothing falls through to `ready`."""

    def test_every_lifecycle_status_has_an_explicit_answer(self):
        """The guard against a tenth status silently landing in a fallback."""
        self.assertEqual(
            set(TASK_LIFECYCLE_STATUSES),
            COMPUTED_STATUSES | set(_STATE_BY_LIFECYCLE_STATUS),
        )

    def test_a_completed_task_reports_completed_with_no_reasons(self):
        task = self._task(status="completed")
        readiness = self._readiness(task)
        self.assertEqual(readiness.state, COMPLETED)
        self.assertEqual(readiness.reasons, ())
        self.assertEqual(readiness.advisories, ())

    def test_a_cancelled_task_is_never_reported_ready(self):
        task = self._task(status="cancelled")
        readiness = self._readiness(task)
        self.assertEqual(readiness.state, CANCELLED)
        self.assertFalse(readiness.is_ready)
        self.assertEqual(readiness.reasons, ())

    def test_an_in_progress_task_reports_in_progress(self):
        self.assertEqual(self._readiness(self._task(status="in_progress")).state, IN_PROGRESS)

    def test_a_submitted_task_reports_awaiting_verification_not_ready(self):
        readiness = self._readiness(self._task(status="submitted"))
        self.assertEqual(readiness.state, AWAITING_VERIFICATION)
        self.assertFalse(readiness.is_ready)

    def test_a_verified_task_reports_awaiting_approval_not_ready(self):
        readiness = self._readiness(self._task(status="verified"))
        self.assertEqual(readiness.state, AWAITING_APPROVAL)
        self.assertFalse(readiness.is_ready)

    def test_an_approval_pending_task_reports_awaiting_approval_not_ready(self):
        readiness = self._readiness(self._task(status="approval_pending"))
        self.assertEqual(readiness.state, AWAITING_APPROVAL)
        self.assertFalse(readiness.is_ready)

    def test_a_rejected_task_reports_rejected_not_ready(self):
        readiness = self._readiness(self._task(status="rejected"))
        self.assertEqual(readiness.state, REJECTED)
        self.assertFalse(readiness.is_ready)

    def test_no_status_outside_planned_and_ready_is_ever_reported_ready(self):
        tasks = {status: self._task(status=status) for status in TASK_LIFECYCLE_STATUSES}
        # Every task above is blocked by the same pending approval, so a
        # ready answer here could only come from the status branch.
        approval = self._approval(status="unassigned")
        for task in tasks.values():
            self._cover(approval, task)
        result = self.service.for_project(self.project.id)
        for status, task in tasks.items():
            with self.subTest(status=status):
                self.assertFalse(result.tasks[task.id].is_ready)

    def test_a_blocked_planned_task_and_a_blocked_ready_task_answer_alike(self):
        predecessor = self._task(status="planned")
        for status in ("planned", "ready"):
            with self.subTest(status=status):
                successor = self._task(status=status)
                self._dependency(predecessor, successor)
                self.assertEqual(self._readiness(successor).state, BLOCKED)


class ProjectLevelReadinessTests(TaskReadinessTestCase):
    def test_unresolved_approvals_are_surfaced_at_project_level(self):
        task = self._task()
        unresolved = self._approval(
            coverage_state="unresolved",
            coverage_text="All structural works require the municipal NOC.",
        )
        # An unresolved approval has no coverage links, so no task is ever
        # mapped to one - which is exactly why it is a project-level signal.
        self._cover(self._approval(status="approved"), task)
        result = self.service.for_project(self.project.id)
        self.assertEqual(len(result.unresolved_approvals), 1)
        surfaced = result.unresolved_approvals[0]
        self.assertEqual(surfaced.approval_id, unresolved.id)
        self.assertEqual(surfaced.status, "unassigned")
        self.assertEqual(surfaced.coverage_text, "All structural works require the municipal NOC.")
        self.assertEqual(result.tasks[task.id].state, READY)

    def test_an_exact_coverage_approval_is_not_surfaced_as_unresolved(self):
        self._approval(coverage_state="exact")
        self.assertEqual(self.service.for_project(self.project.id).unresolved_approvals, ())

    def test_it_returns_an_entry_for_every_task_in_the_project(self):
        tasks = [self._task() for _ in range(3)]
        result = self.service.for_project(self.project.id)
        self.assertEqual(set(result.tasks), {task.id for task in tasks})

    def test_ready_task_ids_are_the_ready_subset(self):
        ready = self._task()
        blocked = self._task()
        # `in_progress`, so the predecessor is neither ready itself nor
        # satisfying of the finish-to-start edge it sits on.
        self._dependency(self._task(status="in_progress"), blocked)
        self.assertEqual(
            set(self.service.for_project(self.project.id).ready_task_ids()), {ready.id}
        )

    def test_readiness_is_unaffected_by_the_tasks_planned_dates(self):
        """Readiness answers "may this start", not "should it have started".
        Dates belong to U13's variance, not here."""
        undated = self._task()
        long_overdue = self._task(
            planned_start_date=date(2020, 1, 1), planned_end_date=date(2020, 1, 5)
        )
        far_future = self._task(
            planned_start_date=date(2099, 1, 1), planned_end_date=date(2099, 1, 5)
        )
        result = self.service.for_project(self.project.id)
        for task in (undated, long_overdue, far_future):
            with self.subTest(task=task.original_code):
                self.assertEqual(result.tasks[task.id].state, READY)

    def test_computing_readiness_never_changes_a_tasks_lifecycle_status(self):
        """R5/KTD1: readiness is advisory - it must not transition anything."""
        blocked = self._task(status="planned")
        self._dependency(self._task(status="planned"), blocked)
        started = self._task(status="in_progress")
        self.service.for_project(self.project.id)
        self.assertFalse(self.db.dirty)
        self.assertFalse(self.db.new)
        for task in (blocked, started):
            self.db.refresh(task)
        self.assertEqual(blocked.lifecycle_status, "planned")
        self.assertEqual(started.lifecycle_status, "in_progress")

    def test_it_reads_only_the_requested_project(self):
        mine = self._task()
        other_project = self._project()
        stray = Task(
            id=uuid.uuid4(),
            project_id=other_project.id,
            baseline_id=uuid.uuid4(),
            baseline_task_id=uuid.uuid4(),
            original_code="X001",
            template_sequence=1,
            title="Someone else's task",
            schedule_classification="execution",
            applicability="mandatory",
            lifecycle_status="planned",
        )
        self.db.add(stray)
        self.db.flush()
        result = self.service.for_project(self.project.id)
        self.assertEqual(set(result.tasks), {mine.id})


class ReadinessQueryCountTests(TaskReadinessTestCase):
    """A 99-task project must resolve in a bounded number of queries.

    Counted with a `before_cursor_execute` listener rather than timed: a
    timing assertion passes on a fast machine no matter how many queries ran,
    which is the exact regression (a per-task lookup) this pins.
    """

    # Four selects from the service (tasks, edges, approvals, coverage
    # links), plus one for the test's own project row, which the commit
    # below expires and reading `project.id` re-loads.
    QUERY_BUDGET = 5

    def test_a_99_task_project_resolves_within_a_bounded_query_count(self):
        tasks = [self._task() for _ in range(99)]
        for predecessor, successor in zip(tasks, tasks[1:]):
            self._dependency(predecessor, successor)
        approval = self._approval(status="unassigned")
        for task in tasks:
            self._cover(approval, task)
        self.db.commit()

        statements: list[str] = []

        @event.listens_for(self.engine, "before_cursor_execute")
        def count(_conn, _cursor, statement, _params, _context, _executemany):
            statements.append(statement)

        try:
            result = self.service.for_project(self.project.id)
        finally:
            event.remove(self.engine, "before_cursor_execute", count)

        self.assertEqual(len(result.tasks), 99)
        self.assertLessEqual(
            len(statements),
            self.QUERY_BUDGET,
            f"readiness issued {len(statements)} queries for 99 tasks:\n" + "\n".join(statements),
        )

    def test_the_query_count_does_not_grow_with_the_project(self):
        """The stronger form: same budget at 10 tasks and at 99."""

        def queries_for(count_of_tasks: int) -> int:
            project = self._project()
            self.project = project
            tasks = [self._task() for _ in range(count_of_tasks)]
            for predecessor, successor in zip(tasks, tasks[1:]):
                self._dependency(predecessor, successor)
            self.db.commit()
            statements: list[str] = []

            @event.listens_for(self.engine, "before_cursor_execute")
            def count(_conn, _cursor, statement, _params, _context, _executemany):
                statements.append(statement)

            try:
                self.service.for_project(project.id)
            finally:
                event.remove(self.engine, "before_cursor_execute", count)
            return len(statements)

        self.assertEqual(queries_for(10), queries_for(99))


if __name__ == "__main__":
    unittest.main()
