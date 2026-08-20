"""Phase 3 (3b): attendance/presence capture.

`TaskAttendanceService.record` records a `TaskAttendanceEvent` row against
an execution-layer task - an internal employee's presence ('present' or
'absent'), either self-reported or recorded on their behalf. Like blockers
and delays, this is an independently queryable, point-in-time record, not a
lifecycle state: this service NEVER calls `TaskLifecycleService.transition`
and NEVER writes `Task.lifecycle_status`.

Access: either the employee recording their own attendance (actor's own
`EmployeeProfile.id` matches `employee_id`), or a Supervisor/PM/Admin
recording on someone else's behalf - mirrors
`TaskBlockerService._require_resolver`'s Supervisor/PM/Admin-fallback
pattern. A bare active-project-member check is not enough here, since this
call can name a *different* person than the actor.

`employee_id` must be an active Internal Employee project member - mirrors
`TaskSupportAssignmentService._require_active_internal_employee`.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task, TaskAttendanceEvent
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService

ATTENDANCE_STATUSES = ("present", "absent")


class TaskAttendanceService:
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

    def _require_self_or_resolver(self, project: V2Project, actor: User, employee_id: uuid.UUID) -> None:
        """Self-report, or Supervisor/PM/Admin recording on behalf of
        someone else. A bare active-project-member check would let any
        member record attendance for anyone else on the project, which
        this call's "on behalf of" shape does not permit."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        actor_employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
        if actor_employee and actor_employee.id == employee_id:
            return
        roles = self._actor_project_roles(project.id, actor)
        if "site_supervisor" in roles or "project_manager" in roles:
            return
        raise HTTPException(
            403,
            "Only the employee themselves, or the project's Supervisor/PM/Admin, can record this attendance.",
        )

    def _require_active_internal_employee(self, project_id: uuid.UUID, employee_id: uuid.UUID) -> EmployeeProfile:
        employee = self.db.get(EmployeeProfile, employee_id)
        user = self.db.get(User, employee.user_id) if employee else None
        if not employee or not user or not user.active or user.role != UserRole.internal_employee:
            raise HTTPException(422, "Select an active Internal Employee to record attendance for.")
        is_member = self.db.scalar(
            select(V2ProjectMembership.id).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.employee_id == employee_id,
                V2ProjectMembership.project_role == "internal_employee",
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        if not is_member:
            raise HTTPException(422, "The selected employee is not an active Internal Employee member of this project.")
        return employee

    # ---- record -----------------------------------------------------------

    def record(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        employee_id: uuid.UUID,
        actor: User,
        status: str,
        note: str | None = None,
    ) -> TaskAttendanceEvent:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)
        self._require_self_or_resolver(project, actor, employee_id)
        self._require_active_internal_employee(project.id, employee_id)

        if status not in ATTENDANCE_STATUSES:
            raise HTTPException(422, "Unknown attendance status.")

        clean_note = (note or "").strip() or None

        attendance = TaskAttendanceEvent(
            task_id=task.id,
            project_id=project.id,
            employee_id=employee_id,
            status=status,
            note=clean_note,
            recorded_by=actor.id,
        )
        self.db.add(attendance)
        self.db.flush()

        OutboxService(self.db).emit(
            event_type="task.attendance_recorded",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "attendance_id": str(attendance.id),
                "employee_id": str(employee_id),
                "status": status,
                "note": clean_note,
            },
            idempotency_key=f"task:{task.id}:task.attendance_recorded:{attendance.id}",
        )

        self.db.commit()
        self.db.refresh(attendance)
        return attendance
