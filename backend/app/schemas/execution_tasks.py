import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.execution_models import TASK_LIFECYCLE_STATUSES

TaskLifecycleStatus = Literal[
    "planned", "ready", "in_progress", "submitted", "verified",
    "approval_pending", "rejected", "completed", "cancelled",
]


class TaskStatusTransitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_status: TaskLifecycleStatus
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None

    @field_validator("target_status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in TASK_LIFECYCLE_STATUSES:
            raise ValueError("Unknown task lifecycle status.")
        return value


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    baseline_id: uuid.UUID
    original_code: str
    title: str
    task_kind: str | None
    task_class: str | None
    lifecycle_status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskEvidenceOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    evidence_type: str
    caption: str | None
    original_filename: str
    mime_type: str
    size_bytes: int

    model_config = ConfigDict(from_attributes=True)


class TaskVerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["verified", "rejected"]
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def normalize_remarks(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def normalize_remarks(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskVerificationOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    submission_update_id: uuid.UUID
    decision: str
    remarks: str | None
    verified_by: uuid.UUID
    verified_at: datetime
    task: TaskOut

    model_config = ConfigDict(from_attributes=True)


class TaskApprovalOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    verification_id: uuid.UUID | None
    decision: str
    remarks: str | None
    decided_by: uuid.UUID
    decided_at: datetime
    task: TaskOut

    model_config = ConfigDict(from_attributes=True)


class TaskProgressUpdateOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    update_type: str
    status_claim: str | None
    note: str | None
    submitted_by: uuid.UUID
    source: str
    created_at: datetime
    evidence: list[TaskEvidenceOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
