"""Plan Phase 4: task rescheduling with audit.

`TaskRescheduleService.reschedule` is the sole intentional exception to
`execution_models.Task.planned_start_date`/`planned_end_date`'s own comment
("Never rewritten by actual execution: the immutable baseline stays in
`planned_start_day`/`planned_end_day`"). Every other write path in this
codebase treats those two columns as read-only after `project_baseline.py`'s
initial resolution from the baseline day offsets. A reschedule is a
deliberate, audited replan decision - not an execution side effect - so this
service is the one place allowed to rewrite them directly; nothing else in
this codebase may.

Deliberately does NOT call `TaskLifecycleService.transition` and NEVER
writes `Task.lifecycle_status` - moving a task's planned dates is orthogonal
to its lifecycle state (BR-009), the same boundary Phase 3's advisory
overlays (`task_readiness_declaration.py`, `task_attendance.py`,
`project_gate_status_check.py`) keep against their own tables. It reuses the
existing generic `V2AuditEvent` table exactly as `task_lifecycle.py`'s own
`TASK_STATUS_CHANGED` writes do - no new table.

Access: Supervisor/PM/Admin - the same scheduling-decision authority tier
`TaskLifecycleService._require_role_for_transition` grants for `ready`
(`_SUPERVISOR_OR_PM_TARGETS`), since a reschedule is a scheduling decision,
not an execution one (it deliberately does not use the executor-driven
Internal Employee tier that `in_progress`/`submitted` use).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.outbox import OutboxService


class TaskRescheduleService:
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

    def _require_scheduler(self, project: V2Project, actor: User) -> None:
        """Supervisor, PM, or Admin/Super Admin - the same authority tier
        `TaskLifecycleService` grants scheduling decisions like `ready`.
        A reschedule is a scheduling decision, not an execution one, so
        this deliberately has no Internal-Employee-assignee fallback."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "site_supervisor" in roles or "project_manager" in roles:
            return
        raise HTTPException(403, "Only the project's Supervisor, PM, or an Admin can reschedule a task.")

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(
            select(Task).where(Task.id == task_id, Task.project_id == project_id).with_for_update()
        )
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    # ---- reschedule -----------------------------------------------------

    def reschedule(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor: User,
        new_planned_start_date: date,
        new_planned_end_date: date,
        reason: str | None,
    ) -> Task:
        project = self._require_access(project_id, actor)
        self._require_scheduler(project, actor)
        task = self._get_task(project.id, task_id)

        # Mirrors task_lifecycle.py's transition()'s own cancel-reason
        # validation style: normalize first, reject blank with 422 before
        # any mutation.
        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise HTTPException(422, "A reason is required to reschedule a task.")

        # Mirrors the DB's own ck_v2_tasks_planned_end_after_start CHECK
        # constraint direction (planned_end_date >= planned_start_date),
        # validated here in Python before any write so a rejected
        # reschedule leaves the task exactly as it was.
        if new_planned_end_date < new_planned_start_date:
            raise HTTPException(422, "The new planned end date cannot be before the new planned start date.")

        before_start = task.planned_start_date
        before_end = task.planned_end_date

        task.planned_start_date = new_planned_start_date
        task.planned_end_date = new_planned_end_date
        self.db.add(task)

        occurred_at = datetime.now(timezone.utc)
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="TASK_RESCHEDULED",
            entity_type="task",
            entity_id=task.id,
            project_id=project.id,
            source="portal",
            before_json={
                "planned_start_date": before_start.isoformat() if before_start else None,
                "planned_end_date": before_end.isoformat() if before_end else None,
            },
            after_json={
                "planned_start_date": new_planned_start_date.isoformat(),
                "planned_end_date": new_planned_end_date.isoformat(),
            },
            reason=clean_reason,
            occurred_at=occurred_at,
        ))
        self.db.flush()

        OutboxService(self.db).emit(
            event_type="task.rescheduled",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "before_planned_start_date": before_start.isoformat() if before_start else None,
                "before_planned_end_date": before_end.isoformat() if before_end else None,
                "planned_start_date": new_planned_start_date.isoformat(),
                "planned_end_date": new_planned_end_date.isoformat(),
                "reason": clean_reason,
            },
            # A task can legitimately be rescheduled more than once, unlike
            # task_lifecycle.py's status-change key (fixed per
            # target_status - re-entering the same status is rejected by
            # ALLOWED_TRANSITIONS before emit() is ever reached, so no
            # suffix is needed there). This mirrors
            # project_gate_assignment.py's reassign/unassign event keys,
            # which timestamp-suffix for the exact same "this can
            # legitimately happen more than once" reason.
            idempotency_key=f"task:{task.id}:task.rescheduled:{occurred_at.isoformat()}",
        )

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(task)
        return task
