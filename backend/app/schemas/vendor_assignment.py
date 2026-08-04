"""Phase 2 U2/U3: request/response schemas for project-vendor mapping, task
vendor delegation, vendor acknowledgement, and vendor activity/incident
capture (R2/R3/R4/R5). Follows the style established in
`app.schemas.execution_tasks`."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class VendorAcknowledgementIn(BaseModel):
    """Phase 2 U3: R4 - a PM-submitted, portal-channel acknowledgement
    recorded on the vendor's behalf. `channel` defaults to 'portal' since
    that is the only channel this unit's route accepts; the field exists so
    the underlying log can later carry WhatsApp-sourced responses without a
    shape change."""

    model_config = ConfigDict(extra="forbid")
    response: Literal["accepted", "declined", "clarification_requested"]
    channel: Literal["portal", "whatsapp", "system"] = "portal"
    note: str | None = Field(default=None, max_length=2000)


class VendorAcknowledgementOut(BaseModel):
    id: uuid.UUID
    task_vendor_assignment_id: uuid.UUID
    response: str
    channel: str
    note: str | None
    recorded_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VendorActivityEvidenceOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int

    model_config = ConfigDict(from_attributes=True)


class VendorActivityEventOut(BaseModel):
    id: uuid.UUID
    task_vendor_assignment_id: uuid.UUID
    event_type: str
    description: str
    responsibility_decision: str | None
    recorded_by: uuid.UUID
    created_at: datetime
    evidence: list[VendorActivityEvidenceOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
