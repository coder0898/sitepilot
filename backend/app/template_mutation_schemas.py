"""Request and response contracts for Phase 2 template mutations."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictTemplateMutationRequest(BaseModel):
    """Reject unknown request fields so protected attributes cannot be mass-assigned."""

    model_config = ConfigDict(extra="forbid")


class TemplateCreateRequest(StrictTemplateMutationRequest):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    duration_days: int = Field(gt=0)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("code", "name")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value

    @field_validator("description", "change_note")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TemplateCloneRequest(StrictTemplateMutationRequest):
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("change_note")
    @classmethod
    def trim_change_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TemplateDraftMutationResponse(BaseModel):
    template_id: uuid.UUID
    template_code: str
    template_name: str
    version_id: uuid.UUID
    version_no: int
    status: str
    duration_days: int
    task_count: int = 0
    dependency_count: int = 0
    gate_count: int = 0
    exact_mapping_count: int = 0


class TemplateCloneMutationResponse(TemplateDraftMutationResponse):
    source_version_id: uuid.UUID


class TemplateMutationConflictDetail(BaseModel):
    code: str
    message: str
    version_id: str
    expected_token: str | None = None
    current_token: str | None = None
    status: str | None = None