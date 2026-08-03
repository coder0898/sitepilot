"""U2: Task lifecycle state machine (BR-009).

`TaskLifecycleService.transition` is the single authority for moving a
`Task.lifecycle_status` from one state to another. It encodes BR-009's exact
transition table as an explicit allow-list (nothing inferred), gates
`ready`/`in_progress` on an active project Supervisor (BR-004) and on
predecessor-dependency satisfaction (BR-011/BR-008), auto-completes
successor milestones as a side effect, and writes a `V2AuditEvent` for every
transition.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import TASK_LIFECYCLE_STATUSES, Task, TaskDependency, TaskVerification
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership


# BR-009's canonical transition table, as an explicit allow-list:
#   planned -> ready -> in_progress -> submitted -> verified -> completed
#   submitted -> rejected -> in_progress (rejected work reopens)
#   verified -> approval_pending -> completed (Class A work, pending PM approval)
#   submitted -> approval_pending -> completed (approval gates skip Supervisor
#       verification per BR-008)
#   approval_pending -> rejected -> in_progress
#   planned -> completed (system-derived milestone auto-completion only)
#   any non-terminal state -> cancelled (authorized override, reason required)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"ready", "completed", "cancelled"},
    "ready": {"in_progress", "cancelled"},
    "in_progress": {"submitted", "cancelled"},
    "submitted": {"verified", "approval_pending", "rejected", "cancelled"},
    "verified": {"approval_pending", "completed", "cancelled"},
    "approval_pending": {"completed", "rejected", "cancelled"},
    "rejected": {"in_progress", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

# Transitions a Supervisor (or PM, or Admin/Super Admin) may drive: moving
# work forward and reopening after rejection. U4 (verification/approval)
# doesn't exist yet, so the actual verify/approve decision endpoints aren't
# built here - these role checks only gate the *status transition itself*,
# not a verification/approval record (that's U4's job).
_SUPERVISOR_OR_PM_TARGETS = {"ready", "in_progress", "submitted", "rejected", "verified", "approval_pending", "completed"}


class TaskLifecycleService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access / role resolution -----------------------------------

    def _actor_project_roles(self, project_id: uuid.UUID, actor: User) -> set[str]:
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
        if not employee:
            return set()
        rows = self.db.scalars(
            select(V2ProjectMembership.project_role).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        return set(rows)

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return project
        if self._actor_project_roles(project_id, actor):
            return project
        raise HTTPException(403, "You do not have access to this project.")

    def _require_role_for_transition(self, project: V2Project, target_status: str, actor: User) -> None:
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if target_status in _SUPERVISOR_OR_PM_TARGETS:
            if "site_supervisor" in roles or "project_manager" in roles:
                return
            raise HTTPException(403, "Only the project's Supervisor, PM, or an Admin can make this task transition.")
        raise HTTPException(403, "You do not have permission to make this task transition.")

    def _can_cancel(self, project: V2Project, actor: User) -> bool:
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return True
        roles = self._actor_project_roles(project.id, actor)
        # "authorized override" per BR-009: Admin/Super Admin, or the
        # accountable PM, may cancel a task.
        return "project_manager" in roles

    def _has_active_supervisor(self, project_id: uuid.UUID) -> bool:
        return self.db.scalar(
            select(V2ProjectMembership.id).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role == "site_supervisor",
                V2ProjectMembership.ends_at.is_(None),
            )
        ) is not None

    # ---- dependency satisfaction -------------------------------------

    def _has_unrejected_verification(self, predecessor: Task) -> bool:
        """Whether the most recent TaskVerification recorded against
        `predecessor` is a 'verified' decision with no later rejection.

        Since a rejection always moves lifecycle_status off 'verified' (back
        to 'in_progress' via U4's TaskVerificationService, requiring
        resubmission and a fresh verification), a predecessor that is
        currently sitting at lifecycle_status == 'verified' can only be
        there because its latest verification decision was 'verified' - but
        we still query explicitly here (rather than trust the status alone)
        so this check is correct even if called from a context that hasn't
        re-read the task's current status.
        """
        latest = self.db.scalar(
            select(TaskVerification)
            .where(TaskVerification.task_id == predecessor.id)
            .order_by(TaskVerification.verified_at.desc(), TaskVerification.id.desc())
            .limit(1)
        )
        return latest is not None and latest.decision == "verified"

    def _predecessor_satisfied(self, predecessor: Task) -> bool:
        """Whether a predecessor task satisfies a blocking dependency,
        per BR-008's exact per-kind rule:

        - `standard` work: satisfied once Supervisor-verified (a
          `task_verifications` row with decision='verified' and no later
          rejection exists) - it does not need to also reach `completed`,
          since BR-008 only requires PM approval for Class A work, not
          standard work. `completed` also satisfies it (the standard-work
          verify path immediately auto-completes it anyway, per U4's
          TaskVerificationService, so this task is nearly always observed
          at `completed`, not `verified` - but the `verified` case is
          the "satisfied" moment we should not block on regardless).
        - `class_a` work and `approval_gate`: require PM-approved
          `completed` (BR-008: "Verified class_a work requires PM approval
          before completion"; gates likewise complete only via PM
          approval).
        - `milestone`: requires `completed` (system-derived, BR-009).
        """
        if predecessor.lifecycle_status == "completed":
            return True
        if (
            predecessor.task_kind == "work"
            and predecessor.task_class == "standard"
            and predecessor.lifecycle_status == "verified"
        ):
            return self._has_unrejected_verification(predecessor)
        return False

    def _blocking_predecessors_satisfied(self, task: Task) -> bool:
        deps = self.db.scalars(
            select(TaskDependency).where(
                TaskDependency.successor_task_id == task.id,
                TaskDependency.blocking.is_(True),
            )
        )
        for dep in deps:
            predecessor = self.db.get(Task, dep.predecessor_task_id)
            if not predecessor or not self._predecessor_satisfied(predecessor):
                return False
        return True

    # ---- milestone auto-completion -----------------------------------

    def _auto_complete_successor_milestones(self, source_task: Task, actor: User) -> None:
        """Side effect run whenever a task reaches `completed`: any
        successor `milestone` task still `planned` whose blocking
        predecessors are now all satisfied auto-transitions to `completed`.
        Recurses to handle chained milestones."""
        dep_rows = list(self.db.scalars(
            select(TaskDependency).where(
                TaskDependency.predecessor_task_id == source_task.id,
                TaskDependency.blocking.is_(True),
            )
        ))
        for dep in dep_rows:
            successor = self.db.get(Task, dep.successor_task_id)
            if not successor or successor.task_kind != "milestone" or successor.lifecycle_status != "planned":
                continue
            if not self._blocking_predecessors_satisfied(successor):
                continue
            before_status = successor.lifecycle_status
            successor.lifecycle_status = "completed"
            self.db.add(V2AuditEvent(
                actor_user_id=actor.id,
                action="TASK_STATUS_CHANGED",
                entity_type="task",
                entity_id=successor.id,
                project_id=successor.project_id,
                source="system",
                before_json={"lifecycle_status": before_status},
                after_json={"lifecycle_status": "completed"},
                reason="Milestone auto-completed: all blocking predecessors satisfied.",
            ))
            self.db.flush()
            self._auto_complete_successor_milestones(successor, actor)

    # ---- transition entry point ---------------------------------------

    def transition(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        target_status: str,
        actor: User,
        reason: str | None = None,
    ) -> Task:
        project = self._require_access(project_id, actor)

        task = self.db.scalar(
            select(Task).where(Task.id == task_id, Task.project_id == project.id).with_for_update()
        )
        if not task:
            raise HTTPException(404, "Task not found.")

        if target_status not in TASK_LIFECYCLE_STATUSES:
            raise HTTPException(422, "Unknown task lifecycle status.")

        current_status = task.lifecycle_status
        if target_status == current_status:
            raise HTTPException(409, f"Task is already {current_status}.")

        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise HTTPException(
                409,
                f"A task cannot move from {current_status} to {target_status}.",
            )

        # planned -> completed is exclusively the system-derived milestone
        # auto-completion path (BR-009) - not a user-initiated transition
        # for any other task_kind, and not permitted before its blocking
        # predecessors are actually satisfied.
        if current_status == "planned" and target_status == "completed":
            if task.task_kind != "milestone":
                raise HTTPException(
                    409,
                    "Only a milestone task can move directly from planned to completed.",
                )
            if not self._blocking_predecessors_satisfied(task):
                raise HTTPException(
                    409,
                    "This milestone's blocking predecessor tasks are not yet all completed.",
                )

        if target_status == "cancelled":
            clean_reason = (reason or "").strip()
            if not clean_reason:
                raise HTTPException(422, "A reason is required to cancel a task.")
            if not self._can_cancel(project, actor):
                raise HTTPException(403, "Only Admin, Super Admin, or the project's PM can cancel a task.")
        else:
            self._require_role_for_transition(project, target_status, actor)

        if target_status in {"ready", "in_progress"}:
            # BR-004: work cannot start/proceed without an accountable
            # active Supervisor on the project.
            if not self._has_active_supervisor(project.id):
                raise HTTPException(
                    409,
                    "This project has no active Supervisor; task work cannot start or proceed.",
                )
            # BR-011: a dependent task cannot start while a blocking
            # predecessor is unsatisfied.
            if not self._blocking_predecessors_satisfied(task):
                raise HTTPException(
                    409,
                    "One or more blocking predecessor tasks are not yet satisfied.",
                )

        before_status = current_status
        task.lifecycle_status = target_status
        clean_reason = (reason or "").strip() or f"Task moved from {before_status} to {target_status}."
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="TASK_STATUS_CHANGED",
            entity_type="task",
            entity_id=task.id,
            project_id=project.id,
            source="portal",
            before_json={"lifecycle_status": before_status},
            after_json={"lifecycle_status": target_status},
            reason=clean_reason,
        ))
        self.db.flush()

        if target_status == "completed":
            self._auto_complete_successor_milestones(task, actor)

        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(409, "This task transition could not be completed.") from exc

        self.db.refresh(task)
        return task
