"""Phase 2 U2: request/response schemas for project-vendor mapping and task
vendor delegation (R2/R3). Follows the style established in
`app.schemas.execution_tasks`."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectVendorMapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor_id: uuid.UUID


class ProjectVendorOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    vendor_id: uuid.UUID
    mapped_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskVendorAssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor_id: uuid.UUID


class TaskVendorAssignmentOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    vendor_id: uuid.UUID
    status: str
    assigned_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
