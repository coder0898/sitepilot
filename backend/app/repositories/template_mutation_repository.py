"""Repository primitives for transactional Phase 2 template commands."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.template_mutation_access import (
    require_current_concurrency_token,
    require_draft_template_version,
    touch_version,
)
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)


@dataclass(frozen=True)
class TemplateCloneSource:
    template: V2Template
    version: V2TemplateVersion
    tasks: list[V2TemplateTask]
    dependencies: list[V2TemplateTaskDependency]
    gates: list[V2TemplateExternalGate]
    gate_links: list[V2TemplateExternalGateTask]


class TemplateMutationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_version_for_mutation(
        self,
        version_id: uuid.UUID,
        *,
        expected_token: str | None = None,
        lock: bool = True,
    ) -> V2TemplateVersion:
        statement = select(V2TemplateVersion).where(V2TemplateVersion.id == version_id)
        if lock:
            statement = statement.with_for_update()
        version = self.db.execute(statement).scalar_one_or_none()
        require_draft_template_version(version)
        if expected_token is not None:
            require_current_concurrency_token(version, expected_token)
        return version

    def find_template_by_normalized_code(self, normalized_code: str) -> V2Template | None:
        return self.db.scalar(
            select(V2Template).where(func.upper(func.trim(V2Template.code)) == normalized_code)
        )

    def create_template(self, *, code: str, name: str, description: str | None) -> V2Template:
        template = V2Template(code=code, name=name, description=description)
        self.db.add(template)
        self.db.flush()
        return template

    def create_draft_version(
        self,
        *,
        template_id: uuid.UUID,
        version_no: int,
        duration_days: int,
        change_note: str | None,
        created_by: uuid.UUID,
    ) -> V2TemplateVersion:
        version = V2TemplateVersion(
            template_id=template_id,
            version_no=version_no,
            status="draft",
            duration_days=duration_days,
            change_note=change_note,
            content_hash=None,
            is_current_published=False,
            created_by=created_by,
            published_by=None,
            published_at=None,
        )
        self.db.add(version)
        self.db.flush()
        return version

    def load_clone_source(self, version_id: uuid.UUID) -> TemplateCloneSource | None:
        version = self.db.scalar(
            select(V2TemplateVersion)
            .where(
                V2TemplateVersion.id == version_id,
                V2TemplateVersion.status.in_(("draft", "published")),
            )
            .with_for_update()
        )
        if version is None:
            return None
        template = self.db.scalar(select(V2Template).where(V2Template.id == version.template_id))
        if template is None:
            return None
        tasks = list(
            self.db.scalars(
                select(V2TemplateTask)
                .where(V2TemplateTask.template_version_id == version.id)
                .order_by(V2TemplateTask.sequence_no, V2TemplateTask.code, V2TemplateTask.id)
            )
        )
        dependencies = list(
            self.db.scalars(
                select(V2TemplateTaskDependency)
                .where(V2TemplateTaskDependency.template_version_id == version.id)
                .order_by(V2TemplateTaskDependency.sequence_no, V2TemplateTaskDependency.id)
            )
        )
        gates = list(
            self.db.scalars(
                select(V2TemplateExternalGate)
                .where(V2TemplateExternalGate.template_version_id == version.id)
                .order_by(V2TemplateExternalGate.sequence_no, V2TemplateExternalGate.code, V2TemplateExternalGate.id)
            )
        )
        gate_ids = [gate.id for gate in gates]
        gate_links = []
        if gate_ids:
            gate_links = list(
                self.db.scalars(
                    select(V2TemplateExternalGateTask)
                    .where(V2TemplateExternalGateTask.gate_id.in_(gate_ids))
                    .order_by(V2TemplateExternalGateTask.gate_id, V2TemplateExternalGateTask.id)
                )
            )
        return TemplateCloneSource(template, version, tasks, dependencies, gates, gate_links)

    def next_version_number(self, template_id: uuid.UUID) -> int:
        # Lock the stable identity so concurrent clones serialize per template.
        self.db.execute(
            select(V2Template.id).where(V2Template.id == template_id).with_for_update()
        ).scalar_one()
        current = self.db.scalar(
            select(func.max(V2TemplateVersion.version_no)).where(
                V2TemplateVersion.template_id == template_id
            )
        )
        return int(current or 0) + 1

    def clone_tasks(
        self,
        source_tasks: list[V2TemplateTask],
        *,
        target_version_id: uuid.UUID,
    ) -> dict[uuid.UUID, V2TemplateTask]:
        task_map: dict[uuid.UUID, V2TemplateTask] = {}
        for source in source_tasks:
            clone = V2TemplateTask(
                template_version_id=target_version_id,
                code=source.code,
                sequence_no=source.sequence_no,
                title=source.title,
                description=source.description,
                schedule_classification=source.schedule_classification,
                planned_start_day=source.planned_start_day,
                planned_end_day=source.planned_end_day,
                phase=source.phase,
                category=source.category,
                applicability=source.applicability,
                task_class=source.task_class,
                task_kind=source.task_kind,
                evidence_required=source.evidence_required,
                duration_days=source.duration_days,
            )
            self.db.add(clone)
            task_map[source.id] = clone
        self.db.flush()
        return task_map

    def clone_dependencies(
        self,
        source_dependencies: list[V2TemplateTaskDependency],
        *,
        target_version_id: uuid.UUID,
        task_map: dict[uuid.UUID, V2TemplateTask],
    ) -> list[V2TemplateTaskDependency]:
        clones: list[V2TemplateTaskDependency] = []
        for source in source_dependencies:
            predecessor = task_map.get(source.predecessor_task_id)
            successor = task_map.get(source.successor_task_id)
            if predecessor is None or successor is None:
                raise ValueError("Source dependency references a task outside the source version.")
            clone = V2TemplateTaskDependency(
                template_version_id=target_version_id,
                predecessor_task_id=predecessor.id,
                successor_task_id=successor.id,
                dependency_type=source.dependency_type,
                blocking=source.blocking,
                rule_text=source.rule_text,
                sequence_no=source.sequence_no,
            )
            self.db.add(clone)
            clones.append(clone)
        self.db.flush()
        return clones

    def clone_gates(
        self,
        source_gates: list[V2TemplateExternalGate],
        *,
        target_version_id: uuid.UUID,
    ) -> dict[uuid.UUID, V2TemplateExternalGate]:
        gate_map: dict[uuid.UUID, V2TemplateExternalGate] = {}
        for source in source_gates:
            clone = V2TemplateExternalGate(
                template_version_id=target_version_id,
                code=source.code,
                approval_name=source.approval_name,
                description=source.description,
                external_party=source.external_party,
                required_by_type=source.required_by_type,
                required_by_value=source.required_by_value,
                impact=source.impact,
                mapping_classification=source.mapping_classification,
                broad_mapping_text=source.broad_mapping_text,
                requires_configuration=source.requires_configuration,
                sequence_no=source.sequence_no,
            )
            self.db.add(clone)
            gate_map[source.id] = clone
        self.db.flush()
        return gate_map

    def clone_exact_gate_links(
        self,
        source_links: list[V2TemplateExternalGateTask],
        *,
        source_gates: list[V2TemplateExternalGate],
        gate_map: dict[uuid.UUID, V2TemplateExternalGate],
        task_map: dict[uuid.UUID, V2TemplateTask],
    ) -> list[V2TemplateExternalGateTask]:
        classification_by_gate = {gate.id: gate.mapping_classification for gate in source_gates}
        clones: list[V2TemplateExternalGateTask] = []
        for source in source_links:
            # Broad-text and unmapped gates deliberately remain configuration records only.
            if classification_by_gate.get(source.gate_id) != "exact":
                continue
            gate = gate_map.get(source.gate_id)
            task = task_map.get(source.template_task_id)
            if gate is None or task is None:
                raise ValueError("Source gate mapping references a record outside the source version.")
            clone = V2TemplateExternalGateTask(gate_id=gate.id, template_task_id=task.id)
            self.db.add(clone)
            clones.append(clone)
        self.db.flush()
        return clones

    def touch(self, version: V2TemplateVersion) -> str:
        token = touch_version(version)
        self.db.flush()
        return token