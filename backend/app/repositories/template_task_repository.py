"""Persistence primitives for draft-only V2 template task commands."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.template_models import (
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
)


@dataclass(frozen=True)
class TaskDependencyReference:
    id: uuid.UUID
    relationship: str
    other_task_id: uuid.UUID


@dataclass(frozen=True)
class TaskGateReference:
    id: uuid.UUID
    gate_id: uuid.UUID
    gate_code: str


@dataclass(frozen=True)
class TaskBlockingReferences:
    dependencies: list[TaskDependencyReference]
    gate_mappings: list[TaskGateReference]

    @property
    def blocked(self) -> bool:
        return bool(self.dependencies or self.gate_mappings)


class TemplateTaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_task(
        self,
        version_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        lock: bool = True,
    ) -> V2TemplateTask | None:
        statement = select(V2TemplateTask).where(
            V2TemplateTask.id == task_id,
            V2TemplateTask.template_version_id == version_id,
        )
        if lock:
            statement = statement.with_for_update()
        return self.db.execute(statement).scalar_one_or_none()

    def list_tasks(
        self,
        version_id: uuid.UUID,
        *,
        lock: bool = True,
    ) -> list[V2TemplateTask]:
        statement = (
            select(V2TemplateTask)
            .where(V2TemplateTask.template_version_id == version_id)
            .order_by(V2TemplateTask.sequence_no, V2TemplateTask.code, V2TemplateTask.id)
        )
        if lock:
            statement = statement.with_for_update()
        return list(self.db.scalars(statement))

    def code_exists(
        self,
        version_id: uuid.UUID,
        code: str,
        *,
        exclude_task_id: uuid.UUID | None = None,
    ) -> bool:
        statement = select(V2TemplateTask.id).where(
            V2TemplateTask.template_version_id == version_id,
            func.upper(func.trim(V2TemplateTask.code)) == code,
        )
        if exclude_task_id is not None:
            statement = statement.where(V2TemplateTask.id != exclude_task_id)
        return self.db.scalar(statement.limit(1)) is not None

    def sequence_exists(
        self,
        version_id: uuid.UUID,
        sequence_no: int,
        *,
        exclude_task_id: uuid.UUID | None = None,
    ) -> bool:
        statement = select(V2TemplateTask.id).where(
            V2TemplateTask.template_version_id == version_id,
            V2TemplateTask.sequence_no == sequence_no,
        )
        if exclude_task_id is not None:
            statement = statement.where(V2TemplateTask.id != exclude_task_id)
        return self.db.scalar(statement.limit(1)) is not None

    def create_task(self, version_id: uuid.UUID, values: dict) -> V2TemplateTask:
        task = V2TemplateTask(template_version_id=version_id, **values)
        self.db.add(task)
        self.db.flush()
        return task

    def update_task(self, task: V2TemplateTask, values: dict) -> V2TemplateTask:
        for field, value in values.items():
            setattr(task, field, value)
        self.db.flush()
        return task

    def blocking_references(self, task: V2TemplateTask) -> TaskBlockingReferences:
        dependency_rows = list(
            self.db.scalars(
                select(V2TemplateTaskDependency)
                .where(
                    V2TemplateTaskDependency.template_version_id == task.template_version_id,
                    or_(
                        V2TemplateTaskDependency.predecessor_task_id == task.id,
                        V2TemplateTaskDependency.successor_task_id == task.id,
                    ),
                )
                .order_by(V2TemplateTaskDependency.sequence_no, V2TemplateTaskDependency.id)
            )
        )
        dependencies = [
            TaskDependencyReference(
                id=item.id,
                relationship=(
                    "predecessor"
                    if item.predecessor_task_id == task.id
                    else "successor"
                ),
                other_task_id=(
                    item.successor_task_id
                    if item.predecessor_task_id == task.id
                    else item.predecessor_task_id
                ),
            )
            for item in dependency_rows
        ]
        gate_rows = list(
            self.db.execute(
                select(V2TemplateExternalGateTask, V2TemplateExternalGate)
                .join(
                    V2TemplateExternalGate,
                    V2TemplateExternalGate.id == V2TemplateExternalGateTask.gate_id,
                )
                .where(
                    V2TemplateExternalGateTask.template_task_id == task.id,
                    V2TemplateExternalGate.template_version_id == task.template_version_id,
                )
                .order_by(V2TemplateExternalGate.sequence_no, V2TemplateExternalGate.code)
            )
        )
        gate_mappings = [
            TaskGateReference(
                id=link.id,
                gate_id=gate.id,
                gate_code=gate.code,
            )
            for link, gate in gate_rows
        ]
        return TaskBlockingReferences(dependencies=dependencies, gate_mappings=gate_mappings)

    def delete_task(self, task: V2TemplateTask) -> None:
        self.db.delete(task)
        self.db.flush()

    def reorder_complete(
        self,
        tasks: list[V2TemplateTask],
        sequence_by_id: dict[uuid.UUID, int],
    ) -> list[V2TemplateTask]:
        # Move every row to a collision-free positive range before assigning the
        # final complete order. This keeps the unique sequence constraint active.
        temporary_base = max((task.sequence_no for task in tasks), default=0) + len(tasks) + 1
        for offset, task in enumerate(tasks):
            task.sequence_no = temporary_base + offset
        self.db.flush()
        for task in tasks:
            task.sequence_no = sequence_by_id[task.id]
        self.db.flush()
        return sorted(tasks, key=lambda item: (item.sequence_no, item.code, item.id))