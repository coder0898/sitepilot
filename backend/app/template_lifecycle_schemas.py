"""Request and response contracts for controlled template lifecycle cleanup."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.template_mutation_schemas import StrictTemplateMutationRequest


class TemplateArchiveVersionRequest(StrictTemplateMutationRequest):
    revision_token: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)
    replacement_current_version_id: uuid.UUID | None = None

    @field_validator("revision_token", "reason")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value


class TemplateArchiveVersionResponse(BaseModel):
    template_id: uuid.UUID
    version_id: uuid.UUID
    version_no: int
    status: str
    is_current_published: bool
    archived_at: datetime
    replacement_current_version_id: uuid.UUID | None = None

class TemplateDeleteDraftRequest(StrictTemplateMutationRequest):
    revision_token: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("revision_token", "reason")
    @classmethod
    def require_delete_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value


class TemplateDeleteDraftResponse(BaseModel):
    template_id: uuid.UUID
    version_id: uuid.UUID
    deleted: bool
    template_deleted: bool
