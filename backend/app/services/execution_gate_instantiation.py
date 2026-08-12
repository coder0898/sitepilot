"""45-day POC U3: copy applicable approvals and dropped edges into the
execution layer.

Shared by activation (`ProjectBaselineService.lock_and_instantiate`) and
the backfill for projects activated before this existed. One
implementation on purpose: if the two drifted, a backfilled project and a
freshly activated one would disagree about what blocks what, and the
difference would only surface as a wrong readiness answer months later.

Every insert is conditional on the table's own unique key rather than on
the caller having been careful. A partially-completed or concurrently
re-run backfill therefore cannot duplicate a row, and a duplicate gate row
is the failure that matters most - it is invisible in the interface and
would leave a twin still blocking after a PM approves the first one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ExecutionExcludedDependency, ExecutionGate, ExecutionGateTask, ProjectBaseline, Task
from app.project_models import (
    V2Project,
    V2ProjectExternalGate,
    V2ProjectExternalGateTask,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.services.project_schedule_dates import required_by_at


def instantiate_execution_gates(
    db: Session,
    *,
    project: V2Project,
    baseline: ProjectBaseline,
    applicable_gates: list[V2ProjectExternalGate],
    task_by_project_task_id: dict[uuid.UUID, Task],
) -> int:
    """Create one execution gate per applicable planning gate, with its
    task links resolved into execution task ids. Returns the number of
    gates created."""
    if not applicable_gates:
        return 0

    existing_codes = set(db.scalars(
        select(ExecutionGate.original_code).where(ExecutionGate.project_id == project.id)
    ).all())

    gate_links = list(db.scalars(
        select(V2ProjectExternalGateTask).where(
            V2ProjectExternalGateTask.project_gate_id.in_([g.id for g in applicable_gates])
        )
    ).all())
    links_by_gate: dict[uuid.UUID, list[V2ProjectExternalGateTask]] = {}
    for link in gate_links:
        links_by_gate.setdefault(link.project_gate_id, []).append(link)

    created = 0
    for gate in applicable_gates:
        if gate.original_code in existing_codes:
            continue
        execution_gate = ExecutionGate(
            project_id=project.id,
            baseline_id=baseline.id,
            project_gate_id=gate.id,
            original_code=gate.original_code,
            approval_name=gate.approval_name,
            external_party=gate.external_party,
            required_by_at=required_by_at(project.start_date, gate.required_by_type, gate.required_by_value),
            # A gate starts execution exactly where planning left it. U1
            # widened this column to the five lifecycle values; nothing has
            # yet been recorded against the gate, so it carries over.
            status=gate.status,
            blocking=gate.blocking,
            mapping_classification=gate.mapping_classification,
            accountable_pm_user_id=gate.accountable_pm_user_id,
        )
        db.add(execution_gate)
        db.flush()
        created += 1

        linked_task_ids: set[uuid.UUID] = set()
        for link in links_by_gate.get(gate.id, []):
            # A link whose task was excluded from scope resolves to
            # nothing and produces no row - the gate simply holds back
            # less work, which is correct.
            task = task_by_project_task_id.get(link.project_task_id)
            if task is None or task.id in linked_task_ids:
                continue
            linked_task_ids.add(task.id)
            db.add(ExecutionGateTask(execution_gate_id=execution_gate.id, task_id=task.id))
        db.flush()

    return created


def snapshot_excluded_dependencies(
    db: Session,
    *,
    project: V2Project,
    baseline: ProjectBaseline,
    dropped_dependencies: list[V2ProjectTaskDependency],
    task_by_project_task_id: dict[uuid.UUID, Task],
) -> int:
    """Record each edge whose predecessor was excluded from scope, so the
    successor can say what it is waiting on rather than looking unblocked.
    Returns the number of edges recorded."""
    if not dropped_dependencies:
        return 0

    predecessor_ids = [d.predecessor_project_task_id for d in dropped_dependencies]
    excluded_by_id = {
        row.id: row
        for row in db.scalars(select(V2ProjectTask).where(V2ProjectTask.id.in_(predecessor_ids))).all()
    }

    existing = set(db.execute(
        select(ExecutionExcludedDependency.successor_task_id,
               ExecutionExcludedDependency.excluded_predecessor_code,
               ExecutionExcludedDependency.dependency_type)
        .where(ExecutionExcludedDependency.project_id == project.id)
    ).all())

    created = 0
    for dependency in dropped_dependencies:
        successor = task_by_project_task_id.get(dependency.successor_project_task_id)
        excluded = excluded_by_id.get(dependency.predecessor_project_task_id)
        if successor is None or excluded is None:
            continue
        key = (successor.id, excluded.original_code, dependency.dependency_type)
        if key in existing:
            continue
        existing.add(key)
        db.add(ExecutionExcludedDependency(
            project_id=project.id,
            baseline_id=baseline.id,
            successor_task_id=successor.id,
            excluded_predecessor_code=excluded.original_code,
            excluded_predecessor_title=excluded.title,
            dependency_type=dependency.dependency_type,
            blocking=dependency.blocking,
            rule_text=dependency.rule_text,
        ))
        created += 1
    return created
