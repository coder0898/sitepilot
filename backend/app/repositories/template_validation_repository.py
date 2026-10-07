"""Read-only aggregate loader for authoritative template validation."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.repositories.template_reference_repository import reference_files_by_owner
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)


@dataclass(frozen=True)
class TemplateValidationAggregate:
    template: V2Template
    version: V2TemplateVersion
    tasks: list[V2TemplateTask]
    dependencies: list[V2TemplateTaskDependency]
    gates: list[V2TemplateExternalGate]
    mappings: list[V2TemplateExternalGateTask]
    # Reference files keyed by template task id or gate id.
    reference_files: dict[uuid.UUID, list[dict]] = field(default_factory=dict)


class TemplateValidationRepository:
    def __init__(self, db: Session):
        self.db = db

    def load(self, version_id: uuid.UUID) -> TemplateValidationAggregate | None:
        version = self.db.scalar(select(V2TemplateVersion).where(V2TemplateVersion.id == version_id))
        if version is None:
            return None
        template = self.db.scalar(select(V2Template).where(V2Template.id == version.template_id))
        if template is None:
            return None
        tasks = list(self.db.scalars(
            select(V2TemplateTask)
            .where(V2TemplateTask.template_version_id == version.id)
            .order_by(V2TemplateTask.sequence_no, V2TemplateTask.code, V2TemplateTask.id)
        ))
        dependencies = list(self.db.scalars(
            select(V2TemplateTaskDependency)
            .where(V2TemplateTaskDependency.template_version_id == version.id)
            .order_by(V2TemplateTaskDependency.sequence_no, V2TemplateTaskDependency.id)
        ))
        gates = list(self.db.scalars(
            select(V2TemplateExternalGate)
            .where(V2TemplateExternalGate.template_version_id == version.id)
            .order_by(V2TemplateExternalGate.sequence_no, V2TemplateExternalGate.code, V2TemplateExternalGate.id)
        ))
        gate_ids = [gate.id for gate in gates]
        mappings = list(self.db.scalars(
            select(V2TemplateExternalGateTask)
            .where(V2TemplateExternalGateTask.gate_id.in_(gate_ids))
            .order_by(V2TemplateExternalGateTask.gate_id, V2TemplateExternalGateTask.template_task_id, V2TemplateExternalGateTask.id)
        )) if gate_ids else []
        reference_files = {
            **reference_files_by_owner(self.db, "task", [task.id for task in tasks]),
            **reference_files_by_owner(self.db, "gate", gate_ids),
        }
        return TemplateValidationAggregate(template, version, tasks, dependencies, gates, mappings, reference_files)
