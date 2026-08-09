"""Phase 3 U1: the single read-side aggregation service every visibility
surface (U2 dashboard, U3 reports, U4 admin rollup) calls through - see the
plan's Key Technical Decisions: "no parallel aggregation logic exists
elsewhere in the codebase."

Compute-on-request, not cached/materialized - Release 1's expected scale is
one project's worth of tasks (a 45-day project), not millions of rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.execution_models import (
    TASK_LIFECYCLE_STATUSES,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDelayEvent,
    TaskProgressUpdate,
)
from app.models import User
from app.project_models import V2Project
from app.routes.projects_v2 import get_project
from app.schemas.project_visibility import (
    ApprovalGateAtRiskOut,
    NoUpdateTaskOut,
    OverdueTaskOut,
    ProjectVisibilitySummary,
    ReassignmentRequiredOut,
    TaskRefOut,
)
from app.services.project_role_change import ProjectRoleChangeService

# Approval gates whose due date falls within this window (or has already
# passed) count as "at risk" per R2's "approaching or past their due date
# without a decision" - the plan leaves the exact window as an
# implementation-time choice, not a design decision worth locking down.
APPROVAL_GATE_RISK_WINDOW_HOURS = 48

PLANNED_STATUSES = ("planned", "ready")
ACTIVE_STATUSES = ("in_progress", "submitted", "verified", "approval_pending", "rejected")
TERMINAL_STATUSES = ("completed", "cancelled")


def _aware(value: datetime) -> datetime:
    """Postgres `timestamptz` columns always round-trip as timezone-aware
    via psycopg, but SQLite (used by this test suite's harness) silently
    drops tzinfo on read - treat a naive value as UTC rather than let a
    naive/aware subtraction raise `TypeError` at request time."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _task_ref(task: Task) -> TaskRefOut:
    return TaskRefOut(
        id=task.id, original_code=task.original_code, title=task.title, lifecycle_status=task.lifecycle_status,
    )


class ProjectVisibilityService:
    def __init__(self, db: Session):
        self.db = db

    def summarize(self, project_id: uuid.UUID, actor: User) -> ProjectVisibilitySummary:
        project = get_project(self.db, project_id, actor)
        now = datetime.now(timezone.utc)

        tasks = list(
            self.db.scalars(select(Task).where(Task.project_id == project.id)).all()
        )

        status_counts = {status: 0 for status in TASK_LIFECYCLE_STATUSES}
        for task in tasks:
            status_counts[task.lifecycle_status] += 1

        planned_count = sum(status_counts[s] for s in PLANNED_STATUSES)
        active_count = sum(status_counts[s] for s in ACTIVE_STATUSES)
        completed_count = status_counts["completed"]
        cancelled_count = status_counts["cancelled"]

        blocked_tasks = self._blocked_tasks(project.id, tasks)
        delayed_tasks = self._delayed_tasks(project.id, tasks)
        overdue_tasks = self._overdue_tasks(tasks, now)
        no_update_tasks = self._no_update_tasks(project.id, tasks, now)

        pending_verifications = [t for t in tasks if t.lifecycle_status == "submitted"]
        pending_approvals = [t for t in tasks if t.lifecycle_status == "approval_pending"]
        approval_gates_at_risk = self._approval_gates_at_risk(tasks, now)

        reassignment = ProjectRoleChangeService(self.db).reassignment_required(project.id, actor)

        return ProjectVisibilitySummary(
            project_id=project.id,
            generated_at=now,
            status_counts=status_counts,
            planned_count=planned_count,
            active_count=active_count,
            completed_count=completed_count,
            cancelled_count=cancelled_count,
            total_count=len(tasks),
            blocked_tasks=[_task_ref(t) for t in blocked_tasks],
            delayed_tasks=[_task_ref(t) for t in delayed_tasks],
            overdue_tasks=overdue_tasks,
            no_update_tasks=no_update_tasks,
            pending_verifications=[_task_ref(t) for t in pending_verifications],
            pending_approvals=[_task_ref(t) for t in pending_approvals],
            approval_gates_at_risk=approval_gates_at_risk,
            reassignment_required=[ReassignmentRequiredOut(**row) for row in reassignment],
        )

    # ---- derived conditions ---------------------------------------------

    def _blocked_tasks(self, project_id: uuid.UUID, tasks: list[Task]) -> list[Task]:
        blocked_task_ids = set(
            self.db.scalars(
                select(TaskBlocker.task_id).where(
                    TaskBlocker.project_id == project_id, TaskBlocker.resolved_at.is_(None),
                )
            ).all()
        )
        return [t for t in tasks if t.id in blocked_task_ids]

    def _delayed_tasks(self, project_id: uuid.UUID, tasks: list[Task]) -> list[Task]:
        delayed_task_ids = set(
            self.db.scalars(
                select(TaskDelayEvent.task_id).where(TaskDelayEvent.project_id == project_id)
            ).all()
        )
        return [t for t in tasks if t.id in delayed_task_ids]

    def _overdue_tasks(self, tasks: list[Task], now: datetime) -> list[OverdueTaskOut]:
        return [
            OverdueTaskOut(
                id=t.id, original_code=t.original_code, title=t.title, lifecycle_status=t.lifecycle_status,
                due_at=t.due_at,
            )
            for t in tasks
            if t.due_at is not None and _aware(t.due_at) < now and t.lifecycle_status not in TERMINAL_STATUSES
        ]

    def _no_update_tasks(self, project_id: uuid.UUID, tasks: list[Task], now: datetime) -> list[NoUpdateTaskOut]:
        candidates = [t for t in tasks if t.update_sla_hours is not None and t.lifecycle_status not in TERMINAL_STATUSES]
        if not candidates:
            return []

        candidate_ids = [t.id for t in candidates]
        last_update_rows = self.db.execute(
            select(TaskProgressUpdate.task_id, func.max(TaskProgressUpdate.created_at))
            .where(TaskProgressUpdate.project_id == project_id, TaskProgressUpdate.task_id.in_(candidate_ids))
            .group_by(TaskProgressUpdate.task_id)
        ).all()
        last_update_by_task = {task_id: last_at for task_id, last_at in last_update_rows}

        results = []
        for task in candidates:
            last_activity_at = _aware(last_update_by_task.get(task.id, task.created_at))
            hours_since = (now - last_activity_at).total_seconds() / 3600
            if hours_since > task.update_sla_hours:
                results.append(
                    NoUpdateTaskOut(
                        id=task.id, original_code=task.original_code, title=task.title,
                        lifecycle_status=task.lifecycle_status, last_activity_at=last_activity_at,
                        update_sla_hours=task.update_sla_hours,
                    )
                )
        return results

    def _approval_gates_at_risk(self, tasks: list[Task], now: datetime) -> list[ApprovalGateAtRiskOut]:
        gate_tasks = [
            t for t in tasks
            if t.task_kind == "approval_gate" and t.lifecycle_status not in TERMINAL_STATUSES and t.due_at is not None
        ]
        if not gate_tasks:
            return []

        gate_ids = [t.id for t in gate_tasks]
        decided_task_ids = set(
            self.db.scalars(
                select(TaskApprovalDecision.task_id).where(TaskApprovalDecision.task_id.in_(gate_ids))
            ).all()
        )
        risk_horizon = now + timedelta(hours=APPROVAL_GATE_RISK_WINDOW_HOURS)

        return [
            ApprovalGateAtRiskOut(
                id=t.id, original_code=t.original_code, title=t.title, lifecycle_status=t.lifecycle_status,
                due_at=t.due_at,
            )
            for t in gate_tasks
            if t.id not in decided_task_ids and _aware(t.due_at) <= risk_horizon
        ]
