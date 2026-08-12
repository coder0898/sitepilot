"""45-day POC U6: compute which work can actually start, and name what is
holding the rest up.

ADVISORY ONLY. THIS SERVICE MUST NEVER MOVE A TASK, AND NOTHING HERE MAY
BECOME A CONDITION ON A TRANSITION. `app/services/task_lifecycle.py` is the
sole authority on what the portal permits. Readiness is a second opinion
computed on request, and it ships as a label first on purpose: the 45-day
template's 38 dependency edges have not been validated against how sites
actually work, and an edge that shows a wrong label costs far less than one
that holds up a crew. Making it binding is a later, deliberate release.

It reads execution-layer rows only - `Task`, `TaskDependency`, the
execution gates from U3 - never their planning-layer counterparts. Planning
rows are Draft-time scope; an approval recorded after activation lives on
the execution row and only the execution row.

Query budget: a fixed number of queries regardless of how many tasks or
predecessors a project has (KTD1). The 45-day template has 99 tasks, and
the one-query-per-edge shape in `_blocking_predecessors_satisfied` would
turn a page load into hundreds of round trips. Everything is bulk-loaded
and intersected in Python. `backend/app/services/project_visibility.py` is
the pattern.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import (
    GATE_NON_BLOCKING_STATUSES,
    ExecutionExcludedDependency,
    ExecutionGate,
    ExecutionGateTask,
    Task,
    TaskDependency,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.routes.projects_v2 import get_project
from app.schemas.task_readiness import (
    ProjectTaskReadinessOut,
    TaskReadinessOut,
    TaskReadinessReasonOut,
)
from app.services.task_lifecycle import predecessor_satisfied

TERMINAL_STATUSES = frozenset({"completed", "cancelled"})
NOT_YET_STARTED_STATUSES = frozenset({"planned", "ready"})
"""Statuses from which work has not begun. `rejected` is excluded on
purpose - a rejected task is work already underway that has come back for
rework, not work waiting to be released."""


class TaskReadinessService:
    def __init__(self, db: Session):
        self.db = db

    def summarize(self, project_id: uuid.UUID, actor: User) -> ProjectTaskReadinessOut:
        project = get_project(self.db, project_id, actor)

        tasks = self._visible_tasks(project.id, actor)
        if not tasks:
            return ProjectTaskReadinessOut(project_id=project.id, total=0, startable_count=0, items=[])

        task_by_id = {t.id: t for t in tasks}
        visible_ids = set(task_by_id)

        dependencies = list(self.db.scalars(
            select(TaskDependency).where(
                TaskDependency.project_id == project.id, TaskDependency.blocking.is_(True)
            )
        ).all())
        verified_task_ids = self._unrejected_verified_task_ids(list(visible_ids))
        gates_by_task, unresolved_gates = self._gate_state(project.id)
        excluded_by_task = self._excluded_predecessors(project.id)

        deps_by_successor: dict[uuid.UUID, list[TaskDependency]] = defaultdict(list)
        for dependency in dependencies:
            deps_by_successor[dependency.successor_task_id].append(dependency)

        items = [
            self._readiness_for(
                task,
                deps_by_successor.get(task.id, []),
                task_by_id,
                verified_task_ids,
                gates_by_task.get(task.id, []),
                excluded_by_task.get(task.id, []),
            )
            for task in tasks
        ]
        # A gate covering no task blocks nothing, which is the demo's own
        # stated limitation. Surface it rather than let an approval look
        # meaningful when it releases nothing (R7).
        return ProjectTaskReadinessOut(
            project_id=project.id,
            total=len(items),
            startable_count=sum(1 for item in items if item.startable),
            items=items,
            unresolved_gates=unresolved_gates,
        )

    # ---- what this actor may see ----------------------------------------

    def _visible_tasks(self, project_id: uuid.UUID, actor: User) -> list[Task]:
        """Scoped exactly like `list_project_tasks`, deliberately.

        `get_project`'s `can_view` admits an Internal Employee to the whole
        project, but the sibling task endpoints narrow that role to its own
        assignments - `get_project_task` even notes that filtering the list
        alone "would only be a UI convenience, not real access control".
        Readiness reasons carry task titles, codes, gate names and external
        parties for the entire project, so returning them unscoped would
        hand that role a project-wide view it does not otherwise have.
        """
        query = select(Task).where(Task.project_id == project_id).order_by(Task.template_sequence.asc())
        if actor.role == UserRole.internal_employee:
            actor_employee_id = self.db.scalar(
                select(EmployeeProfile.id).where(EmployeeProfile.user_id == actor.id)
            )
            assigned_task_ids = select(TaskSupportAssignment.task_id).where(
                TaskSupportAssignment.project_id == project_id,
                TaskSupportAssignment.employee_id == actor_employee_id,
                TaskSupportAssignment.status == "active",
                TaskSupportAssignment.ends_at.is_(None),
            )
            query = query.where(Task.id.in_(assigned_task_ids))
        return list(self.db.scalars(query).all())

    # ---- bulk loads -------------------------------------------------------

    def _unrejected_verified_task_ids(self, task_ids: list[uuid.UUID]) -> frozenset[uuid.UUID]:
        """Task ids whose most recent verification decision is `verified`.

        One query for every task in scope, then latest-per-task in Python.
        `TaskVerification` carries no project_id, so it is scoped by task
        id. Ordered ascending so the last row seen per task wins, mirroring
        the descending `limit(1)` the transition guard uses for one task.
        """
        if not task_ids:
            return frozenset()
        rows = self.db.execute(
            select(TaskVerification.task_id, TaskVerification.decision)
            .where(TaskVerification.task_id.in_(task_ids))
            .order_by(TaskVerification.verified_at.asc(), TaskVerification.id.asc())
        ).all()
        latest: dict[uuid.UUID, str] = {}
        for task_id, decision in rows:
            latest[task_id] = decision
        return frozenset(task_id for task_id, decision in latest.items() if decision == "verified")

    def _gate_state(self, project_id: uuid.UUID) -> tuple[dict[uuid.UUID, list[ExecutionGate]], list[TaskReadinessReasonOut]]:
        gates = list(self.db.scalars(
            select(ExecutionGate).where(ExecutionGate.project_id == project_id)
        ).all())
        if not gates:
            return {}, []
        gate_by_id = {g.id: g for g in gates}
        links = self.db.execute(
            select(ExecutionGateTask.execution_gate_id, ExecutionGateTask.task_id)
            .where(ExecutionGateTask.execution_gate_id.in_(list(gate_by_id)))
        ).all()

        gates_by_task: dict[uuid.UUID, list[ExecutionGate]] = defaultdict(list)
        covered_gate_ids: set[uuid.UUID] = set()
        for gate_id, task_id in links:
            covered_gate_ids.add(gate_id)
            gates_by_task[task_id].append(gate_by_id[gate_id])

        unresolved = [
            TaskReadinessReasonOut(
                kind="unresolved_gate", code=gate.original_code, title=gate.approval_name,
                detail=(
                    f"{gate.approval_name} covers no task on this project, so approving it releases nothing. "
                    "Its coverage has not been configured."
                ),
                status=gate.status, enforced=False,
            )
            for gate in gates
            if gate.blocking and gate.id not in covered_gate_ids
        ]
        return gates_by_task, unresolved

    def _excluded_predecessors(self, project_id: uuid.UUID) -> dict[uuid.UUID, list[ExecutionExcludedDependency]]:
        rows = list(self.db.scalars(
            select(ExecutionExcludedDependency).where(ExecutionExcludedDependency.project_id == project_id)
        ).all())
        grouped: dict[uuid.UUID, list[ExecutionExcludedDependency]] = defaultdict(list)
        for row in rows:
            grouped[row.successor_task_id].append(row)
        return grouped

    # ---- the predicate -----------------------------------------------------

    def _readiness_for(
        self,
        task: Task,
        dependencies: list[TaskDependency],
        task_by_id: dict[uuid.UUID, Task],
        verified_task_ids: frozenset[uuid.UUID],
        gates: list[ExecutionGate],
        excluded: list[ExecutionExcludedDependency],
    ) -> TaskReadinessOut:
        if task.lifecycle_status in TERMINAL_STATUSES:
            return TaskReadinessOut(
                task_id=task.id, original_code=task.original_code, title=task.title,
                lifecycle_status=task.lifecycle_status, state=task.lifecycle_status,
                startable=False, reasons=[],
            )
        if task.lifecycle_status not in NOT_YET_STARTED_STATUSES:
            return TaskReadinessOut(
                task_id=task.id, original_code=task.original_code, title=task.title,
                lifecycle_status=task.lifecycle_status, state="in_progress",
                startable=False, reasons=[],
            )

        reasons: list[TaskReadinessReasonOut] = []
        divergence = False

        for dependency in dependencies:
            predecessor = task_by_id.get(dependency.predecessor_task_id)
            if predecessor is None:
                # Only reachable for an Internal Employee, whose visible set
                # is narrowed to their own assignments. Skipping is right:
                # naming a predecessor they may not see would leak it.
                continue
            if dependency.dependency_type == "start_to_start":
                satisfied = (
                    predecessor.lifecycle_status not in NOT_YET_STARTED_STATUSES
                    and predecessor.lifecycle_status != "cancelled"
                )
                if satisfied and not predecessor_satisfied(predecessor, verified_task_ids):
                    # KTD8: the one divergence from the guard this plan
                    # accepts. The overlap is real per the template, but the
                    # guard still demands a finished predecessor.
                    divergence = True
            else:
                satisfied = predecessor_satisfied(predecessor, verified_task_ids)
            if not satisfied:
                reasons.append(TaskReadinessReasonOut(
                    kind="predecessor", code=predecessor.original_code, title=predecessor.title,
                    detail=(
                        f"{predecessor.original_code} {predecessor.title} must "
                        + ("have started" if dependency.dependency_type == "start_to_start" else "be finished")
                        + f" first (currently {predecessor.lifecycle_status})."
                    ),
                    status=predecessor.lifecycle_status, enforced=True,
                ))

        for gate in gates:
            if not gate.blocking or gate.status in GATE_NON_BLOCKING_STATUSES:
                continue
            reasons.append(TaskReadinessReasonOut(
                kind="gate", code=gate.original_code, title=gate.approval_name,
                detail=f"{gate.original_code} {gate.approval_name} is {gate.status}.",
                status=gate.status, enforced=True,
            ))

        for edge in excluded:
            # Advisory only. The edge was dropped at baseline lock because
            # its predecessor is out of scope, so no TaskDependency row
            # exists and the guard will happily let this task start. Saying
            # nothing would show the task as unconditionally startable,
            # which is the confidently-wrong answer worth avoiding.
            reasons.append(TaskReadinessReasonOut(
                kind="excluded_predecessor", code=edge.excluded_predecessor_code,
                title=edge.excluded_predecessor_title or edge.excluded_predecessor_code,
                detail=(
                    f"{edge.excluded_predecessor_code} was excluded from this project's scope, and the work it "
                    "would have depended on has not been carried across. Not enforced."
                ),
                status="excluded", enforced=False,
            ))

        blocking_reasons = [r for r in reasons if r.enforced]
        return TaskReadinessOut(
            task_id=task.id, original_code=task.original_code, title=task.title,
            lifecycle_status=task.lifecycle_status,
            state="ready" if not blocking_reasons else "blocked",
            startable=not blocking_reasons,
            reasons=reasons,
            guard_diverges=divergence,
        )
