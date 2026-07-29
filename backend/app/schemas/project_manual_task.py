import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectManualTaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    phase: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    planned_start_day: int = Field(ge=1)
    planned_end_day: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("title", "phase", "category", "reason")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_day_order(self):
        if self.planned_start_day > self.planned_end_day:
            raise ValueError("Planned start day cannot exceed planned end day.")
        return self


class ProjectManualTaskCreateOut(BaseModel):
    project_id: uuid.UUID
    task_id: uuid.UUID
    code: str
    sequence: int
    title: str
    phase: str
    category: str
    planned_start_day: int
    planned_end_day: int
    duration_days: int
    source_type: str
    lifecycle_status: str
    included: bool
    decision_state: str
    audit_event_id: uuid.UUID
