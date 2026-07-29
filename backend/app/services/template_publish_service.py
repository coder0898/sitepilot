"""Atomic publication of a fully valid draft template version."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.template_publish_repository import TemplatePublishRepository
from app.repositories.template_validation_repository import TemplateValidationAggregate, TemplateValidationRepository
from app.services.template_audit import TemplateAuditAction, TemplateAuditWrite, write_template_audit_event
from app.services.template_draft_validator import validate_aggregate
from app.services.template_mutation_access import require_template_mutation_access
from app.services.transaction_boundary import command_transaction
from app.template_publish_schemas import TemplatePublishRequest, TemplatePublishResponse


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def normalized_content(aggregate: TemplateValidationAggregate) -> dict[str, Any]:
    """Build a stable semantic representation from persisted aggregate content."""
    task_by_id = {task.id: task.code.strip() for task in aggregate.tasks}
    gate_by_id = {gate.id: gate.code.strip() for gate in aggregate.gates}
    mappings_by_gate: dict[uuid.UUID, list[str]] = {}
    for mapping in aggregate.mappings:
        mappings_by_gate.setdefault(mapping.gate_id, []).append(task_by_id.get(mapping.template_task_id, str(mapping.template_task_id)))

    tasks = [
        {
            "code": _clean(t.code), "sequence_no": t.sequence_no, "title": _clean(t.title),
            "description": _clean(t.description), "schedule_classification": t.schedule_classification,
            "planned_start_day": t.planned_start_day, "planned_end_day": t.planned_end_day,
            "phase": _clean(t.phase), "category": _clean(t.category), "applicability": t.applicability,
            "task_class": _clean(t.task_class), "task_kind": _clean(t.task_kind),
            "evidence_required": t.evidence_required, "duration_days": t.duration_days,
        }
        for t in sorted(aggregate.tasks, key=lambda x: (x.sequence_no, x.code, str(x.id)))
    ]
    dependencies = [
        {
            "predecessor": task_by_id.get(d.predecessor_task_id, str(d.predecessor_task_id)),
            "successor": task_by_id.get(d.successor_task_id, str(d.successor_task_id)),
            "dependency_type": d.dependency_type, "blocking": d.blocking,
            "rule_text": _clean(d.rule_text), "sequence_no": d.sequence_no,
        }
        for d in sorted(aggregate.dependencies, key=lambda x: (x.sequence_no, str(x.id)))
    ]
    gates = [
        {
            "code": _clean(g.code), "approval_name": _clean(g.approval_name),
            "description": _clean(g.description), "external_party": _clean(g.external_party),
            "required_by_type": _clean(g.required_by_type), "required_by_value": _clean(g.required_by_value),
            "impact": _clean(g.impact), "mapping_classification": g.mapping_classification,
            "broad_mapping_text": _clean(g.broad_mapping_text),
            "requires_configuration": g.requires_configuration, "sequence_no": g.sequence_no,
            "exact_task_codes": sorted(mappings_by_gate.get(g.id, [])) if g.mapping_classification == "exact" else [],
        }
        for g in sorted(aggregate.gates, key=lambda x: (x.sequence_no, x.code, str(x.id)))
    ]
    return {
        "template": {"code": _clean(aggregate.template.code), "name": _clean(aggregate.template.name), "description": _clean(aggregate.template.description)},
        "version": {"version_no": aggregate.version.version_no, "duration_days": aggregate.version.duration_days},
        "tasks": tasks, "dependencies": dependencies, "external_gates": gates,
    }


def compute_persisted_content_hash(aggregate: TemplateValidationAggregate) -> str:
    encoded = json.dumps(normalized_content(aggregate), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TemplatePublishService:
    def __init__(self, db: Session):
        self.db = db
        self.publish_repo = TemplatePublishRepository(db)
        self.validation_repo = TemplateValidationRepository(db)

    def publish(self, actor: User, version_id: uuid.UUID, payload: TemplatePublishRequest) -> TemplatePublishResponse:
        require_template_mutation_access(actor)
        with command_transaction(self.db):
            lock = self.publish_repo.lock_for_publish(version_id, payload.revision_token)
            change_note = payload.change_note or lock.version.change_note
            if not change_note or not change_note.strip():
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "change_note_required", "message": "A change note is required before publication."})

            aggregate = self.validation_repo.load(version_id)
            if aggregate is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template version not found.")
            validation = validate_aggregate(aggregate)
            if validation.severity_counts.blocking:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "template_validation_failed",
                        "message": "The draft contains blocking validation errors and cannot be published.",
                        "validation": validation.model_dump(mode="json"),
                    },
                )

            content_hash = compute_persisted_content_hash(aggregate)
            before = {
                "status": lock.version.status,
                "is_current_published": lock.version.is_current_published,
                "previous_current_version_id": str(lock.previous_current.id) if lock.previous_current else None,
            }
            published_at = self.publish_repo.publish(
                lock,
                actor_id=actor.id,
                change_note=change_note.strip(),
                content_hash=content_hash,
            )
            write_template_audit_event(
                self.db,
                TemplateAuditWrite(
                    action=TemplateAuditAction.TEMPLATE_VERSION_PUBLISHED,
                    entity_type="template_version",
                    entity_id=lock.version.id,
                    actor_user_id=actor.id,
                    reason=change_note.strip(),
                    before_json=before,
                    after_json={
                        "status": "published", "is_current_published": True,
                        "published_at": published_at.isoformat(), "published_by": str(actor.id),
                        "content_hash": content_hash,
                        "previous_current_version_id": str(lock.previous_current.id) if lock.previous_current else None,
                    },
                ),
            )
            return TemplatePublishResponse(
                template_id=lock.template.id,
                version_id=lock.version.id,
                version_no=lock.version.version_no,
                status=lock.version.status,
                is_current_published=lock.version.is_current_published,
                published_at=published_at,
                published_by=actor.id,
                content_hash=content_hash,
                previous_current_version_id=lock.previous_current.id if lock.previous_current else None,
            )
