"""U1/U2: dependency-type semantics and the cancelled-predecessor rule.

Covers the two rules that `TaskLifecycleService` applies when deciding
whether a task's blocking predecessors are satisfied:

- U1: a `start_to_start` edge is satisfied once the predecessor has
  *started*; a `finish_to_start` edge still requires completion. Before
  U1, `dependency_type` was stored and rendered but never read at the
  guard, so every SS edge silently behaved as FS.
- U2: a `cancelled` predecessor no longer blocks its successors. Before
  U2, cancelling one task froze every task downstream of it permanently.

Also pins the deliberate asymmetry U1/U2 introduce: milestone
auto-completion keeps the strict rule (`_milestone_predecessors_completed`)
and must NOT inherit either relaxation - a milestone asserts the work
behind it happened, so neither a merely-started predecessor nor a
cancelled one may complete it.

Exercises the service's satisfaction rules directly against the ORM rather
than through the activation flow, so the cases stay readable and do not
depend on the full baseline-lock harness.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import Task, TaskDependency
from app.services.task_lifecycle import TaskLifecycleService


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TaskDependencySemanticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (Task.__table__, TaskDependency.__table__):
            table.create(bind=self.engine, checkfirst=True)

        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()
        self.service = TaskLifecycleService(self.db)
        self.project_id = uuid.uuid4()
        self.baseline_id = uuid.uuid4()
        self._sequence = 0

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # ---- helpers -------------------------------------------------------

    def _task(self, status: str, *, kind: str = "work", task_class: str = "standard") -> Task:
        self._sequence += 1
        task = Task(
            id=uuid.uuid4(),
            project_id=self.project_id,
            baseline_id=self.baseline_id,
            baseline_task_id=uuid.uuid4(),
            original_code=f"T{self._sequence:03d}",
            template_sequence=self._sequence,
            title=f"Task {self._sequence}",
            schedule_classification="execution",
            applicability="mandatory",
            task_class=task_class,
            task_kind=kind,
            lifecycle_status=status,
        )
        self.db.add(task)
        self.db.flush()
        return task

    def _edge(self, predecessor: Task, successor: Task, dependency_type: str) -> None:
        self.db.add(TaskDependency(
            id=uuid.uuid4(),
            project_id=self.project_id,
            baseline_id=self.baseline_id,
            predecessor_task_id=predecessor.id,
            successor_task_id=successor.id,
            dependency_type=dependency_type,
            blocking=True,
        ))
        self.db.flush()

    def _startable(self, successor: Task) -> bool:
        return self.service._blocking_predecessors_satisfied(successor)

    def _milestone_completable(self, successor: Task) -> bool:
        return self.service._milestone_predecessors_completed(successor)

    # ---- U1: start-to-start --------------------------------------------

    def test_start_to_start_successor_is_startable_once_predecessor_is_in_progress(self):
        predecessor = self._task("in_progress")
        successor = self._task("planned")
        self._edge(predecessor, successor, "start_to_start")
        self.assertTrue(self._startable(successor))

    def test_start_to_start_successor_is_startable_once_predecessor_is_completed(self):
        predecessor = self._task("completed")
        successor = self._task("planned")
        self._edge(predecessor, successor, "start_to_start")
        self.assertTrue(self._startable(successor))

    def test_start_to_start_successor_is_not_startable_while_predecessor_is_planned(self):
        predecessor = self._task("planned")
        successor = self._task("planned")
        self._edge(predecessor, successor, "start_to_start")
        self.assertFalse(self._startable(successor))

    def test_start_to_start_successor_is_not_startable_while_predecessor_is_only_ready(self):
        predecessor = self._task("ready")
        successor = self._task("planned")
        self._edge(predecessor, successor, "start_to_start")
        self.assertFalse(self._startable(successor))

    def test_start_to_start_successor_stays_released_after_predecessor_is_rejected(self):
        """A rejected task has still started, so its SS successors hold."""
        predecessor = self._task("rejected")
        successor = self._task("planned")
        self._edge(predecessor, successor, "start_to_start")
        self.assertTrue(self._startable(successor))

    # ---- U1: finish-to-start is unchanged -------------------------------

    def test_finish_to_start_successor_is_not_startable_while_predecessor_is_in_progress(self):
        predecessor = self._task("in_progress")
        successor = self._task("planned")
        self._edge(predecessor, successor, "finish_to_start")
        self.assertFalse(self._startable(successor))

    def test_finish_to_start_successor_is_startable_once_predecessor_is_completed(self):
        predecessor = self._task("completed")
        successor = self._task("planned")
        self._edge(predecessor, successor, "finish_to_start")
        self.assertTrue(self._startable(successor))

    def test_mixed_edge_types_require_each_edges_own_rule(self):
        started_only = self._task("in_progress")
        finished = self._task("completed")
        successor = self._task("planned")
        self._edge(started_only, successor, "start_to_start")
        self._edge(finished, successor, "finish_to_start")
        self.assertTrue(self._startable(successor))

    def test_mixed_edge_types_block_when_the_finish_to_start_edge_is_unsatisfied(self):
        started_only = self._task("in_progress")
        also_started_only = self._task("in_progress")
        successor = self._task("planned")
        self._edge(started_only, successor, "start_to_start")
        self._edge(also_started_only, successor, "finish_to_start")
        self.assertFalse(self._startable(successor))

    # ---- U2: cancelled predecessors -------------------------------------

    def test_successor_of_a_cancelled_predecessor_is_startable(self):
        predecessor = self._task("cancelled")
        successor = self._task("planned")
        self._edge(predecessor, successor, "finish_to_start")
        self.assertTrue(self._startable(successor))

    def test_successor_blocked_when_one_predecessor_cancelled_and_one_incomplete(self):
        cancelled = self._task("cancelled")
        incomplete = self._task("in_progress")
        successor = self._task("planned")
        self._edge(cancelled, successor, "finish_to_start")
        self._edge(incomplete, successor, "finish_to_start")
        self.assertFalse(self._startable(successor))

    def test_successor_startable_when_one_predecessor_cancelled_and_one_completed(self):
        cancelled = self._task("cancelled")
        completed = self._task("completed")
        successor = self._task("planned")
        self._edge(cancelled, successor, "finish_to_start")
        self._edge(completed, successor, "finish_to_start")
        self.assertTrue(self._startable(successor))

    def test_a_chain_of_three_releases_the_third_when_the_middle_is_cancelled(self):
        first = self._task("completed")
        middle = self._task("cancelled")
        third = self._task("planned")
        self._edge(first, middle, "finish_to_start")
        self._edge(middle, third, "finish_to_start")
        self.assertTrue(self._startable(third))

    # ---- U1/U2 must not leak into milestone auto-completion -------------

    def test_milestone_does_not_auto_complete_on_a_merely_started_predecessor(self):
        predecessor = self._task("in_progress")
        milestone = self._task("planned", kind="milestone", task_class="standard")
        self._edge(predecessor, milestone, "start_to_start")
        self.assertTrue(self._startable(milestone))
        self.assertFalse(self._milestone_completable(milestone))

    def test_milestone_does_not_auto_complete_on_a_cancelled_predecessor(self):
        cancelled = self._task("cancelled")
        completed = self._task("completed")
        milestone = self._task("planned", kind="milestone", task_class="standard")
        self._edge(cancelled, milestone, "finish_to_start")
        self._edge(completed, milestone, "finish_to_start")
        self.assertTrue(self._startable(milestone))
        self.assertFalse(self._milestone_completable(milestone))

    def test_milestone_auto_completes_when_every_predecessor_actually_completed(self):
        first = self._task("completed")
        second = self._task("completed")
        milestone = self._task("planned", kind="milestone", task_class="standard")
        self._edge(first, milestone, "finish_to_start")
        self._edge(second, milestone, "finish_to_start")
        self.assertTrue(self._milestone_completable(milestone))


if __name__ == "__main__":
    unittest.main()
