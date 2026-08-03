"""U1: Baseline lock and execution-layer task/dependency instantiation.

`ProjectBaselineService.lock_and_instantiate` is the single service both
`POST /{project_id}/status` (draft->active branch) and
`POST /{project_id}/activate` must call, inside the same transaction as the
draft->active status flip, so no activation code path can produce an active
project without a locked baseline and instantiated tasks.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import BaselineTask, ProjectBaseline, Task, TaskDependency
from app.models import User
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectTask, V2ProjectTaskDependency


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProjectBaselineService:
    def __init__(self, db: Session):
        self.db = db

    def lock_and_instantiate(self, project: V2Project, actor: User) -> ProjectBaseline | None:
        """Lock the project's baseline and instantiate execution tasks.

        Must be called before the caller flips `project.status` to "active"
        and before that caller commits, so both live in one transaction.
        Idempotent: if a baseline already exists for this project, returns it
        unchanged and creates nothing new (re-activation guard).
        """
        existing = self.db.scalar(
            select(ProjectBaseline).where(ProjectBaseline.project_id == project.id)
        )
        if existing:
            return existing

        # "Included" here matches the codebase's existing authoritative flag
        # for baseline participation (V2ProjectTask.included), the same
        # field already used by the read-only /execution-tasks placeholder
        # endpoint's included/excluded counts. decision_state tracks review
        # provenance (pending_review vs. an explicit included/excluded
        # decision) but included=True is the actual "is part of the plan"
        # signal - mandatory tasks stay decision_state='pending_review'
        # forever (never becoming 'included') while still being included.
        included_tasks = list(self.db.scalars(
            select(V2ProjectTask)
            .where(V2ProjectTask.project_id == project.id, V2ProjectTask.included.is_(True))
            .order_by(V2ProjectTask.template_sequence.asc(), V2ProjectTask.original_code.asc())
        ).all())
        if not included_tasks:
            raise HTTPException(409, "Project activation requires at least one included task to lock a baseline.")

        included_dependencies = list(self.db.scalars(
            select(V2ProjectTaskDependency)
            .where(
                V2ProjectTaskDependency.project_id == project.id,
                V2ProjectTaskDependency.predecessor_project_task_id.in_([t.id for t in included_tasks]),
                V2ProjectTaskDependency.successor_project_task_id.in_([t.id for t in included_tasks]),
            )
            .order_by(V2ProjectTaskDependency.template_sequence.asc())
        ).all())

        gate_count = len(list(self.db.scalars(
            select(V2ProjectExternalGate.id)
            .where(V2ProjectExternalGate.project_id == project.id, V2ProjectExternalGate.applicability_state == "applicable")
        ).all()))

        baseline = ProjectBaseline(
            project_id=project.id,
            task_count=len(included_tasks),
            dependency_count=len(included_dependencies),
            gate_count=gate_count,
            locked_by=actor.id,
        )
        self.db.add(baseline)
        self.db.flush()

        baseline_task_by_project_task_id: dict[uuid.UUID, BaselineTask] = {}
        for task in included_tasks:
            snapshot_fields = {
                "original_code": task.original_code,
                "template_sequence": task.template_sequence,
                "title": task.title,
                "description": task.description,
                "schedule_classification": task.schedule_classification,
                "planned_start_day": task.planned_start_day,
                "planned_end_day": task.planned_end_day,
                "phase": task.phase,
                "category": task.category,
                "applicability": task.applicability,
                "task_class": task.task_class,
                "task_kind": task.task_kind,
                "evidence_required": task.evidence_required,
                "duration_days": task.duration_days,
            }
            baseline_task = BaselineTask(
                baseline_id=baseline.id,
                project_id=project.id,
                project_task_id=task.id,
                content_hash=_content_hash(snapshot_fields),
                **snapshot_fields,
            )
            self.db.add(baseline_task)
            baseline_task_by_project_task_id[task.id] = baseline_task
        self.db.flush()

        task_by_baseline_task_id: dict[uuid.UUID, Task] = {}
        for project_task_id, baseline_task in baseline_task_by_project_task_id.items():
            execution_task = Task(
                project_id=project.id,
                baseline_id=baseline.id,
                baseline_task_id=baseline_task.id,
                original_code=baseline_task.original_code,
                template_sequence=baseline_task.template_sequence,
                title=baseline_task.title,
                description=baseline_task.description,
                schedule_classification=baseline_task.schedule_classification,
                planned_start_day=baseline_task.planned_start_day,
                planned_end_day=baseline_task.planned_end_day,
                phase=baseline_task.phase,
                category=baseline_task.category,
                applicability=baseline_task.applicability,
                task_class=baseline_task.task_class,
                task_kind=baseline_task.task_kind,
                evidence_required=baseline_task.evidence_required,
                duration_days=baseline_task.duration_days,
                lifecycle_status="planned",
                created_from_baseline=True,
            )
            self.db.add(execution_task)
            task_by_baseline_task_id[baseline_task.id] = execution_task
        self.db.flush()

        task_by_project_task_id = {
            project_task_id: task_by_baseline_task_id[baseline_task.id]
            for project_task_id, baseline_task in baseline_task_by_project_task_id.items()
        }

        for dependency in included_dependencies:
            predecessor = task_by_project_task_id.get(dependency.predecessor_project_task_id)
            successor = task_by_project_task_id.get(dependency.successor_project_task_id)
            if not predecessor or not successor:
                continue
            self.db.add(TaskDependency(
                project_id=project.id,
                baseline_id=baseline.id,
                project_dependency_id=dependency.id,
                predecessor_task_id=predecessor.id,
                successor_task_id=successor.id,
                dependency_type=dependency.dependency_type,
                blocking=dependency.blocking,
                rule_text=dependency.rule_text,
                created_from_baseline=True,
            ))
        self.db.flush()

        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_BASELINE_LOCKED",
            entity_type="project_baseline",
            entity_id=baseline.id,
            project_id=project.id,
            source="portal",
            before_json={"task_count": 0, "dependency_count": 0},
            after_json={
                "task_count": baseline.task_count,
                "dependency_count": baseline.dependency_count,
                "gate_count": baseline.gate_count,
                "locked_at": datetime.now(timezone.utc).isoformat(),
            },
            reason="Project baseline locked at activation; execution tasks instantiated.",
        ))
        self.db.flush()

        return baseline
