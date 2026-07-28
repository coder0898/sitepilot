"""Request and response contracts for template publication."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.template_mutation_schemas import StrictTemplateMutationRequest


class TemplatePublishRequest(StrictTemplateMutationRequest):
    revision_token: str = Field(min_length=1, max_length=100)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("revision_token")
    @classmethod
    def require_revision(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Revision token is required.")
        return value

    @field_validator("change_note")
    @classmethod
    def trim_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TemplatePublishResponse(BaseModel):
    template_id: uuid.UUID
    version_id: uuid.UUID
    version_no: int
    status: str
    is_current_published: bool
    published_at: datetime
    published_by: uuid.UUID
    content_hash: str
    previous_current_version_id: uuid.UUID | None = None
