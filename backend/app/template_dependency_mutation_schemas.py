"""Contracts for draft-only V2 template dependency mutations."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.template_mutation_schemas import StrictTemplateMutationRequest

DependencyType = Literal["finish_to_start", "start_to_start"]


class TemplateDependencyCreateRequest(StrictTemplateMutationRequest):
    predecessor_task_id: uuid.UUID
    successor_task_id: uuid.UUID
    dependency_type: DependencyType
    blocking: bool
    rule_text: str = Field(min_length=1, max_length=2000)
    sequence_no: int = Field(gt=0)
    revision_token: str = Field(min_length=1, max_length=100)

    @field_validator("rule_text")
    @classmethod
    def normalize_rule_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Rule text cannot be blank.")
        return value


class TemplateDependencyUpdateRequest(StrictTemplateMutationRequest):
    revision_token: str = Field(min_length=1, max_length=100)
    predecessor_task_id: uuid.UUID | None = None
    successor_task_id: uuid.UUID | None = None
    dependency_type: DependencyType | None = None
    blocking: bool | None = None
    rule_text: str | None = Field(default=None, max_length=2000)
    sequence_no: int | None = Field(default=None, gt=0)

    @field_validator("rule_text")
    @classmethod
    def normalize_rule_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Rule text cannot be blank.")
        return value

    @model_validator(mode="after")
    def require_change(self) -> "TemplateDependencyUpdateRequest":
        if not (self.model_fields_set - {"revision_token"}):
            raise ValueError("At least one dependency field must be supplied.")
        return self


class TemplateDependencyMutationItem(BaseModel):
    id: uuid.UUID
    template_version_id: uuid.UUID
    predecessor_task_id: uuid.UUID
    successor_task_id: uuid.UUID
    dependency_type: str
    blocking: bool
    rule_text: str | None
    sequence_no: int


class TemplateDependencyMutationResponse(BaseModel):
    dependency: TemplateDependencyMutationItem
    revision_token: str


class TemplateDependencyDeleteResponse(BaseModel):
    dependency_id: uuid.UUID
    deleted: bool = True
    revision_token: str
