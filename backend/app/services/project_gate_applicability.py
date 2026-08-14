import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ProjectExternalApproval
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
from app.services.project_baseline import ProjectApprovalInstantiationService


class ProjectGateApplicabilityService:
    def __init__(self, db: Session):
        self.db = db

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        # Draft OR active. Applicability began as a Draft-only question, and
        # that left a one-way door: activation never required the gates to be
        # reviewed (see `activate_project`, which checks PM, Supervisor,
        # template and handover date and nothing about gates), so a project
        # could go live with every gate still `pending_review` - and then no
        # one could ever decide them. U8 instantiates approvals only from
        # APPLICABLE gates, so those projects could never have an external
        # approval at all, permanently, and the Execution tab's approvals
        # panel was empty by construction rather than by circumstance.
        #
        # Reviewing after activation is also just true to the work: a permit
        # nobody thought applied turns out to apply once the site opens.
        if project.status not in ("draft", "active"):
            raise HTTPException(
                409,
                f"Gate applicability cannot be reviewed on a {project.status.replace('_', ' ')} project.",
            )
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
        raise HTTPException(403, "Only Admin or the assigned Project Manager can view gate applicability.")

    def _require_decider(self, project_id: uuid.UUID, actor: User) -> V2Project:
        """Whether an external approval applies to a project is Admin's call.
        The assigned PM keeps read access through `_require_access` so they can
        see which approvals are blocking their site and why."""
        project = self._require_access(project_id, actor)
        if actor.role != UserRole.admin:
            raise HTTPException(403, "Only Admin can decide gate applicability.")
        return project

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
        project = self._require_decider(project_id, actor)
        gate = self._get_gate(project.id, gate_id, lock=True)
        if payload.decision == "not_applicable" and not payload.reason:
            raise HTTPException(422, "A reason is required when marking a gate Not Applicable.")

        # Ruling out a gate that already has a runtime approval is refused
        # rather than cascaded. That approval may already carry a recorded
        # decision, and quietly deleting a granted approval - or leaving it
        # orphaned behind a not-applicable gate - are both worse than saying
        # no. Nothing in this release removes an instantiated approval.
        if payload.decision == "not_applicable":
            existing = self.db.scalar(
                select(ProjectExternalApproval.id).where(
                    ProjectExternalApproval.project_gate_id == gate.id
                ).limit(1)
            )
            if existing:
                raise HTTPException(
                    409,
                    "This gate has already been instantiated as an external approval on the "
                    "execution layer and cannot be marked Not Applicable. Reject the approval instead.",
                )

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
            # An active project's execution layer already exists, so a gate
            # that has just become applicable gets its runtime approval now
            # rather than at an activation that has already happened. In the
            # same transaction as the decision: a decision that said
            # "applicable" while no approval appeared would be the same
            # silent dead end this change exists to remove.
            #
            # `instantiate_for_project` skips gates that already have one, so
            # this is safe to reach on every decision.
            if project.status == "active" and payload.decision == "applicable":
                ProjectApprovalInstantiationService(self.db).instantiate_for_project(project)
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
