"""Phase 2 U2: project-vendor mapping and task vendor delegation routes
(R2/R3).

Mirrors the router/route/dependency-injection pattern established in
`app.routes.execution_tasks_v2`: a service instantiated per-request, plain
`Depends(current_user)` / `Depends(get_db)`, and a Pydantic `_Out` schema on
the response. Delegating a task to a vendor here never touches Phase 1's
Supervisor-accountability resolution or dependency graph - see
`app.services.task_vendor_assignment.TaskVendorAssignmentService`.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User
from app.schemas.vendor_assignment import (
    ProjectVendorMapIn,
    ProjectVendorOut,
    TaskVendorAssignmentIn,
    TaskVendorAssignmentOut,
)
from app.services.project_vendor import ProjectVendorService
from app.services.task_vendor_assignment import TaskVendorAssignmentService

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
