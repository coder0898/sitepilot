"""Phase 2 U2: project-vendor mapping (R2).

`ProjectVendorService.map_vendor` records that a vendor is engaged on a
project. Only an `active` `V2Vendor` may be mapped; a `sub_vendor`
additionally requires its parent vendor to already have an active mapping to
the *same* project - a sub-vendor can never appear on a project its parent
hasn't also been mapped to.

Access: only the project's PM (or admin/super_admin fallback) may map a
vendor - mirrors `TaskApprovalService`'s `_require_access` + role-specific
gate pattern.

This module intentionally imports nothing from `app.services.task_lifecycle`
/ `app.services.task_verification` (Phase 1's accountability-resolution
services) - project-vendor mapping has no bearing on Supervisor
accountability (R2/R3).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService
from app.vendor_models import ProjectVendor, V2Vendor


class ProjectVendorService:
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
        raise HTTPException(403, "Only the project's PM, or an Admin, can map a vendor to this project.")

    # ---- mapping ------------------------------------------------------

    def map_vendor(self, project_id: uuid.UUID, vendor_id: uuid.UUID, actor: User) -> ProjectVendor:
        project = self._require_access(project_id, actor)
        self._require_pm(project, actor)

        vendor = self.db.get(V2Vendor, vendor_id)
        if not vendor:
            raise HTTPException(404, "Vendor not found.")
        if vendor.status != "active":
            raise HTTPException(422, "Only an active vendor can be mapped to a project.")

        existing = self.db.scalar(
            select(ProjectVendor).where(
                ProjectVendor.project_id == project.id,
                ProjectVendor.vendor_id == vendor.id,
            )
        )
        if existing:
            raise HTTPException(409, "This vendor is already mapped to this project.")

        if vendor.engagement_type == "sub_vendor":
            if vendor.parent_vendor_id is None:
                raise HTTPException(422, "This sub-vendor has no parent vendor configured.")
            parent_mapped = self.db.scalar(
                select(ProjectVendor.id).where(
                    ProjectVendor.project_id == project.id,
                    ProjectVendor.vendor_id == vendor.parent_vendor_id,
                )
            )
            if not parent_mapped:
                raise HTTPException(
                    422, "This sub-vendor's parent vendor is not yet mapped to this project.",
                )

        mapping = ProjectVendor(project_id=project.id, vendor_id=vendor.id, mapped_by=actor.id)
        self.db.add(mapping)
        self.db.flush()

        # U3 (WhatsApp gate workflow): emit in the same transaction as the
        # mapping row itself, following U2's project.activated / assign_membership's
        # project.member_added discipline - a later rollback in this same
        # commit would take the event with it. Keyed on the mapping's own id
        # since a project can be mapped to many vendors over time.
        OutboxService(self.db).emit(
            event_type="project.vendor_mapped",
            aggregate_type="project",
            aggregate_id=project.id,
            payload={"project_id": str(project.id), "vendor_id": str(vendor.id)},
            idempotency_key=f"project:{project.id}:project.vendor_mapped:{mapping.id}",
        )

        self.db.commit()
        self.db.refresh(mapping)
        return mapping
