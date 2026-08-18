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
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.project_visibility import ProjectVisibilityService

router = APIRouter(prefix="/api/v2/admin", tags=["v2-admin-visibility"])

ADMIN_ROLES = (UserRole.super_admin, UserRole.admin)


class ProjectOverviewOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    status: str
    health: str
    site: str
    pm_name: str | None
    progress_percent: int
    total_count: int
    planned_count: int
    active_count: int
    completed_count: int
    blocked_count: int
    delayed_count: int
    overdue_count: int
    no_update_count: int


def _health(status: str, blocked_count: int, delayed_count: int, overdue_count: int) -> str:
    """A single at-a-glance tag collapsing status + the summarize() signals.

    `status` alone (draft/active/on_hold/completed/archived) can't tell a
    healthy in-flight project from one accumulating overdue/blocked tasks, so
    an active project earns "delayed" or "at_risk" from those counts instead
    of a raw enum value the portfolio rollup UI expects.
    """
    if status in ("completed", "on_hold", "archived", "draft"):
        return status
    if overdue_count > 0 or delayed_count > 0:
        return "delayed"
    if blocked_count > 0:
        return "at_risk"
    return "on_track"


@router.get("/projects-overview", response_model=list[ProjectOverviewOut])
def projects_overview(
    actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db),
):
    projects = list(db.scalars(select(V2Project).order_by(V2Project.name.asc())).all())
    service = ProjectVisibilityService(db)

    pm_name_by_project = dict(
        db.execute(
            select(V2ProjectMembership.project_id, User.name)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                V2ProjectMembership.project_role == "project_manager",
                V2ProjectMembership.ends_at.is_(None),
            )
        ).all()
    )

    results = []
    for project in projects:
        summary = service.summarize(project.id, actor)
        blocked_count = len(summary.blocked_tasks)
        delayed_count = len(summary.delayed_tasks)
        overdue_count = len(summary.overdue_tasks)
        results.append(ProjectOverviewOut(
            id=project.id, code=project.code, name=project.name, status=project.status,
            health=_health(project.status, blocked_count, delayed_count, overdue_count),
            site=project.site_address, pm_name=pm_name_by_project.get(project.id),
            progress_percent=round(summary.completed_count / summary.total_count * 100) if summary.total_count else 0,
            total_count=summary.total_count, planned_count=summary.planned_count,
            active_count=summary.active_count, completed_count=summary.completed_count,
            blocked_count=blocked_count, delayed_count=delayed_count,
            overdue_count=overdue_count, no_update_count=len(summary.no_update_tasks),
        ))
    return results


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
