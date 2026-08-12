"""45-day POC U2: record an external approval's outcome.

WRITES THE EXECUTION GATE ROW, NEVER THE PLANNING ONE. The planning-layer
`V2ProjectExternalGate.status` is a Draft-time value that activation
snapshots and never reads back. Readiness reads execution rows only, so a
status recorded on the planning row would leave the approval invisible -
the gate would still hold its tasks after somebody had approved it.

AUTHORITY IS PER TRANSITION, NOT PER ACTOR. `not_required` is one of the
two statuses that stop a gate blocking, so setting it releases every task
the gate holds back. That is a scoping decision reserved to Admin, not an
approval outcome. A single flat "may this actor record outcomes?" check
would hand every accountable PM a readiness bypass wearing a legitimate
name - so the two `not_required` moves are checked separately from the
submit/approve/reject/resubmit ones.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import (
    GATE_ADMIN_ONLY_TRANSITIONS,
    GATE_DELEGABLE_TRANSITIONS,
    GATE_STATUS_TRANSITIONS,
    EXECUTION_GATE_STATUSES,
    ExecutionGate,
    ExecutionGateDelegation,
    ExecutionGateStatusHistory,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.schemas.project_gates import ExecutionGateOut

_ADMIN_ROLES = {UserRole.super_admin, UserRole.admin}


class ProjectGateStatusService:
    def __init__(self, db: Session):
        self.db = db

    # ---- guards ---------------------------------------------------------

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        """Anyone on the project may see a gate and why it was refused. The
        rejection reason is exactly what a site team needs to read, so
        hiding history behind the recorder's authority would be backwards."""
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

    def _require_recorder(self, gate: ExecutionGate, previous_status: str, new_status: str, actor: User) -> None:
        """Authority is per transition, by the nature of the statement being
        made - not per actor. See GATE_ADMIN_ONLY_TRANSITIONS."""
        if actor.role in _ADMIN_ROLES:
            return
        if (previous_status, new_status) in GATE_DELEGABLE_TRANSITIONS:
            if self._is_active_delegate(gate, actor):
                return
            raise HTTPException(
                403,
                "Only Admin, or an Internal Employee delegated to this approval, can record that it was submitted.",
            )
        raise HTTPException(
            403,
            "Only Admin can record an external approval's outcome. External approvals are Admin's "
            "responsibility; the work of chasing one can be delegated, the decision cannot.",
        )

    def _is_active_delegate(self, gate: ExecutionGate, actor: User) -> bool:
        return self.db.scalar(
            select(ExecutionGateDelegation.id)
            .join(EmployeeProfile, EmployeeProfile.id == ExecutionGateDelegation.employee_id)
            .where(
                ExecutionGateDelegation.execution_gate_id == gate.id,
                ExecutionGateDelegation.status == "active",
                ExecutionGateDelegation.ends_at.is_(None),
                EmployeeProfile.user_id == actor.id,
            )
            .limit(1)
        ) is not None

    # ---- the write ------------------------------------------------------

    def record_status(
        self,
        project_id: uuid.UUID,
        gate_id: uuid.UUID,
        actor: User,
        new_status: str,
        reason: str | None,
    ) -> ExecutionGate:
        project = self._require_access(project_id, actor)
        gate = self._get_gate(project.id, gate_id, lock=True)

        if new_status not in EXECUTION_GATE_STATUSES:
            raise HTTPException(422, "Unknown gate status.")

        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise HTTPException(422, "A reason is required to record an approval outcome.")

        previous_status = gate.status
        if new_status == previous_status:
            raise HTTPException(409, f"This approval is already {previous_status}.")
        if new_status not in GATE_STATUS_TRANSITIONS.get(previous_status, frozenset()):
            raise HTTPException(422, f"An approval cannot move from {previous_status} to {new_status}.")

        self._require_recorder(gate, previous_status, new_status, actor)

        now = datetime.now(timezone.utc)
        gate.status = new_status
        gate.status_recorded_by_user_id = actor.id
        gate.status_recorded_at = now

        self.db.add(ExecutionGateStatusHistory(
            project_id=project.id,
            execution_gate_id=gate.id,
            previous_status=previous_status,
            new_status=new_status,
            reason=clean_reason,
            actor_user_id=actor.id,
            recorded_at=now,
        ))
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_GATE_STATUS_RECORDED",
            entity_type="execution_gate",
            entity_id=gate.id,
            project_id=project.id,
            source="portal",
            before_json={"status": previous_status},
            after_json={"status": new_status},
            reason=clean_reason,
        ))
        self.db.commit()
        self.db.refresh(gate)
        return gate

    # ---- the read -------------------------------------------------------

    def list_history(self, project_id: uuid.UUID, gate_id: uuid.UUID, actor: User) -> list[ExecutionGateStatusHistory]:
        project = self._require_access(project_id, actor)
        gate = self._get_gate(project.id, gate_id)
        return list(self.db.scalars(
            select(ExecutionGateStatusHistory)
            .where(ExecutionGateStatusHistory.execution_gate_id == gate.id)
            .order_by(ExecutionGateStatusHistory.recorded_at.asc())
        ).all())

    def list_gates(self, project_id: uuid.UUID, actor: User) -> list[ExecutionGateOut]:
        project = self._require_access(project_id, actor)
        gates = list(self.db.scalars(
            select(ExecutionGate)
            .where(ExecutionGate.project_id == project.id)
            .order_by(ExecutionGate.original_code.asc())
        ).all())
        if not gates:
            return []

        # One query for every gate's delegates rather than one per gate.
        delegates_by_gate: dict[uuid.UUID, list[uuid.UUID]] = {}
        for gate_id, user_id in self.db.execute(
            select(ExecutionGateDelegation.execution_gate_id, EmployeeProfile.user_id)
            .join(EmployeeProfile, EmployeeProfile.id == ExecutionGateDelegation.employee_id)
            .where(
                ExecutionGateDelegation.execution_gate_id.in_([g.id for g in gates]),
                ExecutionGateDelegation.status == "active",
                ExecutionGateDelegation.ends_at.is_(None),
            )
        ).all():
            delegates_by_gate.setdefault(gate_id, []).append(user_id)

        return [
            ExecutionGateOut.model_validate(gate).model_copy(
                update={"active_delegate_user_ids": delegates_by_gate.get(gate.id, [])}
            )
            for gate in gates
        ]
