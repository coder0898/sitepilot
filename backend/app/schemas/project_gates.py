import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

class ProjectGateGenerateOut(BaseModel):
    project_id: uuid.UUID
    status: str
    generated_gate_count: int
    created_gate_count: int
    exact_mapping_count: int
    no_op: bool

class ProjectGateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    sequence: int
    approval_name: str
    description: str | None
    external_party: str | None
    required_by_type: str | None
    required_by_value: str | None
    impact: str | None
    mapping_classification: str
    broad_mapping_text: str | None
    requires_configuration: bool
    status: str
    applicability_state: str
    source: str
    accountable_pm_user_id: uuid.UUID
    accountable_pm_name: str
    exact_task_count: int
    blocking: bool
    creation_reason: str | None

class ProjectGateListOut(BaseModel):
    project_id: uuid.UUID
    total: int
    items: list[ProjectGateOut]


class ExecutionGateStatusIn(BaseModel):
    """U2. `pending` is accepted as the API spelling of `pending_review`
    because that is what the interface calls it, but only `pending_review`
    is ever stored - one state must not have two names in the database."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["not_required", "pending", "pending_review", "submitted", "approved", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("A reason is required to record an approval outcome.")
        return cleaned

    @property
    def persisted_status(self) -> str:
        return "pending_review" if self.status == "pending" else self.status


class ExecutionGateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    original_code: str
    approval_name: str
    external_party: str | None
    required_by_at: datetime | None
    status: str
    status_recorded_by_user_id: uuid.UUID | None
    status_recorded_at: datetime | None
    blocking: bool
    mapping_classification: str | None
    accountable_pm_user_id: uuid.UUID


class ExecutionGateStatusHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    previous_status: str
    new_status: str
    reason: str
    actor_user_id: uuid.UUID
    recorded_at: datetime
