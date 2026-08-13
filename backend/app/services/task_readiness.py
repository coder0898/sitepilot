"""U12: readiness computed from the facts, never declared by a user.

A task's readiness is derived, at read time, from three already-persisted
facts: its own `lifecycle_status`, the state of its blocking predecessors
in `task_dependencies`, and the state of the external approvals mapped to
it in `project_external_approval_tasks`. Nothing here is stored, so a
readiness answer can never go stale against the facts it is derived from.

Six decisions are pinned here:

- **Every lifecycle status gets its own answer** (R3). `planned` and
  `ready` are the only two statuses whose readiness is *computed*;
  the other seven are reported as what they already are. The naive
  "completed / in progress / blocked / else ready" ladder reports
  `submitted`, `verified`, `approval_pending`, `rejected` and `cancelled`
  as ready, which would put cancelled and under-review work at the top of
  an acceleration list. `_STATE_BY_LIFECYCLE_STATUS` below enumerates the
  seven explicitly and an unrecognised status falls through to `blocked`,
  so nothing outside `planned`/`ready` can ever be reported ready.
- **There is no `not_applicable` state.** Excluded tasks are never
  instantiated into the execution layer at all -
  `ProjectBaselineService.lock_and_instantiate` only instantiates
  `V2ProjectTask.included.is_(True)` - so there is no execution row to
  report it against, and answering it would mean reading the planning
  tables, which KTD8 forbids.
- **Every unsatisfied fact is reported, not the first** (R4). A task
  waiting on three predecessors and two approvals returns five reasons,
  each naming its specific subject, so a PM sees the whole critical path
  rather than peeling it one blocker at a time.
- **The `blocking` flags are honoured on both edges and approvals.** A
  non-blocking dependency and a non-blocking approval are reported as
  advisories, not blockers. `ProjectExternalApproval.blocking` is copied
  from a gate a PM deliberately set; ignoring it would report every task a
  non-blocking approval covers as blocked.
- **Unresolved approval coverage is a project-level signal** (R10). An
  approval with `coverage_state = 'unresolved'` has no rows in
  `project_external_approval_tasks`, so no task is ever mapped to one and
  a per-task unresolved branch would be unreachable. It is surfaced
  against the project instead, where a human can resolve it - never
  silently blocking and never silently passing.
- **Readiness is advisory this release** (R5, KTD1). This module writes
  nothing, calls no lifecycle transition, and changes no status. It is a
  read-side projection like `task_delay_variance.py` and
  `task_approval_metadata.py`; making it enforcing is a separate decision.

Execution-layer tables only (KTD8): `tasks`, `task_dependencies`,
`project_external_approvals`, `project_external_approval_tasks`.
`V2ProjectTask` and `V2ProjectExternalGate` are never read here.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import (
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
    TaskDependency,
)
from app.services.task_lifecycle import TaskLifecycleService

READY = "ready"
BLOCKED = "blocked"
IN_PROGRESS = "in_progress"
AWAITING_VERIFICATION = "awaiting_verification"
AWAITING_APPROVAL = "awaiting_approval"
REJECTED = "rejected"
COMPLETED = "completed"
CANCELLED = "cancelled"

REASON_DEPENDENCY = "dependency"
REASON_APPROVAL = "approval"

# The two statuses whose readiness is a question rather than an answer: the
# task has not started and nothing has been decided about it, so whether it
# may start is exactly what dependencies and approvals determine.
COMPUTED_STATUSES = frozenset({"planned", "ready"})

# Every other member of `TASK_LIFECYCLE_STATUSES`, enumerated rather than
# defaulted. `verified` and `approval_pending` share an answer: a persisted
# `verified` is class_a work parked for PM approval (standard work
# auto-completes straight past it - see task_approval_metadata.py), which is
# the same thing `approval_pending` means to anyone reading a board.
# `test_task_readiness_v2.py` asserts this dict plus COMPUTED_STATUSES
# covers TASK_LIFECYCLE_STATUSES exactly, so adding a tenth status fails a
# test rather than silently landing in the fallback below.
_STATE_BY_LIFECYCLE_STATUS: dict[str, str] = {
    "in_progress": IN_PROGRESS,
    "submitted": AWAITING_VERIFICATION,
    "verified": AWAITING_APPROVAL,
    "approval_pending": AWAITING_APPROVAL,
    "rejected": REJECTED,
    "completed": COMPLETED,
    "cancelled": CANCELLED,
}


@dataclass(frozen=True)
class ReadinessReason:
    """One named fact standing between a task and being ready.

    `subject_id` is the predecessor task or the approval itself, so a
    consumer can link straight to it rather than parse `detail`. `blocking`
    records which side of the edge's / approval's own `blocking` flag this
    reason came from - a caller that wants only the true blockers reads
    `TaskReadiness.reasons`, and `advisories` carries the rest.
    """

    kind: str
    subject_id: uuid.UUID
    detail: str
    blocking: bool


@dataclass(frozen=True)
class TaskReadiness:
    """One task's readiness state and everything standing in its way."""

    task_id: uuid.UUID
    state: str
    reasons: tuple[ReadinessReason, ...] = ()
    advisories: tuple[ReadinessReason, ...] = ()

    @property
    def is_ready(self) -> bool:
        return self.state == READY

    @property
    def is_blocked(self) -> bool:
        return self.state == BLOCKED


@dataclass(frozen=True)
class UnresolvedApproval:
    """An approval whose task coverage could not be resolved at activation.

    Carries `status` as well as the prose so a consumer can decide what to
    lead with. Approved-but-unresolved rows are included deliberately: the
    coverage is still a data-quality gap a PM should close, even though a
    granted approval is no longer holding anything up.
    """

    approval_id: uuid.UUID
    status: str
    blocking: bool
    coverage_text: str | None


@dataclass(frozen=True)
class ProjectReadiness:
    """A whole project's readiness: every task, plus the project-level signal."""

    tasks: dict[uuid.UUID, TaskReadiness] = field(default_factory=dict)
    unresolved_approvals: tuple[UnresolvedApproval, ...] = ()

    def ready_task_ids(self) -> list[uuid.UUID]:
        return [task_id for task_id, readiness in self.tasks.items() if readiness.is_ready]


class TaskReadinessService:
    """Resolves a whole project's readiness in a bounded number of queries.

    Four selects cover a project of any size - tasks, dependency edges,
    approvals, coverage links - each filtered on the denormalised
    `project_id` the schema carries for exactly this reason. Nothing is
    looked up per task.

    The one query that is not batched is
    `TaskLifecycleService._has_unrejected_verification`, reached only for a
    predecessor sitting at `verified` whose class is `standard`. That is a
    transient state standard work auto-completes past in the same verify
    call, so it is bounded by the number of predecessors caught mid-verify,
    not by the size of the project.

    Read-only by construction: it selects, computes and returns. It never
    calls `TaskLifecycleService.transition`, so no status moves and no audit
    event is written by asking this question (R5, KTD1).
    """

    def __init__(self, db: Session):
        self.db = db
        # Borrowed purely for `_predecessor_satisfied`. See
        # `_dependency_reasons` for why this is a call and not a copy.
        self._lifecycle = TaskLifecycleService(db)

    def for_project(self, project_id: uuid.UUID) -> ProjectReadiness:
        tasks = list(self.db.scalars(select(Task).where(Task.project_id == project_id)))
        tasks_by_id = {task.id: task for task in tasks}

        dependencies_by_successor: dict[uuid.UUID, list[TaskDependency]] = defaultdict(list)
        for dependency in self.db.scalars(
            select(TaskDependency).where(TaskDependency.project_id == project_id)
        ):
            dependencies_by_successor[dependency.successor_task_id].append(dependency)

        approvals_by_id = {
            approval.id: approval
            for approval in self.db.scalars(
                select(ProjectExternalApproval).where(
                    ProjectExternalApproval.project_id == project_id
                )
            )
        }

        approval_ids_by_task: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for link in self.db.scalars(
            select(ProjectExternalApprovalTask).where(
                ProjectExternalApprovalTask.project_id == project_id
            )
        ):
            approval_ids_by_task[link.task_id].append(link.approval_id)

        readiness = {
            task.id: self._readiness_for(
                task,
                dependencies_by_successor.get(task.id, ()),
                tasks_by_id,
                approval_ids_by_task.get(task.id, ()),
                approvals_by_id,
            )
            for task in tasks
        }

        unresolved = tuple(
            UnresolvedApproval(
                approval_id=approval.id,
                status=approval.status,
                blocking=approval.blocking,
                coverage_text=approval.coverage_text,
            )
            for approval in sorted(
                (a for a in approvals_by_id.values() if a.coverage_state == "unresolved"),
                key=lambda a: str(a.id),
            )
        )

        return ProjectReadiness(tasks=readiness, unresolved_approvals=unresolved)

    # ---- per-task computation ----------------------------------------

    def _readiness_for(
        self,
        task: Task,
        dependencies,
        tasks_by_id: dict[uuid.UUID, Task],
        approval_ids,
        approvals_by_id: dict[uuid.UUID, ProjectExternalApproval],
    ) -> TaskReadiness:
        settled_state = _STATE_BY_LIFECYCLE_STATUS.get(task.lifecycle_status)
        if task.lifecycle_status not in COMPUTED_STATUSES:
            # Already started, already decided, or a status this module has
            # never heard of. None of them is a readiness question, and none
            # of them may be reported ready. Reasons are empty because a
            # started or terminal task is not waiting on anything - the
            # blockers that mattered were the ones it had before it moved.
            return TaskReadiness(task_id=task.id, state=settled_state or BLOCKED)

        reasons: list[ReadinessReason] = []
        advisories: list[ReadinessReason] = []
        for reason in self._dependency_reasons(dependencies, tasks_by_id):
            (reasons if reason.blocking else advisories).append(reason)
        for reason in self._approval_reasons(approval_ids, approvals_by_id):
            (reasons if reason.blocking else advisories).append(reason)

        return TaskReadiness(
            task_id=task.id,
            state=BLOCKED if reasons else READY,
            reasons=tuple(reasons),
            advisories=tuple(advisories),
        )

    def _dependency_reasons(
        self, dependencies, tasks_by_id: dict[uuid.UUID, Task]
    ) -> list[ReadinessReason]:
        """A reason per unsatisfied predecessor - all of them, per R4.

        `_predecessor_satisfied` is *called*, not reimplemented. It owns
        U1's per-kind BR-008 rule, the start-to-start relaxation and the
        cancelled-satisfies-either-type rule; a second copy here would drift
        from the guard the lifecycle service actually enforces, and a
        readiness board that disagrees with what the portal permits is worse
        than no board. The predecessor row is handed in from the batched map
        rather than re-fetched, so the reuse costs no extra query.
        """
        reasons = []
        for dependency in sorted(dependencies, key=_dependency_order(tasks_by_id)):
            predecessor = tasks_by_id.get(dependency.predecessor_task_id)
            if predecessor is not None and self._lifecycle._predecessor_satisfied(
                predecessor, dependency.dependency_type
            ):
                continue
            if predecessor is None:
                # Mirrors `_blocking_predecessors_satisfied`, which also
                # treats a missing predecessor as unsatisfied: the edge
                # points somewhere unreadable, and guessing "satisfied"
                # would release work on a dependency nobody can see.
                detail = f"Waiting on a predecessor task that could not be read ({dependency.predecessor_task_id})."
            else:
                detail = (
                    f"Waiting on {predecessor.original_code} - {predecessor.title}"
                    f" ({dependency.dependency_type}), currently {predecessor.lifecycle_status}."
                )
            reasons.append(
                ReadinessReason(
                    kind=REASON_DEPENDENCY,
                    subject_id=dependency.predecessor_task_id,
                    detail=detail,
                    blocking=bool(dependency.blocking),
                )
            )
        return reasons

    def _approval_reasons(
        self, approval_ids, approvals_by_id: dict[uuid.UUID, ProjectExternalApproval]
    ) -> list[ReadinessReason]:
        """A reason per approval that is not `approved` - all of them, per R4.

        Both `pending` and `rejected` hold the task: neither has granted
        anything. They are distinguished in `detail` rather than collapsed,
        because a rejected approval needs a different action from one that
        is merely waiting.
        """
        reasons = []
        for approval_id in sorted(approval_ids, key=str):
            approval = approvals_by_id.get(approval_id)
            if approval is None or approval.status == "approved":
                continue
            reasons.append(
                ReadinessReason(
                    kind=REASON_APPROVAL,
                    subject_id=approval.id,
                    detail=f"External approval {approval.id} is {approval.status}.",
                    blocking=bool(approval.blocking),
                )
            )
        return reasons


def _dependency_order(tasks_by_id: dict[uuid.UUID, Task]):
    """Stable reason ordering: predecessors in template sequence.

    A board that reorders its blockers between two identical reads looks
    broken, and a missing predecessor sorts last rather than crashing.
    """

    def key(dependency: TaskDependency):
        predecessor = tasks_by_id.get(dependency.predecessor_task_id)
        return (
            predecessor.template_sequence if predecessor is not None else 1 << 31,
            str(dependency.predecessor_task_id),
        )

    return key
