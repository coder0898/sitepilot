"""Transactional draft-only dependency commands for V2 template versions."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.template_dependency_repository import TemplateDependencyRepository
from app.repositories.template_mutation_repository import TemplateMutationRepository
from app.services.template_audit import (
    TemplateAuditAction,
    TemplateAuditWrite,
    write_template_audit_event,
)
from app.services.template_mutation_access import require_template_mutation_access
from app.services.transaction_boundary import command_transaction
from app.template_dependency_mutation_schemas import (
    TemplateDependencyCreateRequest,
    TemplateDependencyDeleteResponse,
    TemplateDependencyMutationItem,
    TemplateDependencyMutationResponse,
    TemplateDependencyUpdateRequest,
)
from app.template_models import V2TemplateTaskDependency

DEPENDENCY_FIELDS = (
    "predecessor_task_id",
    "successor_task_id",
    "dependency_type",
    "blocking",
    "rule_text",
    "sequence_no",
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Template dependency not found.")


def _invalid(message: str, **details: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "invalid_template_dependency", "message": message, **details},
    )


def _conflict(code: str, message: str, **details: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, **details},
    )


def _snapshot(item: V2TemplateTaskDependency) -> dict[str, Any]:
    return {field: getattr(item, field) for field in DEPENDENCY_FIELDS}


def _audit_snapshot(item: V2TemplateTaskDependency) -> dict[str, Any]:
    return {
        "dependency_id": str(item.id),
        "template_version_id": str(item.template_version_id),
        **{k: str(v) if isinstance(v, uuid.UUID) else v for k, v in _snapshot(item).items()},
    }


def _mutation_item(item: V2TemplateTaskDependency) -> TemplateDependencyMutationItem:
    return TemplateDependencyMutationItem(
        id=item.id,
        template_version_id=item.template_version_id,
        **_snapshot(item),
    )


class TemplateDependencyCommandService:
    def __init__(self, db: Session):
        self.db = db
        self.versions = TemplateMutationRepository(db)
        self.dependencies = TemplateDependencyRepository(db)

    def _require_tasks_in_version(
        self,
        version_id: uuid.UUID,
        predecessor_task_id: uuid.UUID,
        successor_task_id: uuid.UUID,
    ) -> None:
        if predecessor_task_id == successor_task_id:
            raise _invalid(
                "A task cannot depend on itself.",
                task_id=str(predecessor_task_id),
            )
        for label, task_id in (
            ("predecessor", predecessor_task_id),
            ("successor", successor_task_id),
        ):
            task = self.dependencies.get_task(task_id)
            if task is None:
                raise _invalid(
                    f"The {label} task does not exist.",
                    task_id=str(task_id),
                )
            if task.template_version_id != version_id:
                raise _invalid(
                    f"The {label} task belongs to another template version.",
                    task_id=str(task_id),
                    version_id=str(version_id),
                )

    def _require_unique(
        self,
        version_id: uuid.UUID,
        values: dict[str, Any],
        *,
        exclude_dependency_id: uuid.UUID | None = None,
    ) -> None:
        if self.dependencies.duplicate_exists(
            version_id,
            predecessor_task_id=values["predecessor_task_id"],
            successor_task_id=values["successor_task_id"],
            dependency_type=values["dependency_type"],
            exclude_dependency_id=exclude_dependency_id,
        ):
            raise _conflict(
                "template_dependency_exists",
                "The predecessor, successor and dependency type already exist.",
                version_id=str(version_id),
            )

    def _require_acyclic(
        self,
        version_id: uuid.UUID,
        candidate: dict[str, Any],
        *,
        replace_dependency_id: uuid.UUID | None = None,
    ) -> None:
        edges: list[tuple[uuid.UUID, uuid.UUID]] = []
        for dependency in self.dependencies.list_dependencies(version_id):
            if dependency.id == replace_dependency_id:
                continue
            edges.append((dependency.predecessor_task_id, dependency.successor_task_id))
        edges.append((candidate["predecessor_task_id"], candidate["successor_task_id"]))

        adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
        for predecessor, successor in edges:
            adjacency.setdefault(predecessor, []).append(successor)
            adjacency.setdefault(successor, [])

        visiting: set[uuid.UUID] = set()
        visited: set[uuid.UUID] = set()

        def visit(node: uuid.UUID) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for successor in adjacency.get(node, []):
                if visit(successor):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        if any(visit(node) for node in list(adjacency)):
            raise _conflict(
                "template_dependency_cycle",
                "The dependency would create a cycle in the draft graph.",
                version_id=str(version_id),
            )

    def create_dependency(
        self,
        actor: User,
        version_id: uuid.UUID,
        payload: TemplateDependencyCreateRequest,
    ) -> TemplateDependencyMutationResponse:
        require_template_mutation_access(actor)
        try:
            with command_transaction(self.db):
                version = self.versions.get_version_for_mutation(
                    version_id, expected_token=payload.revision_token
                )
                values = payload.model_dump(exclude={"revision_token"})
                self._require_tasks_in_version(
                    version.id,
                    values["predecessor_task_id"],
                    values["successor_task_id"],
                )
                self._require_unique(version.id, values)
                self._require_acyclic(version.id, values)
                dependency = self.dependencies.create_dependency(version.id, values)
                revision_token = self.versions.touch(version)
                write_template_audit_event(
                    self.db,
                    TemplateAuditWrite(
                        action=TemplateAuditAction.TEMPLATE_DEPENDENCY_CREATED,
                        entity_type="template_dependency",
                        entity_id=dependency.id,
                        actor_user_id=actor.id,
                        reason="Created draft template dependency.",
                        after_json=_audit_snapshot(dependency),
                    ),
                )
                result = TemplateDependencyMutationResponse(
                    dependency=_mutation_item(dependency),
                    revision_token=revision_token,
                )
            return result
        except HTTPException:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "template_dependency_conflict",
                "The dependency could not be created because the draft changed concurrently.",
                version_id=str(version_id),
            ) from exc

    def update_dependency(
        self,
        actor: User,
        version_id: uuid.UUID,
        dependency_id: uuid.UUID,
        payload: TemplateDependencyUpdateRequest,
    ) -> TemplateDependencyMutationResponse:
        require_template_mutation_access(actor)
        try:
            with command_transaction(self.db):
                version = self.versions.get_version_for_mutation(
                    version_id, expected_token=payload.revision_token
                )
                dependency = self.dependencies.get_dependency(version.id, dependency_id)
                if dependency is None:
                    raise _not_found()
                before = _audit_snapshot(dependency)
                changes = payload.model_dump(exclude={"revision_token"}, exclude_unset=True)
                candidate = {**_snapshot(dependency), **changes}
                if candidate == _snapshot(dependency):
                    raise _invalid(
                        "Dependency update does not contain an effective change.",
                        dependency_id=str(dependency.id),
                    )
                self._require_tasks_in_version(
                    version.id,
                    candidate["predecessor_task_id"],
                    candidate["successor_task_id"],
                )
                self._require_unique(
                    version.id,
                    candidate,
                    exclude_dependency_id=dependency.id,
                )
                self._require_acyclic(
                    version.id,
                    candidate,
                    replace_dependency_id=dependency.id,
                )
                self.dependencies.update_dependency(dependency, changes)
                revision_token = self.versions.touch(version)
                write_template_audit_event(
                    self.db,
                    TemplateAuditWrite(
                        action=TemplateAuditAction.TEMPLATE_DEPENDENCY_UPDATED,
                        entity_type="template_dependency",
                        entity_id=dependency.id,
                        actor_user_id=actor.id,
                        reason="Updated draft template dependency.",
                        before_json=before,
                        after_json=_audit_snapshot(dependency),
                    ),
                )
                result = TemplateDependencyMutationResponse(
                    dependency=_mutation_item(dependency),
                    revision_token=revision_token,
                )
            return result
        except HTTPException:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "template_dependency_conflict",
                "The dependency could not be updated because the draft changed concurrently.",
                version_id=str(version_id),
            ) from exc

    def delete_dependency(
        self,
        actor: User,
        version_id: uuid.UUID,
        dependency_id: uuid.UUID,
        *,
        revision_token: str,
    ) -> TemplateDependencyDeleteResponse:
        require_template_mutation_access(actor)
        with command_transaction(self.db):
            version = self.versions.get_version_for_mutation(
                version_id, expected_token=revision_token
            )
            dependency = self.dependencies.get_dependency(version.id, dependency_id)
            if dependency is None:
                raise _not_found()
            before = _audit_snapshot(dependency)
            self.dependencies.delete_dependency(dependency)
            new_token = self.versions.touch(version)
            write_template_audit_event(
                self.db,
                TemplateAuditWrite(
                    action=TemplateAuditAction.TEMPLATE_DEPENDENCY_DELETED,
                    entity_type="template_dependency",
                    entity_id=dependency_id,
                    actor_user_id=actor.id,
                    reason="Deleted draft template dependency.",
                    before_json=before,
                ),
            )
            result = TemplateDependencyDeleteResponse(
                dependency_id=dependency_id,
                revision_token=new_token,
            )
        return result
