"""45-day POC U4: populate planned start and target finish on projects that
were activated before this unit existed.

OPERATIONAL ENTRY POINT, NOT AN ENDPOINT. This module registers no router
and is reached by an operator running it deliberately. That is a
requirement, not an oversight: `due_at` is the reference that computed
delay is measured against, and R28 says no execution role may influence
delay. A route that rewrote target finish dates would be exactly that
influence, wearing a different name.

READ THIS BEFORE RUNNING IT ON A LIVE PROJECT. `due_at` is the input to
the `overdue` tile in `ProjectVisibilityService`, and until this unit
nothing had ever written it - so that tile has been reading zero for every
project since it shipped. Backfilling a project that is, say, at day 30 of
45 will light up every unfinished task planned to end before day 30, all
at once. That is the correct number, not a bug, but it is a visible jump
and operators should be told it is coming rather than discovering it.

Every task carrying a planned day offset is populated, *including
completed ones*, because planned-versus-actual reporting (U11) needs a
target finish for tasks that have already finished. A task that already
has a `due_at` is left alone: something set it deliberately and this
backfill is not the authority on it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.project_models import V2AuditEvent, V2Project
from app.services.project_schedule_dates import planned_start_at, target_finish_at


@dataclass(frozen=True)
class BackfillResult:
    project_id: uuid.UUID
    tasks_examined: int
    target_finish_written: int
    planned_start_written: int
    skipped_existing_due_at: int
    skipped_no_offsets: int


class TargetDateBackfillService:
    """Idempotent. Re-running it changes nothing, because every write is
    guarded on the column already being null."""

    def __init__(self, db: Session):
        self.db = db

    def backfill_project(self, project: V2Project, actor_user_id: uuid.UUID | None = None) -> BackfillResult:
        tasks = list(self.db.scalars(select(Task).where(Task.project_id == project.id)).all())

        target_written = start_written = skipped_existing = skipped_no_offsets = 0
        for task in tasks:
            if task.planned_start_day is None and task.planned_end_day is None:
                # Pre-activation task: no offsets, so no dates. Correct, not missing.
                skipped_no_offsets += 1
                continue
            if task.due_at is not None:
                skipped_existing += 1
            elif task.planned_end_day is not None:
                task.due_at = target_finish_at(project.start_date, task.planned_end_day)
                target_written += 1
            if task.planned_start_at is None and task.planned_start_day is not None:
                task.planned_start_at = planned_start_at(project.start_date, task.planned_start_day)
                start_written += 1

        result = BackfillResult(
            project_id=project.id,
            tasks_examined=len(tasks),
            target_finish_written=target_written,
            planned_start_written=start_written,
            skipped_existing_due_at=skipped_existing,
            skipped_no_offsets=skipped_no_offsets,
        )

        self.db.add(V2AuditEvent(
            actor_user_id=actor_user_id,
            action="PROJECT_TARGET_DATES_BACKFILLED",
            entity_type="project",
            entity_id=project.id,
            project_id=project.id,
            source="backfill",
            after_json={
                "tasks_examined": result.tasks_examined,
                "target_finish_written": result.target_finish_written,
                "planned_start_written": result.planned_start_written,
                "skipped_existing_due_at": result.skipped_existing_due_at,
                "skipped_no_offsets": result.skipped_no_offsets,
            },
            reason="U4 backfill: derive planned start and target finish for a project activated before scheduling dates existed.",
        ))
        self.db.commit()
        return result
