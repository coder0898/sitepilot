"""Phase 3 U2: per-project dashboard (R1-R4).

Composes U1's `ProjectVisibilityService.summarize`. Previously also carried
a vendor-risk section sourced from Phase 2's `vendor_activity_events` -
removed along with vendor activity logging (Phase 2 scope, not this
release).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User
from app.schemas.project_visibility import ProjectVisibilitySummary
from app.services.project_visibility import ProjectVisibilityService

router = APIRouter(prefix="/api/v2/projects", tags=["v2-project-dashboard"])


class ProjectDashboardOut(BaseModel):
    summary: ProjectVisibilitySummary


@router.get("/{project_id}/dashboard", response_model=ProjectDashboardOut)
def project_dashboard(
    project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db),
):
    summary = ProjectVisibilityService(db).summarize(project_id, actor)
    return ProjectDashboardOut(summary=summary)
