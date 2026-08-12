"""Phase 3 U4: cross-project Admin rollup (R7).

`projects-overview` calls U1's summarize() once per project - acceptable at
Release 1's expected project count (see the plan's Risks & Dependencies);
`activity` is a wider, unscoped query over the existing `V2AuditEvent`
table, the same one `GET /{project_id}/activity` already queries per-project
- no new audit storage is introduced.

Both routes are Admin/super_admin only, reusing the existing role-bypass
pattern rather than introducing a new "Management" permission concept (BR-003).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.execution_models import GATE_NON_BLOCKING_STATUSES, ExecutionGate
from app.models import User, UserRole
from app.project_models import V2AuditEvent, V2Project
from app.services.project_visibility import ProjectVisibilityService

router = APIRouter(prefix="/api/v2/admin", tags=["v2-admin-visibility"])

ADMIN_ROLES = (UserRole.super_admin, UserRole.admin)


class ProjectOverviewOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    status: str
    total_count: int
    planned_count: int
    active_count: int
    completed_count: int
    blocked_count: int
    delayed_count: int
    overdue_count: int
    no_update_count: int
    # 45-day POC U11. Added, never replacing - every field above is
    # unchanged so the shipped rollup screen keeps working.
    handover_at_risk: bool = False
    handover_at_risk_count: int = 0
    max_delay_days: int = 0
    gates_blocking_outstanding: int = 0
    gates_rejected: int = 0


@router.get("/projects-overview", response_model=list[ProjectOverviewOut])
def projects_overview(
    actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db),
):
    projects = list(db.scalars(select(V2Project).order_by(V2Project.name.asc())).all())
    service = ProjectVisibilityService(db)

    # One query for every project's gates rather than one per project - the
    # per-project summarize() call above is already the expensive part of
    # this route and does not need company.
    gate_rows = db.scalars(select(ExecutionGate)).all()
    gates_by_project: dict[uuid.UUID, list[ExecutionGate]] = {}
    for gate in gate_rows:
        gates_by_project.setdefault(gate.project_id, []).append(gate)

    return [
        ProjectOverviewOut(
            id=project.id, code=project.code, name=project.name, status=project.status,
            total_count=summary.total_count, planned_count=summary.planned_count,
            active_count=summary.active_count, completed_count=summary.completed_count,
            blocked_count=len(summary.blocked_tasks), delayed_count=len(summary.delayed_tasks),
            overdue_count=len(summary.overdue_tasks), no_update_count=len(summary.no_update_tasks),
            handover_at_risk=summary.handover_at_risk,
            handover_at_risk_count=len(summary.handover_at_risk_tasks),
            max_delay_days=max((row.delay_days for row in summary.computed_delays), default=0),
            gates_blocking_outstanding=sum(
                1 for gate in gates_by_project.get(project.id, [])
                if gate.blocking and gate.status not in GATE_NON_BLOCKING_STATUSES
            ),
            gates_rejected=sum(
                1 for gate in gates_by_project.get(project.id, []) if gate.status == "rejected"
            ),
        )
        for project in projects
        for summary in [service.summarize(project.id, actor)]
    ]


class AdminActivityEventOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID
    actor_name: str
    reason: str
    occurred_at: str


@router.get("/activity", response_model=list[AdminActivityEventOut])
def admin_activity(
    limit: int = 100, offset: int = 0,
    actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    rows = db.execute(
        select(V2AuditEvent, User)
        .outerjoin(User, User.id == V2AuditEvent.actor_user_id)
        .order_by(V2AuditEvent.occurred_at.desc())
        .limit(limit)
        .offset(max(offset, 0))
    ).all()

    return [
        AdminActivityEventOut(
            id=event.id, project_id=event.project_id, action=event.action, entity_type=event.entity_type,
            entity_id=event.entity_id, actor_name=user.name if user else "System", reason=event.reason,
            occurred_at=event.occurred_at.isoformat(),
        )
        for event, user in rows
    ]
