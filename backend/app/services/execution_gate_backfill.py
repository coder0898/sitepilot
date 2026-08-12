"""45-day POC U3: give projects activated before execution gates existed
the gate rows and dropped-edge records they never got.

OPERATIONAL ENTRY POINT, NOT AN ENDPOINT — this module registers no router.

This is the part of U3 that silently matters. Without it, every already-
activated project shows each gate-blocked task as startable, because the
readiness advisor reads execution gate rows and finds none. A confidently
wrong startable list gets trusted and acted on, which is worse than no
readiness at all.

Re-runnable by construction rather than by care: both writes go through
the same `execution_gate_instantiation` helpers activation uses, and every
insert is conditional on the destination table's unique key. A run
interrupted halfway and started again produces no duplicates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import BaselineTask, ProjectBaseline, Task
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectTaskDependency
from app.services.execution_gate_instantiation import instantiate_execution_gates, snapshot_excluded_dependencies


@dataclass(frozen=True)
class GateBackfillResult:
    project_id: uuid.UUID
    gates_created: int
    excluded_edges_recorded: int
    skipped_reason: str | None = None


class ExecutionGateBackfillService:
    def __init__(self, db: Session):
        self.db = db

    def backfill_project(self, project: V2Project, actor_user_id: uuid.UUID | None = None) -> GateBackfillResult:
        baseline = self.db.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == project.id))
        if baseline is None:
            # Never activated, so there is no execution layer to populate.
            # Activation itself will do this when it happens.
            return GateBackfillResult(project.id, 0, 0, skipped_reason="project has no locked baseline")

        # The instantiation helpers key off planning-layer task ids, so
        # rebuild that mapping from the baseline chain the execution tasks
        # were created through. One join rather than a lookup per task -
        # a 99-task project would otherwise cost 99 queries here.
        task_by_project_task_id = {
            project_task_id: task
            for project_task_id, task in self.db.execute(
                select(BaselineTask.project_task_id, Task)
                .join(Task, Task.baseline_task_id == BaselineTask.id)
                .where(Task.project_id == project.id)
            ).all()
        }

        applicable_gates = list(self.db.scalars(
            select(V2ProjectExternalGate)
            .where(V2ProjectExternalGate.project_id == project.id,
                   V2ProjectExternalGate.applicability_state == "applicable")
            .order_by(V2ProjectExternalGate.template_sequence.asc(), V2ProjectExternalGate.original_code.asc())
        ).all())

        included_project_task_ids = list(task_by_project_task_id.keys())
        dropped_dependencies = list(self.db.scalars(
            select(V2ProjectTaskDependency)
            .where(
                V2ProjectTaskDependency.project_id == project.id,
                V2ProjectTaskDependency.successor_project_task_id.in_(included_project_task_ids),
                V2ProjectTaskDependency.predecessor_project_task_id.not_in(included_project_task_ids),
            )
            .order_by(V2ProjectTaskDependency.template_sequence.asc())
        ).all())

        gates_created = instantiate_execution_gates(
            self.db, project=project, baseline=baseline,
            applicable_gates=applicable_gates, task_by_project_task_id=task_by_project_task_id,
        )
        edges_recorded = snapshot_excluded_dependencies(
            self.db, project=project, baseline=baseline,
            dropped_dependencies=dropped_dependencies, task_by_project_task_id=task_by_project_task_id,
        )

        self.db.add(V2AuditEvent(
            actor_user_id=actor_user_id,
            action="PROJECT_EXECUTION_GATES_BACKFILLED",
            entity_type="project",
            entity_id=project.id,
            project_id=project.id,
            source="backfill",
            after_json={"gates_created": gates_created, "excluded_edges_recorded": edges_recorded},
            reason="U3 backfill: instantiate execution gates for a project activated before they existed.",
        ))
        self.db.commit()
        return GateBackfillResult(project.id, gates_created, edges_recorded)
