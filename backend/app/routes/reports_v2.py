"""Phase 3 U3: daily/weekly report snapshot generation and listing (R5/R6).

Generation is on-demand (`POST`), not a scheduled job - the plan's Open
Questions resolution defers the scheduling mechanism to an operational
choice that can wrap this endpoint later without a schema change.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.auth import current_user
from app.database import get_db
from app.models import User
from app.report_models import REPORT_TYPES
from app.services.report_generation import ReportGenerationService
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v2/projects", tags=["v2-reports"])


class ReportGenerateIn(BaseModel):
    report_type: str = Field(pattern="^(daily|weekly)$")
    period_start: datetime
    period_end: datetime


class ReportSnapshotOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    report_type: str
    period_start: datetime
    period_end: datetime
    version_no: int
    payload_json: dict
    generated_by: uuid.UUID
    generated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/{project_id}/reports", response_model=ReportSnapshotOut)
def generate_report(
    project_id: uuid.UUID, payload: ReportGenerateIn,
    actor: User = Depends(current_user), db: Session = Depends(get_db),
):
    snapshot = ReportGenerationService(db).generate(
        project_id, payload.report_type, payload.period_start, payload.period_end, actor,
    )
    return snapshot


@router.get("/{project_id}/reports", response_model=list[ReportSnapshotOut])
def list_reports(
    project_id: uuid.UUID, report_type: str | None = None,
    actor: User = Depends(current_user), db: Session = Depends(get_db),
):
    if report_type is not None and report_type not in REPORT_TYPES:
        report_type = None
    return ReportGenerationService(db).list_snapshots(project_id, actor, report_type)
