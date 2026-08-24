"""Phase 3 (3a): readiness declaration capture.

`TaskReadinessDeclarationService.declare` records a `TaskReadinessDeclaration`
row against an execution-layer task - a project member's self-reported
readiness signal ('ready', 'issue', or 'need_help'). Like blockers and
delays, this is an independently queryable, point-in-time record, not a
lifecycle state: this service NEVER calls `TaskLifecycleService.transition`
and NEVER writes `Task.lifecycle_status`.

Deliberately does not touch `task_readiness.py`, which stays a pure derived
projection over already-persisted facts (approvals, dependencies) per that
service's own docstring - a declaration is a human's signal, not a fact the
derived projection is computed from.

Access: any active project member (or admin/super_admin) may declare -
mirrors `TaskBlockerService._require_access`.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task, TaskReadinessDeclaration
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService

READINESS_DECLARATION_STATUSES = ("ready", "issue", "need_help")


class TaskReadinessDeclarationService:
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

    # ---- declare -----------------------------------------------------------

    def declare(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor: User,
        status: str,
        note: str | None = None,
    ) -> TaskReadinessDeclaration:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)

        if status not in READINESS_DECLARATION_STATUSES:
            raise HTTPException(422, "Unknown readiness declaration status.")

        clean_note = (note or "").strip() or None

        declaration = TaskReadinessDeclaration(
            task_id=task.id,
            project_id=project.id,
            declared_by=actor.id,
            status=status,
            note=clean_note,
        )
        self.db.add(declaration)
        self.db.flush()

        OutboxService(self.db).emit(
            event_type="task.readiness_declared",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "declaration_id": str(declaration.id),
                "status": status,
                "note": clean_note,
            },
            idempotency_key=f"task:{task.id}:task.readiness_declared:{declaration.id}",
        )

        self.db.commit()
        self.db.refresh(declaration)
        return declaration
