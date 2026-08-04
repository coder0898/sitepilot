"""Phase 2 U3: vendor acknowledgement of a task assignment (R4).

`VendorAcknowledgementService.record_acknowledgement` logs a response -
'accepted', 'declined', or 'clarification_requested' - against a
`TaskVendorAssignment`, append-only (every acknowledgement row is kept, even
across multiple responses on the same assignment; a clarification request
may be followed by a later acceptance without losing the earlier row).
Only 'accepted' and 'declined' are terminal: they update the parent
assignment's `status` to match ('acknowledged' / 'declined' respectively).
'clarification_requested' never changes `status` (the assignment stays
'pending_ack') and, because it isn't terminal, never blocks a later
acknowledgement attempt on the same assignment.

This unit's route is portal-only - there is no vendor-identity auth here; a
PM records a response on the vendor's behalf per R4 (WhatsApp inbound
matching is a later unit's problem) - but `channel` is accepted as a field
so the same log can later carry WhatsApp-sourced responses without a shape
change.

This module deliberately imports nothing from `app.services.task_lifecycle`
or `app.services.task_verification` - recording a vendor acknowledgement
never mutates task lifecycle/verification/approval state (R4): a vendor
cannot start/complete/verify/approve/close a task through this mechanism.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.vendor_models import TaskVendorAssignment, VendorAcknowledgement

# `TaskVendorAssignment.status` values that mean "already resolved" - a new
# acknowledgement attempt against a resolved assignment is rejected (409).
# 'pending_ack' is not resolved (including after a 'clarification_requested'
# row, which never advances status past 'pending_ack').
RESOLVED_ASSIGNMENT_STATUSES = {"acknowledged", "declined"}

# Only these two responses are terminal; 'clarification_requested' has no
# entry here and therefore never touches TaskVendorAssignment.status.
RESPONSE_TO_ASSIGNMENT_STATUS = {"accepted": "acknowledged", "declined": "declined"}


class VendorAcknowledgementService:
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
        raise HTTPException(403, "Only the project's PM, or an Admin, can record a vendor acknowledgement.")

    def _get_assignment(
        self, project_id: uuid.UUID, task_id: uuid.UUID, assignment_id: uuid.UUID,
    ) -> TaskVendorAssignment:
        assignment = self.db.scalar(
            select(TaskVendorAssignment).where(
                TaskVendorAssignment.id == assignment_id,
                TaskVendorAssignment.task_id == task_id,
                TaskVendorAssignment.project_id == project_id,
            )
        )
        if not assignment:
            raise HTTPException(404, "Vendor assignment not found.")
        return assignment

    # ---- acknowledgement ------------------------------------------------

    def record_acknowledgement(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        assignment_id: uuid.UUID,
        response: str,
        actor: User,
        channel: str = "portal",
        note: str | None = None,
    ) -> VendorAcknowledgement:
        project = self._require_access(project_id, actor)
        self._require_pm(project, actor)
        assignment = self._get_assignment(project.id, task_id, assignment_id)

        if assignment.status in RESOLVED_ASSIGNMENT_STATUSES:
            raise HTTPException(409, "This vendor assignment has already been resolved.")

        clean_note = (note or "").strip() or None

        acknowledgement = VendorAcknowledgement(
            task_vendor_assignment_id=assignment.id,
            response=response,
            channel=channel,
            note=clean_note,
            recorded_by=actor.id,
        )
        self.db.add(acknowledgement)

        new_status = RESPONSE_TO_ASSIGNMENT_STATUS.get(response)
        if new_status:
            assignment.status = new_status

        self.db.commit()
        self.db.refresh(acknowledgement)
        return acknowledgement
