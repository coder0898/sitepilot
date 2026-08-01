"""Repository primitives for draft template external-gate commands."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.template_models import V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask


class TemplateGateRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_gate(self, version_id: uuid.UUID, gate_id: uuid.UUID) -> V2TemplateExternalGate | None:
        return self.db.scalar(
            select(V2TemplateExternalGate).where(
                V2TemplateExternalGate.id == gate_id,
                V2TemplateExternalGate.template_version_id == version_id,
            )
        )

    def get_tasks(self, task_ids: list[uuid.UUID]) -> list[V2TemplateTask]:
        if not task_ids:
            return []
        return list(self.db.scalars(select(V2TemplateTask).where(V2TemplateTask.id.in_(task_ids))))

    def list_mapping_task_ids(self, gate_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            self.db.scalars(
                select(V2TemplateExternalGateTask.template_task_id)
                .where(V2TemplateExternalGateTask.gate_id == gate_id)
                .order_by(V2TemplateExternalGateTask.template_task_id)
            )
        )

    def create_gate(self, version_id: uuid.UUID, values: dict) -> V2TemplateExternalGate:
        gate = V2TemplateExternalGate(template_version_id=version_id, **values)
        self.db.add(gate)
        self.db.flush()
        return gate

    def update_gate(self, gate: V2TemplateExternalGate, values: dict) -> V2TemplateExternalGate:
        for field, value in values.items():
            setattr(gate, field, value)
        self.db.flush()
        return gate

    def replace_mappings(self, gate_id: uuid.UUID, task_ids: list[uuid.UUID]) -> None:
        self.db.execute(
            delete(V2TemplateExternalGateTask).where(V2TemplateExternalGateTask.gate_id == gate_id)
        )
        for task_id in task_ids:
            self.db.add(V2TemplateExternalGateTask(gate_id=gate_id, template_task_id=task_id))
        self.db.flush()

    def delete_gate(self, gate: V2TemplateExternalGate) -> None:
        self.db.execute(
            delete(V2TemplateExternalGateTask).where(V2TemplateExternalGateTask.gate_id == gate.id)
        )
        self.db.delete(gate)
        self.db.flush()
