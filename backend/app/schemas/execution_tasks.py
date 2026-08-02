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
