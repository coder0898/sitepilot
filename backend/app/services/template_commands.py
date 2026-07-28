"""Transactional command service for creating and cloning V2 template drafts."""
from __future__ import annotations

import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.template_mutation_repository import TemplateMutationRepository
from app.services.template_audit import (
    TemplateAuditAction,
    TemplateAuditWrite,
    write_template_audit_event,
)
from app.services.template_mutation_access import (
    require_template_mutation_access,
    stable_template_version_not_found,
)
from app.services.transaction_boundary import command_transaction
from app.template_mutation_schemas import (
    TemplateCloneMutationResponse,
    TemplateCloneRequest,
    TemplateCreateRequest,
    TemplateDraftMutationResponse,
)


def normalize_template_code(value: str) -> str:
    """Return the canonical stored code used for uniqueness checks."""
    normalized = re.sub(r"\s+", "-", value.strip().upper())
    normalized = re.sub(r"-+", "-", normalized)
    return normalized


def _duplicate_code_conflict(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "template_code_exists",
            "message": f"A template with code {code} already exists.",
        },
    )


def _clone_conflict(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "template_clone_conflict", "message": message},
    )


class TemplateCommandService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = TemplateMutationRepository(db)

    def create_template(
        self,
        actor: User,
        payload: TemplateCreateRequest,
    ) -> TemplateDraftMutationResponse:
        require_template_mutation_access(actor)
        normalized_code = normalize_template_code(payload.code)
        if not normalized_code:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Template code is required.",
            )

        try:
            with command_transaction(self.db):
                if self.repository.find_template_by_normalized_code(normalized_code) is not None:
                    raise _duplicate_code_conflict(normalized_code)
                template = self.repository.create_template(
                    code=normalized_code,
                    name=payload.name.strip(),
                    description=payload.description,
                )
                version = self.repository.create_draft_version(
                    template_id=template.id,
                    version_no=1,
                    duration_days=payload.duration_days,
                    change_note=payload.change_note,
                    created_by=actor.id,
                )
                write_template_audit_event(
                    self.db,
                    TemplateAuditWrite(
                        action=TemplateAuditAction.TEMPLATE_CREATED,
                        entity_type="template",
                        entity_id=template.id,
                        actor_user_id=actor.id,
                        reason="Created template identity and initial draft version.",
                        after_json={
                            "template_code": template.code,
                            "template_name": template.name,
                            "version_id": str(version.id),
                            "version_no": version.version_no,
                            "status": version.status,
                            "duration_days": version.duration_days,
                        },
                    ),
                )
                result = TemplateDraftMutationResponse(
                    template_id=template.id,
                    template_code=template.code,
                    template_name=template.name,
                    version_id=version.id,
                    version_no=version.version_no,
                    status=version.status,
                    duration_days=version.duration_days,
                )
            return result
        except HTTPException:
            raise
        except IntegrityError as exc:
            raise _duplicate_code_conflict(normalized_code) from exc

    def clone_version(
        self,
        actor: User,
        source_version_id: uuid.UUID,
        payload: TemplateCloneRequest,
    ) -> TemplateCloneMutationResponse:
        require_template_mutation_access(actor)
        try:
            with command_transaction(self.db):
                source = self.repository.load_clone_source(source_version_id)
                if source is None:
                    # Archived versions intentionally share the same non-disclosing response.
                    raise stable_template_version_not_found()

                version_no = self.repository.next_version_number(source.template.id)
                target = self.repository.create_draft_version(
                    template_id=source.template.id,
                    version_no=version_no,
                    duration_days=source.version.duration_days,
                    change_note=payload.change_note
                    or f"Cloned from version {source.version.version_no}.",
                    created_by=actor.id,
                )
                task_map = self.repository.clone_tasks(
                    source.tasks,
                    target_version_id=target.id,
                )
                dependencies = self.repository.clone_dependencies(
                    source.dependencies,
                    target_version_id=target.id,
                    task_map=task_map,
                )
                gate_map = self.repository.clone_gates(
                    source.gates,
                    target_version_id=target.id,
                )
                links = self.repository.clone_exact_gate_links(
                    source.gate_links,
                    source_gates=source.gates,
                    gate_map=gate_map,
                    task_map=task_map,
                )

                write_template_audit_event(
                    self.db,
                    TemplateAuditWrite(
                        action=TemplateAuditAction.TEMPLATE_VERSION_CLONED,
                        entity_type="template_version",
                        entity_id=target.id,
                        actor_user_id=actor.id,
                        reason=f"Cloned template version {source.version.version_no} into draft version {target.version_no}.",
                        before_json={
                            "source_version_id": str(source.version.id),
                            "source_version_no": source.version.version_no,
                            "source_status": source.version.status,
                        },
                        after_json={
                            "template_id": str(source.template.id),
                            "version_id": str(target.id),
                            "version_no": target.version_no,
                            "status": target.status,
                            "task_count": len(task_map),
                            "dependency_count": len(dependencies),
                            "gate_count": len(gate_map),
                            "exact_mapping_count": len(links),
                        },
                    ),
                )
                result = TemplateCloneMutationResponse(
                    source_version_id=source.version.id,
                    template_id=source.template.id,
                    template_code=source.template.code,
                    template_name=source.template.name,
                    version_id=target.id,
                    version_no=target.version_no,
                    status=target.status,
                    duration_days=target.duration_days,
                    task_count=len(task_map),
                    dependency_count=len(dependencies),
                    gate_count=len(gate_map),
                    exact_mapping_count=len(links),
                )
            return result
        except HTTPException:
            raise
        except ValueError as exc:
            raise _clone_conflict(str(exc)) from exc
        except IntegrityError as exc:
            raise _clone_conflict(
                "The new draft version could not be created because the template changed concurrently. Retry the clone."
            ) from exc