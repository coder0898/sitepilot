"""U13: delegate the chasing of an external approval to an Internal Employee.

WHO MAY DELEGATE: Admin and Super Admin only. External approvals are
Admin's responsibility across this codebase - `project_gate_applicability`
reserves applicability to Admin, and adding a manual gate is Admin-only
with the note that "owning the follow-up is not the same as adding it".
Handing the follow-up to somebody is the same kind of act, so it sits with
the same role.

WHAT A DELEGATE MAY THEN DO: record that the approval was submitted or
resubmitted, and nothing else (`GATE_DELEGABLE_TRANSITIONS`). Approving and
rejecting stay with Admin, because those assert what an external authority
decided rather than what the delegate did.

WHAT DELEGATION DOES NOT DO: it never moves accountability.
`ExecutionGate.accountable_pm_user_id` stays the PM whose handover the
approval blocks. A delegate chases; the PM is who escalation reaches.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ExecutionGate, ExecutionGateDelegation
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership

_ADMIN_ROLES = {UserRole.super_admin, UserRole.admin}


class ExecutionGateDelegationService:
    def __init__(self, db: Session):
        self.db = db

    # ---- guards ---------------------------------------------------------

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in _ADMIN_ROLES or self._is_project_member(project.id, actor):
            return project
        raise HTTPException(403, "You do not have access to this project.")

    def _is_project_member(self, project_id: uuid.UUID, actor: User) -> bool:
        return self.db.scalar(
            select(V2ProjectMembership.id)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.ends_at.is_(None),
                EmployeeProfile.user_id == actor.id,
            )
            .limit(1)
        ) is not None

    def _require_delegator(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self._require_access(project_id, actor)
        if actor.role not in _ADMIN_ROLES:
            raise HTTPException(
                403,
                "Only Admin can delegate an external approval. External approvals are Admin's "
                "responsibility; the chasing can be handed on, the ownership cannot.",
            )
        return project

    def _get_gate(self, project_id: uuid.UUID, gate_id: uuid.UUID, *, lock: bool = False) -> ExecutionGate:
        statement = select(ExecutionGate).where(
            ExecutionGate.id == gate_id, ExecutionGate.project_id == project_id
        )
        if lock:
            statement = statement.with_for_update()
        gate = self.db.scalar(statement)
        if not gate:
            raise HTTPException(404, "Gate not found.")
        return gate

    def _require_active_internal_employee(self, project_id: uuid.UUID, employee_id: uuid.UUID) -> EmployeeProfile:
        """The same bar `TaskSupportAssignmentService` applies: an active
        Internal Employee who is actually a member of this project. Chasing
        an approval for a project you were never put on is not a thing."""
        employee = self.db.get(EmployeeProfile, employee_id)
        user = self.db.get(User, employee.user_id) if employee else None
        if not employee or not user or not user.active or user.role != UserRole.internal_employee:
            raise HTTPException(422, "Select an active Internal Employee to chase this approval.")
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

    # ---- writes ---------------------------------------------------------

    def delegate(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, actor: User,
        employee_id: uuid.UUID, instruction: str,
    ) -> ExecutionGateDelegation:
        project = self._require_delegator(project_id, actor)
        gate = self._get_gate(project.id, gate_id, lock=True)
        self._require_active_internal_employee(project.id, employee_id)

        clean_instruction = (instruction or "").strip()
        if not clean_instruction:
            raise HTTPException(422, "Say what this person is being asked to chase.")

        existing = self.db.scalar(
            select(ExecutionGateDelegation.id).where(
                ExecutionGateDelegation.execution_gate_id == gate.id,
                ExecutionGateDelegation.employee_id == employee_id,
                ExecutionGateDelegation.status == "active",
            )
        )
        if existing:
            raise HTTPException(409, "This employee is already chasing this approval.")

        delegation = ExecutionGateDelegation(
            execution_gate_id=gate.id, project_id=project.id, employee_id=employee_id,
            instruction=clean_instruction, status="active", assigned_by=actor.id,
        )
        self.db.add(delegation)
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_GATE_DELEGATED",
            entity_type="execution_gate",
            entity_id=gate.id,
            project_id=project.id,
            source="portal",
            after_json={"employee_id": str(employee_id), "gate_code": gate.original_code},
            reason=clean_instruction,
        ))
        self.db.commit()
        self.db.refresh(delegation)
        return delegation

    def end_delegation(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, delegation_id: uuid.UUID,
        actor: User, reason: str,
    ) -> ExecutionGateDelegation:
        project = self._require_delegator(project_id, actor)
        gate = self._get_gate(project.id, gate_id)

        delegation = self.db.scalar(
            select(ExecutionGateDelegation).where(
                ExecutionGateDelegation.id == delegation_id,
                ExecutionGateDelegation.execution_gate_id == gate.id,
            ).with_for_update()
        )
        if not delegation:
            raise HTTPException(404, "Delegation not found.")
        if delegation.status != "active":
            raise HTTPException(409, "This delegation has already ended.")

        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise HTTPException(422, "A reason is required to end a delegation.")

        delegation.status = "ended"
        delegation.ends_at = datetime.now(timezone.utc)
        delegation.ended_by = actor.id
        delegation.end_reason = clean_reason
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_GATE_DELEGATION_ENDED",
            entity_type="execution_gate",
            entity_id=gate.id,
            project_id=project.id,
            source="portal",
            before_json={"employee_id": str(delegation.employee_id), "status": "active"},
            after_json={"status": "ended"},
            reason=clean_reason,
        ))
        self.db.commit()
        self.db.refresh(delegation)
        return delegation

    # ---- read -----------------------------------------------------------

    def list_delegations(self, project_id: uuid.UUID, gate_id: uuid.UUID, actor: User) -> list[ExecutionGateDelegation]:
        """Readable by any project member - who is chasing an approval is
        exactly what a PM watching their handover date needs to know."""
        project = self._require_access(project_id, actor)
        gate = self._get_gate(project.id, gate_id)
        return list(self.db.scalars(
            select(ExecutionGateDelegation)
            .where(ExecutionGateDelegation.execution_gate_id == gate.id)
            .order_by(ExecutionGateDelegation.starts_at.asc())
        ).all())
