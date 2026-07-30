import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectGateApplicabilityDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["applicable", "not_applicable"]
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class ProjectGateApplicabilityDecisionOut(BaseModel):
    project_id: uuid.UUID
    gate_id: uuid.UUID
    gate_code: str
    applicability_state: str
    decision_id: uuid.UUID
    actor_user_id: uuid.UUID
    reason: str
    decided_at: datetime


class ProjectGateApplicabilityHistoryItem(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    gate_id: uuid.UUID
    actor_user_id: uuid.UUID
    actor_name: str
    previous_state: str
    decision: str
    reason: str
    decided_at: datetime
