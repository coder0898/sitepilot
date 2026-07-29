"""Transactional draft-only external-gate commands for V2 template versions."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.template_gate_repository import TemplateGateRepository
from app.repositories.template_mutation_repository import TemplateMutationRepository
from app.services.template_audit import TemplateAuditAction, TemplateAuditWrite, write_template_audit_event
from app.services.template_mutation_access import require_template_mutation_access
from app.services.transaction_boundary import command_transaction
from app.template_gate_mutation_schemas import (
    TemplateGateCreateRequest,
    TemplateGateDeleteResponse,
    TemplateGateMappingRequest,
    TemplateGateMutationItem,
    TemplateGateMutationResponse,
    TemplateGateUpdateRequest,
)
from app.template_models import V2TemplateExternalGate

GATE_FIELDS = (
    "code",
    "approval_name",
    "description",
    "external_party",
    "required_by_type",
    "required_by_value",
    "impact",
    "mapping_classification",
    "broad_mapping_text",
    "requires_configuration",
    "sequence_no",
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Template external gate not found.")


def _invalid(message: str, **details: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "invalid_template_gate", "message": message, **details},
    )


def _conflict(code: str, message: str, **details: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, **details},
    )


def _mapping_values(classification: str, broad_text: str | None) -> dict[str, Any]:
    if classification == "exact":
        return {
            "mapping_classification": "exact",
            "broad_mapping_text": None,
            "requires_configuration": False,
        }
    if classification == "broad_text":
        return {
            "mapping_classification": "broad_text",
            "broad_mapping_text": broad_text,
            "requires_configuration": True,
        }
    return {
        "mapping_classification": "unmapped",
        "broad_mapping_text": None,
        "requires_configuration": True,
    }


def _snapshot(gate: V2TemplateExternalGate, task_ids: list[uuid.UUID]) -> dict[str, Any]:
    return {
        "gate_id": str(gate.id),
        "template_version_id": str(gate.template_version_id),
        **{field: getattr(gate, field) for field in GATE_FIELDS},
        "task_ids": [str(task_id) for task_id in task_ids],
    }


def _mutation_item(
    gate: V2TemplateExternalGate, task_ids: list[uuid.UUID]
) -> TemplateGateMutationItem:
    return TemplateGateMutationItem(
        id=gate.id,
        template_version_id=gate.template_version_id,
        code=gate.code,
        approval_name=gate.approval_name,
        description=gate.description,
        external_party=gate.external_party,
        required_by_type=gate.required_by_type,
        required_by_value=gate.required_by_value,
        impact=gate.impact,
        mapping_classification=gate.mapping_classification,
        broad_mapping_text=gate.broad_mapping_text,
        requires_configuration=gate.requires_configuration,
        sequence_no=gate.sequence_no,
        task_ids=task_ids,
    )


class TemplateGateCommandService:
    def __init__(self, db: Session):
        self.db = db
        self.versions = TemplateMutationRepository(db)
        self.gates = TemplateGateRepository(db)

    def _require_tasks_in_version(
        self, version_id: uuid.UUID, task_ids: list[uuid.UUID]
    ) -> None:
        if len(set(task_ids)) != len(task_ids):
            raise _invalid("Exact mapping task IDs must be unique.")
        tasks = self.gates.get_tasks(task_ids)
        found = {task.id: task for task in tasks}
        for task_id in task_ids:
            task = found.get(task_id)
            if task is None:
                raise _invalid("A mapped task does not exist.", task_id=str(task_id))
            if task.template_version_id != version_id:
                raise _invalid(
                    "A mapped task belongs to another template version.",
                    task_id=str(task_id),
                    version_id=str(version_id),
                )

    def create_gate(
        self,
        actor: User,
        version_id: uuid.UUID,
        payload: TemplateGateCreateRequest,
    ) -> TemplateGateMutationResponse:
        require_template_mutation_access(actor)
        try:
            with command_transaction(self.db):
                version = self.versions.get_version_for_mutation(
                    version_id, expected_token=payload.revision_token
                )
                task_ids = list(payload.task_ids)
                if payload.mapping_classification == "exact":
                    self._require_tasks_in_version(version.id, task_ids)
                values = payload.model_dump(
                    exclude={
                        "revision_token",
                        "task_ids",
                        "mapping_classification",
                        "broad_mapping_text",
                    }
                )
                values.update(
                    _mapping_values(payload.mapping_classification, payload.broad_mapping_text)
                )
                gate = self.gates.create_gate(version.id, values)
                if payload.mapping_classification == "exact":
                    self.gates.replace_mappings(gate.id, task_ids)
                revision_token = self.versions.touch(version)
                write_template_audit_event(
                    self.db,
                    TemplateAuditWrite(
                        action=TemplateAuditAction.TEMPLATE_GATE_CREATED,
                        entity_type="template_external_gate",
                        entity_id=gate.id,
                        actor_user_id=actor.id,
                        reason="Created draft template external gate.",
                        after_json=_snapshot(gate, sorted(task_ids)),
                    ),
                )
                result = TemplateGateMutationResponse(
                    gate=_mutation_item(gate, sorted(task_ids)),
                    revision_token=revision_token,
                )
            return result
        except HTTPException:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "template_gate_conflict",
                "The gate could not be created because its code already exists or the draft changed concurrently.",
                version_id=str(version_id),
            ) from exc

    def update_gate(
        self,
        actor: User,
        version_id: uuid.UUID,
        gate_id: uuid.UUID,
        payload: TemplateGateUpdateRequest,
    ) -> TemplateGateMutationResponse:
        require_template_mutation_access(actor)
        try:
            with command_transaction(self.db):
                version = self.versions.get_version_for_mutation(
                    version_id, expected_token=payload.revision_token
                )
                gate = self.gates.get_gate(version.id, gate_id)
                if gate is None:
                    raise _not_found()
                task_ids = self.gates.list_mapping_task_ids(gate.id)
                before = _snapshot(gate, task_ids)
                changes = payload.model_dump(exclude={"revision_token"}, exclude_unset=True)
                current = {field: getattr(gate, field) for field in changes}
                if changes == current:
                    raise _invalid("Gate update does not contain an effective change.", gate_id=str(gate.id))
                self.gates.update_gate(gate, changes)
                revision_token = self.versions.touch(version)
                write_template_audit_event(
                    self.db,
                    TemplateAuditWrite(
                        action=TemplateAuditAction.TEMPLATE_GATE_UPDATED,
                        entity_type="template_external_gate",
                        entity_id=gate.id,
                        actor_user_id=actor.id,
                        reason="Updated draft template external gate.",
                        before_json=before,
                        after_json=_snapshot(gate, task_ids),
                    ),
                )
                result = TemplateGateMutationResponse(
                    gate=_mutation_item(gate, task_ids), revision_token=revision_token
                )
            return result
        except HTTPException:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "template_gate_conflict",
                "The gate could not be updated because its code already exists or the draft changed concurrently.",
                version_id=str(version_id),
            ) from exc

    def configure_mappings(
        self,
        actor: User,
        version_id: uuid.UUID,
        gate_id: uuid.UUID,
        payload: TemplateGateMappingRequest,
    ) -> TemplateGateMutationResponse:
        require_template_mutation_access(actor)
        with command_transaction(self.db):
            version = self.versions.get_version_for_mutation(
                version_id, expected_token=payload.revision_token
            )
            gate = self.gates.get_gate(version.id, gate_id)
            if gate is None:
                raise _not_found()
            task_ids = list(payload.task_ids)
            if payload.mapping_classification == "exact":
                self._require_tasks_in_version(version.id, task_ids)
            before_ids = self.gates.list_mapping_task_ids(gate.id)
            before = _snapshot(gate, before_ids)
            new_mapping = _mapping_values(
                payload.mapping_classification, payload.broad_mapping_text
            )
            target_ids = sorted(task_ids) if payload.mapping_classification == "exact" else []
            if (
                gate.mapping_classification == new_mapping["mapping_classification"]
                and gate.broad_mapping_text == new_mapping["broad_mapping_text"]
                and gate.requires_configuration == new_mapping["requires_configuration"]
                and sorted(before_ids) == target_ids
            ):
                raise _invalid(
                    "Mapping update does not contain an effective change.", gate_id=str(gate.id)
                )
            self.gates.update_gate(gate, new_mapping)
            # Exact rows are replaced or removed only within this transaction.
            self.gates.replace_mappings(gate.id, target_ids)
            revision_token = self.versions.touch(version)
            write_template_audit_event(
                self.db,
                TemplateAuditWrite(
                    action=TemplateAuditAction.TEMPLATE_GATE_MAPPING_CHANGED,
                    entity_type="template_external_gate",
                    entity_id=gate.id,
                    actor_user_id=actor.id,
                    reason="Changed draft template external-gate mapping.",
                    before_json=before,
                    after_json=_snapshot(gate, target_ids),
                ),
            )
            result = TemplateGateMutationResponse(
                gate=_mutation_item(gate, target_ids), revision_token=revision_token
            )
        return result

    def delete_gate(
        self,
        actor: User,
        version_id: uuid.UUID,
        gate_id: uuid.UUID,
        *,
        revision_token: str,
    ) -> TemplateGateDeleteResponse:
        require_template_mutation_access(actor)
        with command_transaction(self.db):
            version = self.versions.get_version_for_mutation(
                version_id, expected_token=revision_token
            )
            gate = self.gates.get_gate(version.id, gate_id)
            if gate is None:
                raise _not_found()
            task_ids = self.gates.list_mapping_task_ids(gate.id)
            before = _snapshot(gate, task_ids)
            self.gates.delete_gate(gate)
            new_token = self.versions.touch(version)
            write_template_audit_event(
                self.db,
                TemplateAuditWrite(
                    action=TemplateAuditAction.TEMPLATE_GATE_DELETED,
                    entity_type="template_external_gate",
                    entity_id=gate_id,
                    actor_user_id=actor.id,
                    reason="Deleted draft template external gate.",
                    before_json=before,
                ),
            )
            result = TemplateGateDeleteResponse(gate_id=gate_id, revision_token=new_token)
        return result
