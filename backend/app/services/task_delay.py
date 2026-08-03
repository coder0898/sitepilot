"""U5: delay event capture (BR-010).

`TaskDelayService.create_delay` records a `TaskDelayEvent` against an
execution-layer task. Like blockers, delays are an independently queryable
condition, not a lifecycle state: this service NEVER calls
`TaskLifecycleService.transition` and NEVER writes `Task.lifecycle_status`.

`responsible_vendor_id` is required when `responsibility_type == 'vendor'`
and must be null otherwise - validated here (422 on violation) in addition
to the DB-level check constraint added in the migration, matching this
codebase's existing double-enforcement convention (see
`TaskDelayEvent.__table_args__` in execution_models.py).

Access: any active project member (or admin/super_admin) may log a delay -
there is no separate "resolver" step for a delay event (unlike a blocker,
a delay is a point-in-time record, not an open/closed condition).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task, TaskDelayEvent
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership

DELAY_RESPONSIBILITY_TYPES = (
    "vendor", "client", "approval", "design", "site_readiness", "internal", "other",
)


class TaskDelayService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access ---------------------------------------------------------

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

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    # ---- create -----------------------------------------------------------

    def create_delay(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor: User,
        responsibility_type: str,
        reason: str,
        impact_days: int,
        responsible_vendor_id: uuid.UUID | None = None,
    ) -> TaskDelayEvent:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)

        if responsibility_type not in DELAY_RESPONSIBILITY_TYPES:
            raise HTTPException(422, "Unknown delay responsibility type.")

        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise HTTPException(422, "A delay reason is required.")

        if impact_days is None or impact_days <= 0:
            raise HTTPException(422, "impact_days must be a positive integer.")

        if responsibility_type == "vendor" and responsible_vendor_id is None:
            raise HTTPException(422, "responsible_vendor_id is required when responsibility_type is 'vendor'.")
        if responsibility_type != "vendor" and responsible_vendor_id is not None:
            raise HTTPException(422, "responsible_vendor_id must be omitted unless responsibility_type is 'vendor'.")

        delay = TaskDelayEvent(
            task_id=task.id,
            project_id=project.id,
            responsibility_type=responsibility_type,
            responsible_vendor_id=responsible_vendor_id,
            reason=clean_reason,
            impact_days=impact_days,
            recorded_by=actor.id,
        )
        self.db.add(delay)
        self.db.commit()
        self.db.refresh(delay)
        return delay
