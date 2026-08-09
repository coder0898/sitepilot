"""Phase 3 U2: per-project dashboard (R1-R4).

Composes U1's `ProjectVisibilityService.summarize` with a vendor-risk
section sourced from Phase 2's `vendor_activity_events`, when that table
exists - see `_vendor_activity_table_available` for the once-per-engine,
process-lifetime-cached existence check (not a per-request try/catch around
a missing-table error, per the plan's Key Technical Decisions).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User
from app.project_models import V2_SCHEMA
from app.schemas.project_visibility import ProjectVisibilitySummary
from app.services.project_visibility import ProjectVisibilityService

router = APIRouter(prefix="/api/v2/projects", tags=["v2-project-dashboard"])

# Checked once per process lifetime, not per request - Phase 2 either
# shipped before this process started or it didn't; a table doesn't appear
# mid-process outside of a migration + restart. Keyed off the request
# session's own bound engine (not a module-level `app.database.engine`
# import) so a test overriding `get_db` with an isolated engine gets a
# correct, independently-cacheable answer instead of silently checking a
# different database than the one the request actually uses.
_vendor_activity_cache: dict[int, bool] = {}


def _vendor_activity_table_available(db: Session) -> bool:
    """Any connection-level failure (e.g. the database is unreachable)
    degrades to "unavailable" rather than raising - this check must never
    be the reason a dashboard request 500s."""
    bind = db.get_bind()
    cache_key = id(bind)
    if cache_key not in _vendor_activity_cache:
        try:
            _vendor_activity_cache[cache_key] = inspect(bind).has_table("vendor_activity_events", schema=V2_SCHEMA)
        except Exception:
            _vendor_activity_cache[cache_key] = False
    return _vendor_activity_cache[cache_key]


class VendorRiskEventOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    vendor_id: uuid.UUID
    event_type: str
    description: str
    responsibility_decision: str | None
    created_at: str


def _vendor_risk_events(db: Session, project_id: uuid.UUID) -> list[VendorRiskEventOut]:
    if not _vendor_activity_table_available(db):
        return []

    # Imported lazily: importing app.vendor_models at module load time would
    # fail hard in an environment where Phase 2's tables (and thus this
    # module's mapped classes) were never migrated in - the whole point of
    # the has_table gate above.
    from app.vendor_models import TaskVendorAssignment, VendorActivityEvent

    rows = db.execute(
        select(VendorActivityEvent, TaskVendorAssignment)
        .join(TaskVendorAssignment, TaskVendorAssignment.id == VendorActivityEvent.task_vendor_assignment_id)
        .where(
            TaskVendorAssignment.project_id == project_id,
            VendorActivityEvent.event_type.in_(("delay", "rework", "incident")),
        )
        .order_by(VendorActivityEvent.created_at.desc())
    ).all()

    return [
        VendorRiskEventOut(
            id=event.id, task_id=assignment.task_id, vendor_id=assignment.vendor_id,
            event_type=event.event_type, description=event.description,
            responsibility_decision=event.responsibility_decision,
            created_at=event.created_at.isoformat(),
        )
        for event, assignment in rows
    ]


class ProjectDashboardOut(BaseModel):
    summary: ProjectVisibilitySummary
    vendor_risks: list[VendorRiskEventOut]


@router.get("/{project_id}/dashboard", response_model=ProjectDashboardOut)
def project_dashboard(
    project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db),
):
    summary = ProjectVisibilityService(db).summarize(project_id, actor)
    vendor_risks = _vendor_risk_events(db, project_id)
    return ProjectDashboardOut(summary=summary, vendor_risks=vendor_risks)
