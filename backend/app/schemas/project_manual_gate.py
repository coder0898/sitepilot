import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectManualGateCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    external_party: str = Field(min_length=1, max_length=200)
    required_by_type: Literal["date", "project_day"]
    required_by_date: date | None = None
    required_by_day: int | None = Field(default=None, ge=1)
    affected_project_task_ids: list[uuid.UUID] = Field(default_factory=list)
    blocking: bool = True
    impact: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("title", "external_party", "impact", "reason")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_required_by_and_mapping(self):
        if self.required_by_type == "date":
            if not self.required_by_date or self.required_by_day is not None:
                raise ValueError("Required-by date is required for date-based approvals.")
        else:
            if self.required_by_day is None or self.required_by_date is not None:
                raise ValueError("Required-by project day is required for day-based approvals.")
        if self.blocking and not self.affected_project_task_ids:
            raise ValueError("A blocking approval requires at least one affected project task.")
        if len(set(self.affected_project_task_ids)) != len(self.affected_project_task_ids):
            raise ValueError("Affected project tasks must be unique.")
        return self


class ProjectManualGateCreateOut(BaseModel):
    project_id: uuid.UUID
    gate_id: uuid.UUID
    code: str
    sequence: int
    title: str
    external_party: str
    required_by_type: str
    required_by_value: str
    blocking: bool
    affected_task_count: int
    impact: str
    source_type: str
    accountable_pm_user_id: uuid.UUID
    audit_event_id: uuid.UUID
