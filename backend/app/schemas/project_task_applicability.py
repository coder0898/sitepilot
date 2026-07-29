import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectTaskApplicabilityDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["included", "excluded"]
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class ProjectTaskApplicabilityDecisionOut(BaseModel):
    project_id: uuid.UUID
    task_id: uuid.UUID
    code: str
    applicability: str
    included: bool
    decision_state: str
    audit_event_id: uuid.UUID
    actor_user_id: uuid.UUID
    reason: str
    decided_at: datetime


class ProjectTaskApplicabilityHistoryItem(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_name: str
    previous_decision_state: str | None
    decision_state: str
    included: bool
    reason: str
    decided_at: datetime
