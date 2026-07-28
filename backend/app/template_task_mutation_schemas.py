"""Contracts for draft-only V2 template task mutations."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.template_mutation_schemas import StrictTemplateMutationRequest


ScheduleClassification = Literal["pre_activation", "execution"]
TaskApplicability = Literal["mandatory", "conditional"]


class TemplateTaskCreateRequest(StrictTemplateMutationRequest):
    code: str = Field(min_length=1, max_length=80)
    sequence_no: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    schedule_classification: ScheduleClassification
    planned_start_day: int | None = Field(default=None, ge=1)
    planned_end_day: int | None = Field(default=None, ge=1)
    phase: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    applicability: TaskApplicability = "mandatory"
    task_class: str | None = Field(default=None, max_length=120)
    task_kind: str | None = Field(default=None, max_length=120)
    evidence_required: bool = False
    duration_days: int | None = Field(default=None, gt=0)
    revision_token: str = Field(min_length=1, max_length=100)

    @field_validator("code", "title")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value

    @field_validator("description", "phase", "category", "task_class", "task_kind")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TemplateTaskUpdateRequest(StrictTemplateMutationRequest):
    revision_token: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=80)
    sequence_no: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    schedule_classification: ScheduleClassification | None = None
    planned_start_day: int | None = Field(default=None, ge=1)
    planned_end_day: int | None = Field(default=None, ge=1)
    phase: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    applicability: TaskApplicability | None = None
    task_class: str | None = Field(default=None, max_length=120)
    task_kind: str | None = Field(default=None, max_length=120)
    evidence_required: bool | None = None
    duration_days: int | None = Field(default=None, gt=0)

    @field_validator("code", "title")
    @classmethod
    def normalize_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value

    @field_validator("description", "phase", "category", "task_class", "task_kind")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_change(self) -> "TemplateTaskUpdateRequest":
        if not (self.model_fields_set - {"revision_token"}):
            raise ValueError("At least one task field must be supplied.")
        return self


class TemplateTaskReorderItem(BaseModel):
    task_id: uuid.UUID
    sequence_no: int = Field(gt=0)


class TemplateTaskReorderRequest(StrictTemplateMutationRequest):
    revision_token: str = Field(min_length=1, max_length=100)
    items: list[TemplateTaskReorderItem] = Field(min_length=1)


class TemplateTaskMutationItem(BaseModel):
    id: uuid.UUID
    template_version_id: uuid.UUID
    code: str
    sequence_no: int
    title: str
    description: str | None
    schedule_classification: str
    planned_start_day: int | None
    planned_end_day: int | None
    phase: str | None
    category: str | None
    applicability: str
    task_class: str | None
    task_kind: str | None
    evidence_required: bool
    duration_days: int | None


class TemplateTaskMutationResponse(BaseModel):
    task: TemplateTaskMutationItem
    revision_token: str


class TemplateTaskDeleteResponse(BaseModel):
    task_id: uuid.UUID
    deleted: bool = True
    revision_token: str


class TemplateTaskReorderResult(BaseModel):
    task_id: uuid.UUID
    code: str
    sequence_no: int


class TemplateTaskReorderResponse(BaseModel):
    items: list[TemplateTaskReorderResult]
    revision_token: str