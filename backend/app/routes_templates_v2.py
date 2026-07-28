"""V2 template query and controlled mutation APIs."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.services.template_access import require_template_reader
from app.services.template_commands import TemplateCommandService
from app.services.template_task_commands import TemplateTaskCommandService
from app.services.template_dependency_commands import TemplateDependencyCommandService
from app.services.template_gate_commands import TemplateGateCommandService
from app.services.template_draft_validator import TemplateDraftValidationService
from app.services.template_mutation_access import (
    concurrency_token,
    require_template_mutator,
)
from app.services.template_queries import TemplateQueryService
from app.template_schemas import (
    PaginationMetadata,
    TemplateDependencyListResponse,
    TemplateGateListResponse,
    TemplateListResponse,
    TemplateTaskListResponse,
    TemplateVersionResponse,
)
from app.template_mutation_schemas import (
    TemplateCloneMutationResponse,
    TemplateCloneRequest,
    TemplateCreateRequest,
    TemplateDraftMutationResponse,
)

from app.template_dependency_mutation_schemas import (
    TemplateDependencyCreateRequest,
    TemplateDependencyDeleteResponse,
    TemplateDependencyMutationResponse,
    TemplateDependencyUpdateRequest,
)
from app.template_gate_mutation_schemas import (
    TemplateGateCreateRequest,
    TemplateGateDeleteResponse,
    TemplateGateMappingRequest,
    TemplateGateMutationResponse,
    TemplateGateUpdateRequest,
)
from app.template_validation_schemas import TemplateValidationResponse
from app.template_task_mutation_schemas import (
    TemplateTaskCreateRequest,
    TemplateTaskDeleteResponse,
    TemplateTaskMutationResponse,
    TemplateTaskReorderRequest,
    TemplateTaskReorderResponse,
    TemplateTaskUpdateRequest,
)
router = APIRouter(prefix="/api/v2/templates", tags=["v2-templates"])

@router.post("/versions/{version_id}/validate", response_model=TemplateValidationResponse)
def validate_template_version(
    version_id: uuid.UUID,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateValidationResponse:
    return TemplateDraftValidationService(db).validate(actor, version_id)

@router.post("", response_model=TemplateDraftMutationResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreateRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateDraftMutationResponse:
    return TemplateCommandService(db).create_template(actor, payload)


@router.post(
    "/versions/{version_id}/clone",
    response_model=TemplateCloneMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def clone_template_version(
    version_id: uuid.UUID,
    payload: TemplateCloneRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateCloneMutationResponse:
    return TemplateCommandService(db).clone_version(actor, version_id, payload)


@router.post(
    "/versions/{version_id}/tasks",
    response_model=TemplateTaskMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_template_task(
    version_id: uuid.UUID,
    payload: TemplateTaskCreateRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateTaskMutationResponse:
    return TemplateTaskCommandService(db).create_task(actor, version_id, payload)


@router.post(
    "/versions/{version_id}/tasks/reorder",
    response_model=TemplateTaskReorderResponse,
)
def reorder_template_tasks(
    version_id: uuid.UUID,
    payload: TemplateTaskReorderRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateTaskReorderResponse:
    return TemplateTaskCommandService(db).reorder_tasks(actor, version_id, payload)


@router.patch(
    "/versions/{version_id}/tasks/{task_id}",
    response_model=TemplateTaskMutationResponse,
)
def update_template_task(
    version_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TemplateTaskUpdateRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateTaskMutationResponse:
    return TemplateTaskCommandService(db).update_task(actor, version_id, task_id, payload)


@router.delete(
    "/versions/{version_id}/tasks/{task_id}",
    response_model=TemplateTaskDeleteResponse,
)
def delete_template_task(
    version_id: uuid.UUID,
    task_id: uuid.UUID,
    revision_token: str = Query(min_length=1, max_length=100),
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateTaskDeleteResponse:
    return TemplateTaskCommandService(db).delete_task(
        actor,
        version_id,
        task_id,
        revision_token=revision_token,
    )

@router.post(
    "/versions/{version_id}/dependencies",
    response_model=TemplateDependencyMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_template_dependency(
    version_id: uuid.UUID,
    payload: TemplateDependencyCreateRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateDependencyMutationResponse:
    return TemplateDependencyCommandService(db).create_dependency(actor, version_id, payload)


@router.patch(
    "/versions/{version_id}/dependencies/{dependency_id}",
    response_model=TemplateDependencyMutationResponse,
)
def update_template_dependency(
    version_id: uuid.UUID,
    dependency_id: uuid.UUID,
    payload: TemplateDependencyUpdateRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateDependencyMutationResponse:
    return TemplateDependencyCommandService(db).update_dependency(
        actor, version_id, dependency_id, payload
    )


@router.delete(
    "/versions/{version_id}/dependencies/{dependency_id}",
    response_model=TemplateDependencyDeleteResponse,
)
def delete_template_dependency(
    version_id: uuid.UUID,
    dependency_id: uuid.UUID,
    revision_token: str = Query(min_length=1, max_length=100),
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateDependencyDeleteResponse:
    return TemplateDependencyCommandService(db).delete_dependency(
        actor, version_id, dependency_id, revision_token=revision_token
    )


@router.post(
    "/versions/{version_id}/gates",
    response_model=TemplateGateMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_template_gate(
    version_id: uuid.UUID,
    payload: TemplateGateCreateRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateGateMutationResponse:
    return TemplateGateCommandService(db).create_gate(actor, version_id, payload)


@router.patch(
    "/versions/{version_id}/gates/{gate_id}",
    response_model=TemplateGateMutationResponse,
)
def update_template_gate(
    version_id: uuid.UUID,
    gate_id: uuid.UUID,
    payload: TemplateGateUpdateRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateGateMutationResponse:
    return TemplateGateCommandService(db).update_gate(actor, version_id, gate_id, payload)


@router.put(
    "/versions/{version_id}/gates/{gate_id}/mappings",
    response_model=TemplateGateMutationResponse,
)
def configure_template_gate_mappings(
    version_id: uuid.UUID,
    gate_id: uuid.UUID,
    payload: TemplateGateMappingRequest,
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateGateMutationResponse:
    return TemplateGateCommandService(db).configure_mappings(
        actor, version_id, gate_id, payload
    )


@router.delete(
    "/versions/{version_id}/gates/{gate_id}",
    response_model=TemplateGateDeleteResponse,
)
def delete_template_gate(
    version_id: uuid.UUID,
    gate_id: uuid.UUID,
    revision_token: str = Query(min_length=1, max_length=100),
    actor: User = Depends(require_template_mutator),
    db: Session = Depends(get_db),
) -> TemplateGateDeleteResponse:
    return TemplateGateCommandService(db).delete_gate(
        actor, version_id, gate_id, revision_token=revision_token
    )


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
    version = TemplateQueryService(db).get_version(actor, version_id)
    return TemplateVersionResponse.model_validate(
        {**version.to_dict(), "revision_token": concurrency_token(version)}
    )


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
