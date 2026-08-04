"""U6: task-level support-employee assignment (BR-005).

`TaskSupportAssignmentService.assign_support` and `.end_support` manage
`TaskSupportAssignment` rows against an execution-layer task. Support
assignment NEVER changes task accountability - accountability stays
derived from the active project Supervisor (`work`) / PM (`approval_gate`)
membership per BR-004/Key Technical Decisions; this service only ever
writes to `task_support_assignments`, never to `V2ProjectMembership`.

Assignment control per BR-005 / plan Approach:
- Supervisor (or Admin/Super Admin) controls support for `work` tasks.
- PM (or Admin/Super Admin) controls follow-up support for `approval_gate`
  tasks.
- The assignee must be an active `internal_employee` project member (an
  Internal Employee currently holding an active
  `V2ProjectMembership(project_role='internal_employee')` row on this
  project).
- Unique active assignment per task/employee: an employee cannot have a
  second `task_support_assignments` row with `ends_at is null` for the
  same task - enforced here and, redundantly, at the DB level
  (`uq_v2_task_support_assignments_active_task_employee`, migration).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import SupportAssignmentChange, Task, TaskSupportAssignment
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService


class TaskSupportAssignmentService:
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

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    def _require_controller(self, project: V2Project, task: Task, actor: User) -> None:
        """BR-005: Supervisor controls support for `work` tasks; PM
        controls follow-up support for `approval_gate` tasks. Milestones
        have no support-assignment concept (no work is performed on a
        system-derived milestone)."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if task.task_kind == "work":
            if "site_supervisor" in roles:
                return
            raise HTTPException(403, "Only the project's Supervisor, or an Admin, can assign task support for work tasks.")
        if task.task_kind == "approval_gate":
            if "project_manager" in roles:
                return
            raise HTTPException(403, "Only the project's PM, or an Admin, can assign follow-up support for approval gates.")
        raise HTTPException(409, "Support assignment is not applicable to this task kind.")

    def _require_active_internal_employee(self, project_id: uuid.UUID, employee_id: uuid.UUID) -> EmployeeProfile:
        employee = self.db.get(EmployeeProfile, employee_id)
        user = self.db.get(User, employee.user_id) if employee else None
        if not employee or not user or not user.active or user.role != UserRole.internal_employee:
            raise HTTPException(422, "Select an active Internal Employee to assign as task support.")
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

    # ---- assign -----------------------------------------------------------

    def assign_support(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        employee_id: uuid.UUID,
        responsibility: str,
        actor: User,
    ) -> TaskSupportAssignment:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)
        self._require_controller(project, task, actor)
        self._require_active_internal_employee(project.id, employee_id)

        clean_responsibility = (responsibility or "").strip()
        if not clean_responsibility:
            raise HTTPException(422, "A responsibility description is required.")

        existing = self.db.scalar(
            select(TaskSupportAssignment).where(
                TaskSupportAssignment.task_id == task.id,
                TaskSupportAssignment.employee_id == employee_id,
                TaskSupportAssignment.ends_at.is_(None),
            )
        )
        if existing is not None:
            raise HTTPException(409, "This employee already has an active support assignment on this task.")

        assignment = TaskSupportAssignment(
            task_id=task.id,
            project_id=project.id,
            employee_id=employee_id,
            responsibility=clean_responsibility,
            status="active",
            assigned_by=actor.id,
        )
        self.db.add(assignment)
        try:
            self.db.flush()
            OutboxService(self.db).emit(
                event_type="task.support_assigned",
                aggregate_type="task",
                aggregate_id=task.id,
                payload={
                    "task_id": str(task.id),
                    "project_id": str(project.id),
                    "assignment_id": str(assignment.id),
                    "employee_id": str(employee_id),
                    "responsibility": clean_responsibility,
                },
                idempotency_key=f"task:{task.id}:task.support_assigned:{assignment.id}",
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(409, "This employee already has an active support assignment on this task.") from exc
        self.db.refresh(assignment)
        return assignment

    # ---- end -----------------------------------------------------------

    def end_support(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        assignment_id: uuid.UUID,
        actor: User,
        reason_code: str,
        reason_detail: str | None = None,
        replacement_employee_id: uuid.UUID | None = None,
    ) -> TaskSupportAssignment:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)
        self._require_controller(project, task, actor)

        assignment = self.db.scalar(
            select(TaskSupportAssignment).where(
                TaskSupportAssignment.id == assignment_id,
                TaskSupportAssignment.task_id == task.id,
            )
        )
        if not assignment or assignment.ends_at is not None:
            raise HTTPException(404, "Active support assignment not found for this task.")

        clean_reason_code = (reason_code or "").strip()
        if not clean_reason_code:
            raise HTTPException(422, "A reason is required to end a support assignment.")

        if replacement_employee_id is not None:
            self._require_active_internal_employee(project.id, replacement_employee_id)

        now = datetime.now(timezone.utc)
        previous_employee_id = assignment.employee_id
        assignment.ends_at = now
        assignment.status = "ended"

        self.db.add(SupportAssignmentChange(
            task_support_assignment_id=assignment.id,
            previous_employee_id=previous_employee_id,
            replacement_employee_id=replacement_employee_id,
            reason_code=clean_reason_code,
            reason_detail=(reason_detail or "").strip() or None,
            changed_by=actor.id,
        ))
        self.db.flush()

        replacement: TaskSupportAssignment | None = None
        if replacement_employee_id is not None:
            replacement = TaskSupportAssignment(
                task_id=task.id,
                project_id=project.id,
                employee_id=replacement_employee_id,
                responsibility=assignment.responsibility,
                status="active",
                assigned_by=actor.id,
            )
            self.db.add(replacement)

        try:
            OutboxService(self.db).emit(
                event_type="task.support_ended",
                aggregate_type="task",
                aggregate_id=task.id,
                payload={
                    "task_id": str(task.id),
                    "project_id": str(project.id),
                    "assignment_id": str(assignment.id),
                    "previous_employee_id": str(previous_employee_id),
                    "replacement_employee_id": str(replacement_employee_id) if replacement_employee_id else None,
                    "reason_code": clean_reason_code,
                },
                idempotency_key=f"task:{task.id}:task.support_ended:{assignment.id}",
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(409, "This support assignment change could not be completed.") from exc

        self.db.refresh(assignment)
        return replacement if replacement is not None else assignment
