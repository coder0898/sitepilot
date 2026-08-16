"""Plan: External Approval Gate Assignment & Evidence Lifecycle (U3).

`ProjectGateAssignmentService` owns the assignment edge of the external
approval lifecycle: `assign()` moves a gate from `unassigned` to `assigned`,
and `reassign()`/`unassign()` cover the case where the originally assigned
employee becomes unavailable mid-flow (R8) - a deliberately separate
operation from the reject/resubmit loop that `ProjectGateDecisionService.
decide()` drives (see the plan's Key Technical Decisions).

Authority is Admin-only throughout (R1/R3/R6): there is no PM-fallback tier
here, unlike `TaskApprovalService`/`ProjectGateDecisionService` - a
deliberate divergence, not an oversight.

The assignee validation mirrors `TaskSupportAssignmentService.
_require_active_internal_employee` (an active `internal_employee` project
member), resolved from `assigned_to_user_id`'s FK to `users` rather than
`task_support_assignments.employee_id`'s FK to `employee_profiles`, to stay
consistent with `decided_by`/`assigned_by` on this same table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ProjectExternalApproval
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.outbox import OutboxService


class ProjectGateAssignmentService:
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

    def _require_assigner(self, actor: User) -> None:
        """R1/R3/R6: assignment, like the decision itself, is Admin-only -
        no PM-fallback tier for this flow."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        raise HTTPException(403, "Only an Admin can assign an external approval gate.")

    def _get_approval(self, project_id: uuid.UUID, approval_id: uuid.UUID) -> ProjectExternalApproval:
        approval = self.db.scalar(
            select(ProjectExternalApproval).where(
                ProjectExternalApproval.id == approval_id,
                ProjectExternalApproval.project_id == project_id,
            )
        )
        if not approval:
            raise HTTPException(404, "External approval not found for this project.")
        return approval

    def _require_active_internal_employee(self, project_id: uuid.UUID, user_id: uuid.UUID) -> User:
        """Mirrors TaskSupportAssignmentService._require_active_internal_employee,
        resolved from the user side since this table's assignee column is a
        `users` FK (consistent with `decided_by`), not an `employee_profiles`
        FK."""
        user = self.db.get(User, user_id)
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))
        if not user or not employee or not user.active or user.role != UserRole.internal_employee:
            raise HTTPException(422, "Select an active Internal Employee to assign this external approval to.")
        is_member = self.db.scalar(
            select(V2ProjectMembership.id).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.project_role == "internal_employee",
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        if not is_member:
            raise HTTPException(422, "The selected employee is not an active Internal Employee member of this project.")
        return user

    # ---- assign -------------------------------------------------------

    def assign(
        self, project_id: uuid.UUID, approval_id: uuid.UUID, assignee_user_id: uuid.UUID, actor: User,
    ) -> ProjectExternalApproval:
        project = self._require_access(project_id, actor)
        self._require_assigner(actor)
        approval = self._get_approval(project.id, approval_id)

        if approval.status != "unassigned":
            raise HTTPException(
                409,
                f"This external approval is already {approval.status}; use reassign or unassign instead of assign.",
            )

        self._require_active_internal_employee(project.id, assignee_user_id)

        return self._write_assignment(
            project, approval, assignee_user_id, actor,
            action="PROJECT_EXTERNAL_APPROVAL_ASSIGNED",
            event_type="project_external_approval.assigned",
            previous_status=approval.status,
        )

    # ---- reassign / unassign -------------------------------------------

    def reassign(
        self, project_id: uuid.UUID, approval_id: uuid.UUID, new_assignee_user_id: uuid.UUID, actor: User,
    ) -> ProjectExternalApproval:
        """R8: covers the assignee-unavailable case - moves an `assigned`/
        `submitted` gate to a different employee. Distinct from the reject
        loop, which always returns to the *same* assignee."""
        project = self._require_access(project_id, actor)
        self._require_assigner(actor)
        approval = self._get_approval(project.id, approval_id)

        if approval.status not in ("assigned", "submitted"):
            raise HTTPException(
                409,
                f"This external approval is {approval.status}; only an assigned or submitted gate can be reassigned.",
            )

        self._require_active_internal_employee(project.id, new_assignee_user_id)

        return self._write_assignment(
            project, approval, new_assignee_user_id, actor,
            action="PROJECT_EXTERNAL_APPROVAL_REASSIGNED",
            event_type="project_external_approval.reassigned",
            previous_status=approval.status,
        )

    def unassign(self, project_id: uuid.UUID, approval_id: uuid.UUID, actor: User) -> ProjectExternalApproval:
        project = self._require_access(project_id, actor)
        self._require_assigner(actor)
        approval = self._get_approval(project.id, approval_id)

        if approval.status not in ("assigned", "submitted"):
            raise HTTPException(
                409,
                f"This external approval is {approval.status}; only an assigned or submitted gate can be unassigned.",
            )

        previous_status = approval.status
        previous_assignee = approval.assigned_to_user_id
        approval.status = "unassigned"
        approval.assigned_to_user_id = None
        approval.assigned_by = None
        approval.assigned_at = None
        self.db.add(approval)

        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_EXTERNAL_APPROVAL_UNASSIGNED",
            entity_type="project_external_approval",
            entity_id=approval.id,
            project_id=project.id,
            source="portal",
            before_json={"status": previous_status, "assigned_to_user_id": str(previous_assignee) if previous_assignee else None},
            after_json={"status": "unassigned", "assigned_to_user_id": None},
            reason="External approval unassigned by Admin.",
            occurred_at=datetime.now(timezone.utc),
        ))
        self.db.flush()

        OutboxService(self.db).emit(
            event_type="project_external_approval.unassigned",
            aggregate_type="project_external_approval",
            aggregate_id=approval.id,
            payload={
                "approval_id": str(approval.id),
                "project_id": str(project.id),
                "previous_assignee_id": str(previous_assignee) if previous_assignee else None,
                "unassigned_by": str(actor.id),
            },
            idempotency_key=f"project_external_approval:{approval.id}:project_external_approval.unassigned:{datetime.now(timezone.utc).isoformat()}",
        )

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(approval)
        return approval

    # ---- shared write path ----------------------------------------------

    def _write_assignment(
        self,
        project: V2Project,
        approval: ProjectExternalApproval,
        assignee_user_id: uuid.UUID,
        actor: User,
        *,
        action: str,
        event_type: str,
        previous_status: str,
    ) -> ProjectExternalApproval:
        assigned_at = datetime.now(timezone.utc)
        previous_assignee = approval.assigned_to_user_id
        approval.status = "assigned"
        approval.assigned_to_user_id = assignee_user_id
        approval.assigned_by = actor.id
        approval.assigned_at = assigned_at
        self.db.add(approval)

        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action=action,
            entity_type="project_external_approval",
            entity_id=approval.id,
            project_id=project.id,
            source="portal",
            before_json={"status": previous_status, "assigned_to_user_id": str(previous_assignee) if previous_assignee else None},
            after_json={"status": "assigned", "assigned_to_user_id": str(assignee_user_id)},
            reason=f"External approval assigned by Admin ({action}).",
            occurred_at=assigned_at,
        ))
        self.db.flush()

        OutboxService(self.db).emit(
            event_type=event_type,
            aggregate_type="project_external_approval",
            aggregate_id=approval.id,
            payload={
                "approval_id": str(approval.id),
                "project_id": str(project.id),
                "assigned_to_user_id": str(assignee_user_id),
                "assigned_by": str(actor.id),
                "assigned_at": assigned_at.isoformat(),
            },
            idempotency_key=f"project_external_approval:{approval.id}:{event_type}:{assigned_at.isoformat()}",
        )

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(approval)
        return approval
