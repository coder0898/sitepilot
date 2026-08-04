"""Phase 2 U2/U3: project-vendor mapping, task vendor delegation, vendor
acknowledgement, and vendor activity/incident capture routes (R2/R3/R4/R5).

Mirrors the router/route/dependency-injection pattern established in
`app.routes.execution_tasks_v2`: a service instantiated per-request, plain
`Depends(current_user)` / `Depends(get_db)`, and a Pydantic `_Out` schema on
the response. The acknowledgement and activity routes are PM-authenticated
portal actions only - a vendor cannot start/complete/verify/approve/close a
task through this mechanism (R4); see
`app.services.vendor_acknowledgement.VendorAcknowledgementService` and
`app.services.vendor_activity.VendorActivityService`.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.execution_models import FileObject
from app.models import User
from app.schemas.vendor_assignment import (
    ProjectVendorMapIn,
    ProjectVendorOut,
    TaskVendorAssignmentIn,
    TaskVendorAssignmentOut,
    VendorAcknowledgementIn,
    VendorAcknowledgementOut,
    VendorActivityEventOut,
    VendorActivityEvidenceOut,
)
from app.services.project_vendor import ProjectVendorService
from app.services.task_vendor_assignment import TaskVendorAssignmentService
from app.services.vendor_acknowledgement import VendorAcknowledgementService
from app.services.vendor_activity import VendorActivityService
from app.vendor_models import VendorActivityEvidence

router = APIRouter(prefix="/api/v2/projects", tags=["v2-vendors"])


@router.post("/{project_id}/vendors", response_model=ProjectVendorOut)
def map_vendor(
    project_id: uuid.UUID,
    payload: ProjectVendorMapIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectVendorService(db).map_vendor(project_id, payload.vendor_id, actor)


@router.post("/{project_id}/tasks/{task_id}/vendor-assignment", response_model=TaskVendorAssignmentOut)
def assign_vendor_to_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskVendorAssignmentIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskVendorAssignmentService(db).assign_vendor(project_id, task_id, payload.vendor_id, actor)


@router.post(
    "/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/acknowledge",
    response_model=VendorAcknowledgementOut,
)
def acknowledge_vendor_assignment(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: VendorAcknowledgementIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return VendorAcknowledgementService(db).record_acknowledgement(
        project_id, task_id, assignment_id, payload.response, actor,
        channel=payload.channel, note=payload.note,
    )


def _activity_event_out(db: Session, event) -> VendorActivityEventOut:
    evidence_rows = db.scalars(
        select(VendorActivityEvidence).where(VendorActivityEvidence.vendor_activity_event_id == event.id)
    ).all()
    evidence_out = []
    for evidence in evidence_rows:
        file_object = db.get(FileObject, evidence.file_id)
        if not file_object:
            continue
        evidence_out.append(VendorActivityEvidenceOut(
            id=evidence.id,
            file_id=file_object.id,
            original_filename=file_object.original_filename,
            mime_type=file_object.mime_type,
            size_bytes=file_object.size_bytes,
        ))
    return VendorActivityEventOut(
        id=event.id,
        task_vendor_assignment_id=event.task_vendor_assignment_id,
        event_type=event.event_type,
        description=event.description,
        responsibility_decision=event.responsibility_decision,
        recorded_by=event.recorded_by,
        created_at=event.created_at,
        evidence=evidence_out,
    )


@router.post(
    "/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/activity",
    response_model=VendorActivityEventOut,
)
async def log_vendor_activity(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    assignment_id: uuid.UUID,
    event_type: str = Form(...),
    description: str = Form(...),
    responsibility_decision: str | None = Form(default=None),
    evidence: UploadFile | None = File(default=None),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    evidence_bytes = await evidence.read() if evidence is not None else None
    event = VendorActivityService(db).log_activity(
        project_id,
        task_id,
        assignment_id,
        actor,
        event_type=event_type,
        description=description,
        responsibility_decision=responsibility_decision,
        evidence_bytes=evidence_bytes,
        evidence_filename=evidence.filename if evidence is not None else None,
        evidence_content_type=evidence.content_type if evidence is not None else None,
    )
    return _activity_event_out(db, event)
