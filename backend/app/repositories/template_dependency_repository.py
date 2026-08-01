"""Repository primitives for draft template dependency commands."""
from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.template_models import V2TemplateTask, V2TemplateTaskDependency


class TemplateDependencyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_task(self, task_id: uuid.UUID) -> V2TemplateTask | None:
        return self.db.get(V2TemplateTask, task_id)

    def get_dependency(
        self, version_id: uuid.UUID, dependency_id: uuid.UUID
    ) -> V2TemplateTaskDependency | None:
        return self.db.scalar(
            select(V2TemplateTaskDependency).where(
                V2TemplateTaskDependency.id == dependency_id,
                V2TemplateTaskDependency.template_version_id == version_id,
            )
        )

    def list_dependencies(self, version_id: uuid.UUID) -> list[V2TemplateTaskDependency]:
        return list(
            self.db.scalars(
                select(V2TemplateTaskDependency)
                .where(V2TemplateTaskDependency.template_version_id == version_id)
                .order_by(
                    V2TemplateTaskDependency.sequence_no,
                    V2TemplateTaskDependency.id,
                )
            )
        )

    def duplicate_exists(
        self,
        version_id: uuid.UUID,
        *,
        predecessor_task_id: uuid.UUID,
        successor_task_id: uuid.UUID,
        dependency_type: str,
        exclude_dependency_id: uuid.UUID | None = None,
    ) -> bool:
        conditions = [
            V2TemplateTaskDependency.template_version_id == version_id,
            V2TemplateTaskDependency.predecessor_task_id == predecessor_task_id,
            V2TemplateTaskDependency.successor_task_id == successor_task_id,
            V2TemplateTaskDependency.dependency_type == dependency_type,
        ]
        if exclude_dependency_id is not None:
            conditions.append(V2TemplateTaskDependency.id != exclude_dependency_id)
        return self.db.scalar(
            select(V2TemplateTaskDependency.id).where(and_(*conditions)).limit(1)
        ) is not None

    def create_dependency(self, version_id: uuid.UUID, values: dict) -> V2TemplateTaskDependency:
        dependency = V2TemplateTaskDependency(template_version_id=version_id, **values)
        self.db.add(dependency)
        self.db.flush()
        return dependency

    def update_dependency(
        self, dependency: V2TemplateTaskDependency, values: dict
    ) -> V2TemplateTaskDependency:
        for field, value in values.items():
            setattr(dependency, field, value)
        self.db.flush()
        return dependency

    def delete_dependency(self, dependency: V2TemplateTaskDependency) -> None:
        self.db.delete(dependency)
        self.db.flush()
