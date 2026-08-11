import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership, V2ProjectTask
from app.schemas.project_task_applicability import (
    ProjectTaskApplicabilityDecisionIn,
    ProjectTaskApplicabilityDecisionOut,
    ProjectTaskApplicabilityHistoryItem,
)


class ProjectTaskApplicabilityService:
    def __init__(self, db: Session):
        self.db = db

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role == UserRole.admin:
            return project
        if actor.role == UserRole.project_manager:
            assigned = self.db.scalar(
                select(V2ProjectMembership.id)
                .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
                .where(
                    V2ProjectMembership.project_id == project_id,
                    V2ProjectMembership.project_role == "project_manager",
                    V2ProjectMembership.ends_at.is_(None),
                    EmployeeProfile.user_id == actor.id,
                )
                .limit(1)
            )
            if assigned:
                return project
        raise HTTPException(
            403,
            "Only Admin or the assigned Project Manager can view conditional task applicability.",
        )

    def _require_decider(self, project_id: uuid.UUID, actor: User) -> V2Project:
        """Scope decisions are Admin's to make. The assigned PM keeps read
        access through `_require_access` - they see what was decided and why,
        they just cannot change it. Deciding what is in scope for a project is
        a controlled call, made centrally."""
        project = self._require_access(project_id, actor)
        if actor.role != UserRole.admin:
            raise HTTPException(403, "Only Admin can decide conditional task applicability.")
        return project

    def history(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor: User,
    ) -> list[ProjectTaskApplicabilityHistoryItem]:
        project = self._require_access(project_id, actor)
        task_exists = self.db.scalar(
            select(V2ProjectTask.id)
            .where(V2ProjectTask.id == task_id, V2ProjectTask.project_id == project.id)
            .limit(1)
        )
        if not task_exists:
            raise HTTPException(404, "Project task not found.")

        rows = self.db.execute(
            select(V2AuditEvent, User)
            .outerjoin(User, User.id == V2AuditEvent.actor_user_id)
            .where(
                V2AuditEvent.project_id == project.id,
                V2AuditEvent.entity_type == "project_task",
                V2AuditEvent.entity_id == task_id,
                V2AuditEvent.action == "PROJECT_TASK_APPLICABILITY_DECIDED",
            )
            .order_by(V2AuditEvent.occurred_at.desc(), V2AuditEvent.id.desc())
        ).all()
        return [ProjectTaskApplicabilityHistoryItem(
            id=event.id,
            project_id=project.id,
            task_id=task_id,
            actor_user_id=event.actor_user_id,
            actor_name=user.name if user else "System",
            previous_decision_state=(event.before_json or {}).get("decision_state"),
            decision_state=(event.after_json or {}).get("decision_state", "unknown"),
            included=bool((event.after_json or {}).get("included")),
            reason=event.reason or "No reason recorded.",
            decided_at=event.occurred_at,
        ) for event, user in rows]

    def decide(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor: User,
        payload: ProjectTaskApplicabilityDecisionIn,
    ) -> ProjectTaskApplicabilityDecisionOut:
        project = self._require_decider(project_id, actor)
        task = self.db.scalar(
            select(V2ProjectTask)
            .where(V2ProjectTask.id == task_id, V2ProjectTask.project_id == project.id)
            .with_for_update()
        )
        if not task:
            raise HTTPException(404, "Project task not found.")
        if task.applicability != "conditional":
            raise HTTPException(
                409,
                "Mandatory template tasks are locked included and cannot receive an applicability decision.",
            )
        if payload.decision == "excluded" and not payload.reason:
            raise HTTPException(422, "A reason is required when excluding a conditional task.")

        before = {
            "included": task.included,
            "decision_state": task.decision_state,
        }
        task.included = payload.decision == "included"
        task.decision_state = payload.decision
        reason = payload.reason or "Conditional task re-included."
        audit = V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_TASK_APPLICABILITY_DECIDED",
            entity_type="project_task",
            entity_id=task.id,
            project_id=project.id,
            source="portal",
            before_json=before,
            after_json={
                "included": task.included,
                "decision_state": task.decision_state,
            },
            reason=reason,
            occurred_at=datetime.now(timezone.utc),
        )
        try:
            self.db.add(audit)
            self.db.flush()
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(audit)
        return ProjectTaskApplicabilityDecisionOut(
            project_id=project.id,
            task_id=task.id,
            code=task.original_code,
            applicability=task.applicability,
            included=task.included,
            decision_state=task.decision_state,
            audit_event_id=audit.id,
            actor_user_id=actor.id,
            reason=audit.reason,
            decided_at=audit.occurred_at,
        )
