"""Contracts for draft-only V2 template external-gate mutations."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.template_mutation_schemas import StrictTemplateMutationRequest

MappingClassification = Literal["exact", "broad_text", "unmapped"]


class _GateFields(StrictTemplateMutationRequest):
    code: str = Field(min_length=1, max_length=80)
    approval_name: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    external_party: str | None = Field(default=None, max_length=500)
    required_by_type: str | None = Field(default=None, max_length=120)
    required_by_value: str | None = Field(default=None, max_length=500)
    impact: str | None = Field(default=None, max_length=500)
    sequence_no: int = Field(gt=0)

    @field_validator("code", "approval_name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value

    @field_validator(
        "description", "external_party", "required_by_type", "required_by_value", "impact"
    )
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TemplateGateCreateRequest(_GateFields):
    mapping_classification: MappingClassification
    broad_mapping_text: str | None = Field(default=None, max_length=4000)
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    revision_token: str = Field(min_length=1, max_length=100)

    @field_validator("broad_mapping_text")
    @classmethod
    def strip_broad_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_mapping(self) -> "TemplateGateCreateRequest":
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Exact mapping task IDs must be unique.")
        if self.mapping_classification == "exact":
            if not self.task_ids:
                raise ValueError("Exact mappings require at least one explicit task ID.")
            if self.broad_mapping_text is not None:
                raise ValueError("Exact mappings cannot include broad mapping text.")
        elif self.mapping_classification == "broad_text":
            if not self.broad_mapping_text:
                raise ValueError("Broad-text mappings require the original mapping wording.")
            if self.task_ids:
                raise ValueError("Broad-text mappings cannot include exact task IDs.")
        else:
            if self.broad_mapping_text is not None or self.task_ids:
                raise ValueError("Unmapped gates cannot include mapping text or task IDs.")
        return self


class TemplateGateUpdateRequest(StrictTemplateMutationRequest):
    revision_token: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    approval_name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    external_party: str | None = Field(default=None, max_length=500)
    required_by_type: str | None = Field(default=None, max_length=120)
    required_by_value: str | None = Field(default=None, max_length=500)
    impact: str | None = Field(default=None, max_length=500)
    sequence_no: int | None = Field(default=None, gt=0)

    @field_validator("code", "approval_name")
    @classmethod
    def strip_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value

    @field_validator(
        "description", "external_party", "required_by_type", "required_by_value", "impact"
    )
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_change(self) -> "TemplateGateUpdateRequest":
        if not (self.model_fields_set - {"revision_token"}):
            raise ValueError("At least one gate field must be supplied.")
        return self


class TemplateGateMappingRequest(StrictTemplateMutationRequest):
    mapping_classification: MappingClassification
    broad_mapping_text: str | None = Field(default=None, max_length=4000)
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    revision_token: str = Field(min_length=1, max_length=100)

    @field_validator("broad_mapping_text")
    @classmethod
    def strip_broad_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_mapping(self) -> "TemplateGateMappingRequest":
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Exact mapping task IDs must be unique.")
        if self.mapping_classification == "exact":
            if not self.task_ids:
                raise ValueError("Exact mappings require at least one explicit task ID.")
            if self.broad_mapping_text is not None:
                raise ValueError("Exact mappings cannot include broad mapping text.")
        elif self.mapping_classification == "broad_text":
            if not self.broad_mapping_text:
                raise ValueError("Broad-text mappings require the original mapping wording.")
            if self.task_ids:
                raise ValueError("Broad-text mappings cannot include exact task IDs.")
        else:
            if self.broad_mapping_text is not None or self.task_ids:
                raise ValueError("Unmapped gates cannot include mapping text or task IDs.")
        return self


class TemplateGateMutationItem(BaseModel):
    id: uuid.UUID
    template_version_id: uuid.UUID
    code: str
    approval_name: str
    description: str | None
    external_party: str | None
    required_by_type: str | None
    required_by_value: str | None
    impact: str | None
    mapping_classification: str
    broad_mapping_text: str | None
    requires_configuration: bool
    sequence_no: int
    task_ids: list[uuid.UUID]


class TemplateGateMutationResponse(BaseModel):
    gate: TemplateGateMutationItem
    revision_token: str


class TemplateGateDeleteResponse(BaseModel):
    gate_id: uuid.UUID
    deleted: bool = True
    revision_token: str
