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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.execution_models import FileObject, Task
from app.models import User
from app.routes.projects_v2 import get_project
from app.schemas.vendor_assignment import (
    ProjectVendorMapIn,
    ProjectVendorMappingOut,
    ProjectVendorOut,
    TaskVendorAssignmentDetailOut,
    TaskVendorAssignmentIn,
    TaskVendorAssignmentOut,
    V2VendorOut,
    VendorAcknowledgementIn,
    VendorAcknowledgementOut,
    VendorActivityEventOut,
    VendorActivityEvidenceOut,
)
from app.services.project_vendor import ProjectVendorService
from app.services.task_vendor_assignment import TaskVendorAssignmentService
from app.services.vendor_acknowledgement import VendorAcknowledgementService
from app.services.vendor_activity import VendorActivityService
from app.vendor_models import (
    ProjectVendor,
    TaskVendorAssignment,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorCapability,
    VendorAcknowledgement,
    VendorActivityEvent,
    VendorActivityEvidence,
)

router = APIRouter(prefix="/api/v2/projects", tags=["v2-vendors"])

# A bare `/api/v2/vendors` listing isn't project-scoped, so it can't live on
# the `/api/v2/projects`-prefixed router above - registered separately in
# main.py alongside it.
vendors_router = APIRouter(prefix="/api/v2/vendors", tags=["v2-vendors"])


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


@vendors_router.get("", response_model=list[V2VendorOut])
def list_vendors(
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read surface for the vendor picker (ProjectVendorPanel) - every
    active V2 vendor plus its capability category names. Any authenticated
    project-side user may view vendor master data (mirrors the legacy
    Communication Hub's unrestricted vendor read), since mapping/delegation
    itself is still PM/Admin-gated at the write routes below."""
    vendors = db.scalars(select(V2Vendor).where(V2Vendor.status == "active").order_by(V2Vendor.name)).all()
    if not vendors:
        return []
    category_rows = db.execute(
        select(V2VendorCapability.vendor_id, V2CapabilityCategory.name)
        .join(V2CapabilityCategory, V2VendorCapability.category_id == V2CapabilityCategory.id)
        .where(V2VendorCapability.vendor_id.in_([vendor.id for vendor in vendors]))
    ).all()
    categories_by_vendor: dict[uuid.UUID, list[str]] = {}
    for vendor_id, category_name in category_rows:
        categories_by_vendor.setdefault(vendor_id, []).append(category_name)
    return [
        V2VendorOut(
            id=vendor.id,
            name=vendor.name,
            engagement_type=vendor.engagement_type,
            parent_vendor_id=vendor.parent_vendor_id,
            status=vendor.status,
            contact_person=vendor.contact_person,
            phone=vendor.phone,
            whatsapp=vendor.whatsapp,
            capability_categories=categories_by_vendor.get(vendor.id, []),
        )
        for vendor in vendors
    ]


@router.post("/{project_id}/vendors", response_model=ProjectVendorOut)
def map_vendor(
    project_id: uuid.UUID,
    payload: ProjectVendorMapIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectVendorService(db).map_vendor(project_id, payload.vendor_id, actor)


@router.get("/{project_id}/vendors", response_model=list[ProjectVendorMappingOut])
def list_project_vendors(
    project_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read surface for ProjectVendorPanel's "list current mappings" and
    TaskVendorDelegationForm's vendor picker, which must only offer
    vendors already mapped to this project (plan U2 frontend test
    scenario)."""
    project = get_project(db, project_id, actor)
    rows = db.execute(
        select(ProjectVendor, V2Vendor)
        .join(V2Vendor, ProjectVendor.vendor_id == V2Vendor.id)
        .where(ProjectVendor.project_id == project.id)
        .order_by(V2Vendor.name)
    ).all()
    return [
        ProjectVendorMappingOut(
            id=mapping.id,
            project_id=mapping.project_id,
            vendor_id=mapping.vendor_id,
            vendor_name=vendor.name,
            engagement_type=vendor.engagement_type,
            parent_vendor_id=vendor.parent_vendor_id,
            mapped_by=mapping.mapped_by,
            created_at=mapping.created_at,
        )
        for mapping, vendor in rows
    ]


@router.post("/{project_id}/tasks/{task_id}/vendor-assignment", response_model=TaskVendorAssignmentOut)
def assign_vendor_to_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskVendorAssignmentIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskVendorAssignmentService(db).assign_vendor(project_id, task_id, payload.vendor_id, actor)


@router.get(
    "/{project_id}/tasks/{task_id}/vendor-assignments",
    response_model=list[TaskVendorAssignmentDetailOut],
)
def list_task_vendor_assignments(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read surface for TaskVendorDelegationForm/VendorAcknowledgementForm/
    VendorActivityForm - a task's vendor assignment(s) with full
    acknowledgement and activity history, so the UI reflects the updated
    status immediately after a portal action (plan U3 frontend test
    scenario)."""
    project = get_project(db, project_id, actor)
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project.id))
    if not task:
        raise HTTPException(404, "Task not found.")
    rows = db.execute(
        select(TaskVendorAssignment, V2Vendor)
        .join(V2Vendor, TaskVendorAssignment.vendor_id == V2Vendor.id)
        .where(TaskVendorAssignment.task_id == task.id)
        .order_by(TaskVendorAssignment.created_at.desc())
    ).all()
    return [
        TaskVendorAssignmentDetailOut(
            id=assignment.id,
            task_id=assignment.task_id,
            project_id=assignment.project_id,
            vendor_id=assignment.vendor_id,
            vendor_name=vendor.name,
            status=assignment.status,
            assigned_by=assignment.assigned_by,
            created_at=assignment.created_at,
            acknowledgements=[
                VendorAcknowledgementOut.model_validate(ack)
                for ack in db.scalars(
                    select(VendorAcknowledgement)
                    .where(VendorAcknowledgement.task_vendor_assignment_id == assignment.id)
                    .order_by(VendorAcknowledgement.created_at.asc())
                ).all()
            ],
            activity_events=[
                _activity_event_out(db, event)
                for event in db.scalars(
                    select(VendorActivityEvent)
                    .where(VendorActivityEvent.task_vendor_assignment_id == assignment.id)
                    .order_by(VendorActivityEvent.created_at.desc())
                ).all()
            ],
        )
        for assignment, vendor in rows
    ]


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
