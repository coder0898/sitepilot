"""U4: Supervisor verification decisions (BR-008).

`TaskVerificationService.verify` records a `TaskVerification` decision
against a `work` task's most recent submitted progress update, then drives
`Task.lifecycle_status` forward (or back) via U2's `TaskLifecycleService`:

- `decision == 'verified'`: `submitted -> verified`; if the task is
  `standard` class, immediately also `verified -> completed` (standard
  work needs no PM step per BR-008). `class_a` work stops at `verified`,
  awaiting a later `TaskApprovalService.approve` call.
- `decision == 'rejected'`: `submitted -> rejected -> in_progress`, per
  BR-009's literal transition table - the task reopens under Supervisor
  accountability. A correction reason (`remarks`) is required.

`approval_gate` tasks never go through this service - BR-008 says gates
skip Supervisor verification entirely; they go straight to
`TaskApprovalService`.

Verifier resolution: the project's active Supervisor, or an audited PM/
Admin fallback (BR-007's "if a Supervisor is unavailable, the project PM
replaces or temporarily assigns the Supervisor" plus Admin's general
fallback authority). `TaskApprovalService` is responsible for refusing to
let that same fallback actor also record the task's approval decision.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task, TaskProgressUpdate, TaskVerification
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.task_lifecycle import TaskLifecycleService

VERIFICATION_DECISIONS = ("verified", "rejected")


class TaskVerificationService:
    def __init__(self, db: Session):
        self.db = db
        self.lifecycle = TaskLifecycleService(db)

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

    def _require_verifier(self, project: V2Project, actor: User) -> None:
        """BR-008: the Supervisor verifies work, or an audited PM/Admin
        fallback stands in (BR-007's Supervisor-unavailable hierarchy)."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "site_supervisor" in roles or "project_manager" in roles:
            return
        raise HTTPException(
            403, "Only the project's Supervisor, or an authorized PM/Admin fallback, can verify work.",
        )

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    def _latest_submission(self, task_id: uuid.UUID) -> TaskProgressUpdate | None:
        return self.db.scalar(
            select(TaskProgressUpdate)
            .where(TaskProgressUpdate.task_id == task_id)
            .order_by(TaskProgressUpdate.created_at.desc(), TaskProgressUpdate.id.desc())
            .limit(1)
        )

    # ---- verify -----------------------------------------------------------

    def verify(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        decision: str,
        actor: User,
        remarks: str | None = None,
    ) -> Task:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)

        if task.task_kind != "work":
            raise HTTPException(
                409, "Only work tasks go through Supervisor verification; approval gates go straight to PM approval.",
            )
        if task.lifecycle_status != "submitted":
            raise HTTPException(409, "A task must be submitted before it can be verified.")
        if decision not in VERIFICATION_DECISIONS:
            raise HTTPException(422, "Verification decision must be 'verified' or 'rejected'.")

        clean_remarks = (remarks or "").strip() or None
        if decision == "rejected" and not clean_remarks:
            raise HTTPException(422, "A correction reason is required to reject a task.")

        self._require_verifier(project, actor)

        submission = self._latest_submission(task.id)
        if submission is None:
            raise HTTPException(409, "This task has no pending progress submission to verify.")

        self.db.add(TaskVerification(
            task_id=task.id,
            submission_update_id=submission.id,
            decision=decision,
            remarks=clean_remarks,
            verified_by=actor.id,
        ))
        self.db.flush()

        if decision == "rejected":
            task = self.lifecycle.transition(project.id, task.id, "rejected", actor, reason=clean_remarks)
            return self.lifecycle.transition(project.id, task.id, "in_progress", actor, reason=clean_remarks)

        task = self.lifecycle.transition(
            project.id, task.id, "verified", actor,
            reason=clean_remarks or "Verified by Supervisor.",
        )
        if task.task_class == "standard":
            task = self.lifecycle.transition(
                project.id, task.id, "completed", actor,
                reason="Standard work completes automatically after Supervisor verification (BR-008).",
            )
        return task
