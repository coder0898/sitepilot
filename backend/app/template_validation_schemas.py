"""Structured response contracts for authoritative template validation."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TemplateValidationIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    blocking: bool
    group: str
    entity_type: str
    entity_id: str | None = None
    path: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TemplateValidationSeverityCounts(BaseModel):
    errors: int
    warnings: int
    blocking: int
    non_blocking: int


class TemplateValidationEntityCounts(BaseModel):
    tasks: int
    dependencies: int
    gates: int
    exact_mappings: int


class TemplateValidationResponse(BaseModel):
    version_id: str
    version_status: str
    draft_revision: str
    validated_at: datetime
    is_valid: bool
    can_publish: bool
    issues: list[TemplateValidationIssue]
    severity_counts: TemplateValidationSeverityCounts
    entity_counts: TemplateValidationEntityCounts
