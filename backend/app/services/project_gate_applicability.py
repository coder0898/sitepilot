import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectExternalGateApplicabilityDecision,
    V2ProjectMembership,
)
from app.schemas.project_gate_applicability import (
    ProjectGateApplicabilityDecisionIn,
    ProjectGateApplicabilityDecisionOut,
    ProjectGateApplicabilityHistoryItem,
)


class ProjectGateApplicabilityService:
    def __init__(self, db: Session):
        self.db = db

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if project.status != "draft":
            raise HTTPException(409, "Gate applicability can be reviewed only while the project is Draft.")
        if actor.role == UserRole.admin:
            return project
        if actor.role == UserRole.project_manager:
            assigned = self.db.scalar(
                select(V2ProjectMembership.id)
                .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
                .where(
                    V2ProjectMembership.project_id == project.id,
                    V2ProjectMembership.project_role == "project_manager",
                    V2ProjectMembership.ends_at.is_(None),
                    EmployeeProfile.user_id == actor.id,
                )
                .limit(1)
            )
            if assigned:
                return project
        raise HTTPException(403, "Only Admin or the assigned Project Manager can decide gate applicability.")

    def _get_gate(self, project_id: uuid.UUID, gate_id: uuid.UUID, *, lock: bool = False) -> V2ProjectExternalGate:
        statement = select(V2ProjectExternalGate).where(
            V2ProjectExternalGate.id == gate_id,
            V2ProjectExternalGate.project_id == project_id,
        )
        if lock:
            statement = statement.with_for_update()
        gate = self.db.scalar(statement)
        if not gate:
            raise HTTPException(404, "Project gate not found.")
        return gate

    def decide(
        self,
        project_id: uuid.UUID,
        gate_id: uuid.UUID,
        actor: User,
        payload: ProjectGateApplicabilityDecisionIn,
    ) -> ProjectGateApplicabilityDecisionOut:
        project = self._require_access(project_id, actor)
        gate = self._get_gate(project.id, gate_id, lock=True)
        if payload.decision == "not_applicable" and not payload.reason:
            raise HTTPException(422, "A reason is required when marking a gate Not Applicable.")

        previous_state = gate.applicability_state
        reason = payload.reason or "Gate confirmed applicable."
        now = datetime.now(timezone.utc)
        decision = V2ProjectExternalGateApplicabilityDecision(
            project_id=project.id,
            project_gate_id=gate.id,
            previous_state=previous_state,
            decision=payload.decision,
            reason=reason,
            actor_user_id=actor.id,
            decided_at=now,
        )
        gate.applicability_state = payload.decision
        audit = V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_GATE_APPLICABILITY_DECIDED",
            entity_type="project_external_gate",
            entity_id=gate.id,
            project_id=project.id,
            source="portal",
            before_json={"applicability_state": previous_state},
            after_json={"applicability_state": payload.decision},
            reason=reason,
            occurred_at=now,
        )
        try:
            self.db.add_all([decision, audit])
            self.db.flush()
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(decision)
        return ProjectGateApplicabilityDecisionOut(
            project_id=project.id,
            gate_id=gate.id,
            gate_code=gate.original_code,
            applicability_state=gate.applicability_state,
            decision_id=decision.id,
            actor_user_id=actor.id,
            reason=decision.reason,
            decided_at=decision.decided_at,
        )

    def history(
        self,
        project_id: uuid.UUID,
        gate_id: uuid.UUID,
        actor: User,
    ) -> list[ProjectGateApplicabilityHistoryItem]:
        project = self._require_access(project_id, actor)
        self._get_gate(project.id, gate_id)
        rows = self.db.execute(
            select(V2ProjectExternalGateApplicabilityDecision, User)
            .join(User, User.id == V2ProjectExternalGateApplicabilityDecision.actor_user_id)
            .where(V2ProjectExternalGateApplicabilityDecision.project_gate_id == gate_id)
            .order_by(
                V2ProjectExternalGateApplicabilityDecision.decided_at.desc(),
                V2ProjectExternalGateApplicabilityDecision.id.desc(),
            )
        ).all()
        return [
            ProjectGateApplicabilityHistoryItem(
                id=item.id,
                project_id=item.project_id,
                gate_id=item.project_gate_id,
                actor_user_id=item.actor_user_id,
                actor_name=user.name,
                previous_state=item.previous_state,
                decision=item.decision,
                reason=item.reason,
                decided_at=item.decided_at,
            )
            for item, user in rows
        ]
