"""Phase 2 U2: task vendor delegation (R3).

`TaskVendorAssignmentService.assign_vendor` delegates an execution-layer
task to a vendor already mapped to the task's project
(`app.services.project_vendor.ProjectVendorService`), without transferring
Site Supervisor accountability. `Task.lifecycle_status` is never read for
gating purposes here (beyond loading the row) and never written by this
service - a vendor assignment is a separate concept from BR-009's lifecycle
transitions and BR-008/BR-011's dependency-blocking checks.

This module deliberately imports nothing from `app.services.task_lifecycle`,
`app.services.task_verification`, or any other Phase 1 accountability/
dependency-resolution service - that is how non-interference with the
accountable-Supervisor derivation (R3) is proven structurally, not just by a
passing test.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2CapabilityCategory, V2Vendor, V2VendorCapability


class TaskVendorAssignmentService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access -----------------------------------------------------

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

    def _require_pm(self, project: V2Project, actor: User) -> None:
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "project_manager" in roles:
            return
        raise HTTPException(403, "Only the project's PM, or an Admin, can delegate a task to a vendor.")

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    # ---- capability matching -------------------------------------------

    def _vendor_matches_task_category(self, vendor_id: uuid.UUID, task: Task) -> bool:
        """R3/plan Approach: a null `Task.category` carries no capability
        requirement, so any mapped vendor may be assigned. Otherwise the
        vendor must hold a `V2VendorCapability` whose category `name`
        case-insensitively equals the task's category."""
        category = (task.category or "").strip()
        if not category:
            return True
        match = self.db.scalar(
            select(V2VendorCapability.id)
            .join(V2CapabilityCategory, V2VendorCapability.category_id == V2CapabilityCategory.id)
            .where(
                V2VendorCapability.vendor_id == vendor_id,
                func.lower(V2CapabilityCategory.name) == category.lower(),
            )
        )
        return match is not None

    # ---- assignment ------------------------------------------------------

    def assign_vendor(
        self, project_id: uuid.UUID, task_id: uuid.UUID, vendor_id: uuid.UUID, actor: User,
    ) -> TaskVendorAssignment:
        project = self._require_access(project_id, actor)
        self._require_pm(project, actor)
        task = self._get_task(project.id, task_id)

        vendor = self.db.get(V2Vendor, vendor_id)
        if not vendor:
            raise HTTPException(404, "Vendor not found.")
        if vendor.status != "active":
            raise HTTPException(422, "Only an active vendor can be assigned to a task.")

        mapped = self.db.scalar(
            select(ProjectVendor.id).where(
                ProjectVendor.project_id == project.id,
                ProjectVendor.vendor_id == vendor.id,
            )
        )
        if not mapped:
            raise HTTPException(422, "This vendor is not mapped to this project.")

        if not self._vendor_matches_task_category(vendor.id, task):
            raise HTTPException(422, "This vendor's capabilities do not match the task's category.")

        assignment = TaskVendorAssignment(
            task_id=task.id,
            project_id=project.id,
            vendor_id=vendor.id,
            status="pending_ack",
            assigned_by=actor.id,
        )
        self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        return assignment
