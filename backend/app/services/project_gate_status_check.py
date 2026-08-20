"""Phase 3 (3c): external-approval status-check overlay.

`ProjectGateStatusCheckService.record` records a
`ProjectExternalApprovalStatusCheck` row against a `ProjectExternalApproval`
- the assignee's self-reported health ('on_track', 'blocked', or
'need_help'). This is the direct structural analog of the BLOCKED-overlay
decision already applied to tasks (`TaskBlocker`): it is an independently
queryable, point-in-time record, never a lifecycle status. This service
NEVER writes `ProjectExternalApproval.status` and is never read by the
formal assign/submit/decide state machine (`project_gate_assignment.py`,
`project_gate_decision.py`).

Access: assignee-only - mirrors `ProjectGateSubmissionService._require_submitter`
exactly, including its error response. Not even Admin/PM may record a
status check on the assignee's behalf.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ProjectExternalApproval, ProjectExternalApprovalStatusCheck
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService

STATUS_CHECK_HEALTHS = ("on_track", "blocked", "need_help")


class ProjectGateStatusCheckService:
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

    def _require_assignee(self, approval: ProjectExternalApproval, actor: User) -> None:
        """Assignee-exclusive - not even Admin/PM may record a status check
        on the assignee's behalf, matching `ProjectGateSubmissionService.
        _require_submitter`'s framing literally."""
        if approval.assigned_to_user_id != actor.id:
            raise HTTPException(
                403,
                "Only the employee this external approval is assigned to can record a status check for it.",
            )

    # ---- record -----------------------------------------------------------

    def record(
        self,
        project_id: uuid.UUID,
        approval_id: uuid.UUID,
        actor: User,
        health: str,
        note: str | None = None,
    ) -> ProjectExternalApprovalStatusCheck:
        project = self._require_access(project_id, actor)
        approval = self._get_approval(project.id, approval_id)
        self._require_assignee(approval, actor)

        if health not in STATUS_CHECK_HEALTHS:
            raise HTTPException(422, "Unknown external-approval status-check health.")

        clean_note = (note or "").strip() or None

        status_check = ProjectExternalApprovalStatusCheck(
            approval_id=approval.id,
            project_id=project.id,
            health=health,
            note=clean_note,
            recorded_by=actor.id,
        )
        self.db.add(status_check)
        self.db.flush()

        OutboxService(self.db).emit(
            event_type="project_external_approval.status_checked",
            aggregate_type="project_external_approval",
            aggregate_id=approval.id,
            payload={
                "approval_id": str(approval.id),
                "project_id": str(project.id),
                "status_check_id": str(status_check.id),
                "health": health,
                "note": clean_note,
            },
            idempotency_key=f"project_external_approval:{approval.id}:project_external_approval.status_checked:{status_check.id}",
        )

        self.db.commit()
        self.db.refresh(status_check)
        return status_check
