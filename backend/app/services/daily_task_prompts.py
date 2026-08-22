"""Plan Phase 6 (second half): daily task-prompt emission - the four
time-of-day WhatsApp prompts (readiness check, start check, midday check,
end-of-day check) the WhatsApp Operating Model doc describes for every
task, independent of `EscalationService`'s followup/escalation sweeps
(those fire on silence; these fire on a routine daily cadence).

`DailyTaskPromptsService` is an internal scheduled process, not a
user-facing portal route - the same framing `MessageDispatchService.
process_pending` documents for why it isn't actor-gated: there is no
"acting user" behind a scheduler tick, so there is nothing for an access
check to check. Every method here only reads task state and emits an
outbox event; none of them ever write `Task.lifecycle_status` or any other
lifecycle field.

Idempotency is deliberately PER CALENDAR DAY, not per exact timestamp: the
scheduler (`daily_task_prompts_scheduler.py`) may tick many times in one
day, and a task should get at most one of each prompt per day no matter how
often the tick fires. Each emit call's idempotency key is
`f"task:{task.id}:{event_type}:{now.date().isoformat()}"` -
`OutboxService.emit`'s own idempotency-key uniqueness check (see
`app.services.outbox`) then does the rest: a second call on the same
calendar day finds the key already taken and returns `None` (a no-op), with
zero extra tracking table needed.

The midday/EOD checks additionally gate on wall-clock hour (UTC - the only
clock this codebase reasons about; see `settings.daily_task_prompts_
midday_hour_utc`/`eod_hour_utc`) so the two can never both fire in the same
pass: "midday" only actually emits once `now.hour` reaches the midday hour
(and before the EOD hour), and "EOD" only once `now.hour` reaches the EOD
hour. Per-calendar-day idempotency above still applies on top of this, so a
later tick that lands in the same window on the same day is a no-op rather
than a duplicate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import Task
from app.services.outbox import OutboxService

logger = logging.getLogger(__name__)

NOT_YET_STARTED_STATUSES = ("planned", "ready")
IN_PROGRESS_STATUSES = ("in_progress",)


class DailyTaskPromptsService:
    def __init__(self, db: Session):
        self.db = db

    def _commit(self) -> None:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _emit_for_tasks(self, tasks: list[Task], event_type: str, now: datetime) -> list[Task]:
        """Shared emit loop: commits once per task (mirrors
        `EscalationService`'s own per-entity commit granularity), and only
        includes a task in the return value when `OutboxService.emit`
        actually wrote a new row - a `None` return means today's prompt for
        that task was already emitted by an earlier tick this same
        calendar day.

        A single task's failure (bad payload, a transient DB error) is
        logged and skipped rather than raised - letting the exception
        propagate would abort every remaining task in this call *and* every
        call still queued behind it in the same scheduler pass (see
        `daily_task_prompts_scheduler.run_daily_task_prompts_pass`), turning
        one bad row into a stalled channel for every task on that tick."""
        emitted: list[Task] = []
        for task in tasks:
            try:
                event = OutboxService(self.db).emit(
                    event_type=event_type,
                    aggregate_type="task",
                    aggregate_id=task.id,
                    payload={
                        "task_id": str(task.id),
                        "project_id": str(task.project_id),
                        "lifecycle_status": task.lifecycle_status,
                        "planned_start_date": task.planned_start_date.isoformat() if task.planned_start_date else None,
                    },
                    idempotency_key=f"task:{task.id}:{event_type}:{now.date().isoformat()}",
                )
                self._commit()
            except Exception:
                logger.exception(
                    "Failed to emit %s for task %s (project %s); skipping and continuing.",
                    event_type, task.id, task.project_id,
                )
                self.db.rollback()
                continue
            if event is not None:
                emitted.append(task)
        return emitted

    def emit_readiness_checks(self, now: datetime) -> list[Task]:
        """Tasks starting tomorrow that have not started yet - the doc's
        "day before start" readiness prompt. Emits `task.readiness_check`."""
        tomorrow = now.date() + timedelta(days=1)
        tasks = list(
            self.db.scalars(
                select(Task).where(
                    Task.planned_start_date == tomorrow,
                    Task.lifecycle_status.in_(NOT_YET_STARTED_STATUSES),
                )
            ).all()
        )
        return self._emit_for_tasks(tasks, "task.readiness_check", now)

    def emit_start_checks(self, now: datetime) -> list[Task]:
        """Tasks starting today that still have not started - the doc's
        "morning of start" prompt. Emits `task.start_check`."""
        today = now.date()
        tasks = list(
            self.db.scalars(
                select(Task).where(
                    Task.planned_start_date == today,
                    Task.lifecycle_status.in_(NOT_YET_STARTED_STATUSES),
                )
            ).all()
        )
        return self._emit_for_tasks(tasks, "task.start_check", now)

    def emit_midday_checks(self, now: datetime) -> list[Task]:
        """In-progress tasks - the doc's midday progress prompt. Emits
        `task.midday_check`.

        Only actually fires once `now.hour` reaches the configured midday
        hour and before the EOD hour - outside that window this is a no-op,
        so an hourly tick at, say, 2am UTC never sends a "midday" prompt."""
        if not (settings.daily_task_prompts_midday_hour_utc <= now.hour < settings.daily_task_prompts_eod_hour_utc):
            return []
        tasks = list(
            self.db.scalars(
                select(Task).where(Task.lifecycle_status.in_(IN_PROGRESS_STATUSES))
            ).all()
        )
        return self._emit_for_tasks(tasks, "task.midday_check", now)

    def emit_eod_checks(self, now: datetime) -> list[Task]:
        """In-progress tasks - the doc's end-of-day check. Emits
        `task.eod_check`.

        Only actually fires once `now.hour` reaches the configured EOD hour
        - strictly after the midday window, so the two prompts can never
        both fire in the same pass."""
        if now.hour < settings.daily_task_prompts_eod_hour_utc:
            return []
        tasks = list(
            self.db.scalars(
                select(Task).where(Task.lifecycle_status.in_(IN_PROGRESS_STATUSES))
            ).all()
        )
        return self._emit_for_tasks(tasks, "task.eod_check", now)
