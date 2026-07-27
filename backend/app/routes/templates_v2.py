"""Read-only V2 template list, version, and task APIs."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.services.template_access import require_template_reader
from app.services.template_queries import TemplateQueryService
from app.template_schemas import (
    PaginationMetadata,
    TemplateDependencyListResponse,
    TemplateGateListResponse,
    TemplateListResponse,
    TemplateTaskListResponse,
    TemplateVersionResponse,
)


router = APIRouter(prefix="/api/v2/templates", tags=["v2-templates"])


@router.get("", response_model=TemplateListResponse)
def list_templates(
    search: str | None = Query(default=None, max_length=200),
    status_filter: Literal["draft", "published"] | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    actor: User = Depends(require_template_reader),
    db: Session = Depends(get_db),
) -> TemplateListResponse:
    statuses = {status_filter} if actor.role == UserRole.super_admin and status_filter else None
    result = TemplateQueryService(db).list_versions(
        actor, search=search, statuses=statuses, page=page, page_size=page_size
    )
    return TemplateListResponse(
        items=result.items,
        pagination=PaginationMetadata.from_result(
            page=result.page, page_size=result.page_size, total=result.total
        ),
    )


@router.get("/versions/{version_id}", response_model=TemplateVersionResponse)
def get_template_version(
    version_id: uuid.UUID,
    actor: User = Depends(require_template_reader),
    db: Session = Depends(get_db),
) -> TemplateVersionResponse:
    return TemplateVersionResponse.model_validate(TemplateQueryService(db).get_version(actor, version_id))


@router.get("/versions/{version_id}/tasks", response_model=TemplateTaskListResponse)
def list_template_tasks(
    version_id: uuid.UUID,
    search: str | None = Query(default=None, max_length=200),
    schedule_classification: Literal["pre_activation", "execution"] | None = None,
    phase: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=120),
    applicability: Literal["mandatory", "conditional"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    actor: User = Depends(require_template_reader),
    db: Session = Depends(get_db),
) -> TemplateTaskListResponse:
    result = TemplateQueryService(db).list_tasks(
        actor,
        version_id,
        search=search,
        schedule_classification=schedule_classification,
        phase=phase,
        category=category,
        applicability=applicability,
        page=page,
        page_size=page_size,
    )
    return TemplateTaskListResponse(
        items=result.items,
        pagination=PaginationMetadata.from_result(
            page=result.page, page_size=result.page_size, total=result.total
        ),
    )


@router.get("/versions/{version_id}/dependencies", response_model=TemplateDependencyListResponse)
def list_template_dependencies(
    version_id: uuid.UUID,
    search: str | None = Query(default=None, max_length=200),
    dependency_type: Literal["finish_to_start", "start_to_start"] | None = None,
    blocking: bool | None = None,
    validation_state: Literal["valid", "invalid"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    actor: User = Depends(require_template_reader),
    db: Session = Depends(get_db),
) -> TemplateDependencyListResponse:
    result = TemplateQueryService(db).list_dependencies(
        actor,
        version_id,
        search=search,
        dependency_type=dependency_type,
        blocking=blocking,
        validation_state=validation_state,
        page=page,
        page_size=page_size,
    )
    return TemplateDependencyListResponse(
        items=result.items,
        pagination=PaginationMetadata.from_result(
            page=result.page, page_size=result.page_size, total=result.total
        ),
        summary=result.summary,
    )

@router.get("/versions/{version_id}/gates", response_model=TemplateGateListResponse)
def list_template_gates(
    version_id: uuid.UUID,
    search: str | None = Query(default=None, max_length=200),
    mapping_classification: Literal["exact", "broad_text", "unmapped"] | None = None,
    requires_configuration: bool | None = None,
    external_party: str | None = Query(default=None, max_length=200),
    validation_state: Literal["valid", "invalid"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    actor: User = Depends(require_template_reader),
    db: Session = Depends(get_db),
) -> TemplateGateListResponse:
    result = TemplateQueryService(db).list_gates(
        actor,
        version_id,
        search=search,
        mapping_classification=mapping_classification,
        requires_configuration=requires_configuration,
        external_party=external_party,
        validation_state=validation_state,
        page=page,
        page_size=page_size,
    )
    return TemplateGateListResponse(
        items=result.items,
        pagination=PaginationMetadata.from_result(
            page=result.page, page_size=result.page_size, total=result.total
        ),
    )
