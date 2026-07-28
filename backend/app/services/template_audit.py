"""Reusable audit-event writer and stable Phase 2 template action names."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.project_models import V2AuditEvent


class TemplateAuditAction:
    TEMPLATE_CREATED = "template_created"
    TEMPLATE_VERSION_CLONED = "template_version_cloned"
    TEMPLATE_TASK_CREATED = "template_task_created"
    TEMPLATE_TASK_UPDATED = "template_task_updated"
    TEMPLATE_TASK_DELETED = "template_task_deleted"
    TEMPLATE_TASKS_REORDERED = "template_tasks_reordered"
    TEMPLATE_DEPENDENCY_CREATED = "template_dependency_created"
    TEMPLATE_DEPENDENCY_UPDATED = "template_dependency_updated"
    TEMPLATE_DEPENDENCY_DELETED = "template_dependency_deleted"
    TEMPLATE_GATE_CREATED = "template_gate_created"
    TEMPLATE_GATE_UPDATED = "template_gate_updated"
    TEMPLATE_GATE_DELETED = "template_gate_deleted"
    TEMPLATE_GATE_MAPPING_CHANGED = "template_gate_mapping_changed"
    TEMPLATE_DRAFT_VALIDATED = "template_draft_validated"
    TEMPLATE_VERSION_PUBLISHED = "template_version_published"
    TEMPLATE_VERSION_ARCHIVED = "template_version_archived"
    TEMPLATE_DRAFT_DELETED = "template_draft_deleted"

    ALL = frozenset(
        {
            TEMPLATE_CREATED,
            TEMPLATE_VERSION_CLONED,
            TEMPLATE_TASK_CREATED,
            TEMPLATE_TASK_UPDATED,
            TEMPLATE_TASK_DELETED,
            TEMPLATE_TASKS_REORDERED,
            TEMPLATE_DEPENDENCY_CREATED,
            TEMPLATE_DEPENDENCY_UPDATED,
            TEMPLATE_DEPENDENCY_DELETED,
            TEMPLATE_GATE_CREATED,
            TEMPLATE_GATE_UPDATED,
            TEMPLATE_GATE_DELETED,
            TEMPLATE_GATE_MAPPING_CHANGED,
            TEMPLATE_DRAFT_VALIDATED,
            TEMPLATE_VERSION_PUBLISHED,
            TEMPLATE_VERSION_ARCHIVED,
            TEMPLATE_DRAFT_DELETED,
        }
    )


@dataclass(frozen=True)
class TemplateAuditWrite:
    action: str
    entity_type: str
    entity_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    reason: str
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None
    correlation_id: uuid.UUID | None = None
    source: str = "portal"


def write_template_audit_event(db: Session, write: TemplateAuditWrite) -> V2AuditEvent:
    """Stage exactly one template audit event in the caller's transaction."""
    if write.action not in TemplateAuditAction.ALL:
        raise ValueError(f"Unsupported template audit action: {write.action}")
    reason = write.reason.strip()
    if not reason:
        raise ValueError("Audit reason is required.")

    event = V2AuditEvent(
        actor_user_id=write.actor_user_id,
        action=write.action,
        entity_type=write.entity_type,
        entity_id=write.entity_id,
        correlation_id=write.correlation_id or uuid.uuid4(),
        source=write.source,
        before_json=write.before_json,
        after_json=write.after_json,
        reason=reason,
    )
    db.add(event)
    return event
