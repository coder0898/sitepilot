"""Plan Phase 6 (first half): escalation-tracking table + `EscalationService`
sweep logic. This dispatch is service-layer only - it deliberately does NOT
build the scheduler file(s) (`daily_task_prompts_scheduler.py`,
`gate_reminder_scheduler.py`) that will call these methods on a timer; every
sweep method here takes an explicit `now: datetime` so it is fully testable
by calling it directly, the same way any other service in this codebase is
unit tested.

Four sweep methods, one shared shape:

- `sweep_task_followups` / `sweep_approval_followups` find entities whose
  "expected update not received" condition is true right now and have no
  open (`resolved_at IS NULL`) `followup`-stage `EscalationTracking` row yet
  - track + emit for each, once.
- `sweep_task_escalations` / `sweep_approval_escalations` find entities with
  an open `followup`-stage row at least 6 hours old and RE-DERIVE the same
  live condition before escalating further - a stale/no-longer-true
  condition resolves that `followup` row (`resolved_at = now`) instead of
  escalating it, and a still-true condition escalates it to
  `admin_escalation` (once, guarded the same way). This "always re-derive
  from live data before escalating further" rule is why a stale tracking
  row with no explicit resolve is harmless (see `EscalationTracking`'s own
  docstring in `execution_models.py`).

Task-side staleness reuses `project_visibility.py`'s `_no_update_tasks`
query shape (no `TaskProgressUpdate` since an SLA-derived cutoff) rather
than reinventing it - see `_stale_tasks`/`_is_task_stale` below. Approval-
side staleness is "assigned but not yet submitted, at or past `due_at`"
(Phase 5's `ProjectExternalApproval.due_at`), the execution-layer's own
"expected update not received" condition for a gate.

A fifth method, `emit_gate_due_reminders`, lives here too (added in this
same phase's second half) rather than in the new
`app.services.daily_task_prompts` module: it operates on
`ProjectExternalApproval`, the same aggregate every other method in this
file already handles, so it belongs here for cohesion even though it is a
one-shot day-before reminder rather than a followup/escalation sweep - see
its own docstring for how it differs from the four sweeps above.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import (
    EscalationTracking,
    ProjectExternalApproval,
    Task,
    TaskProgressUpdate,
)
from app.services.outbox import OutboxService

# Mirrors `TERMINAL_STATUSES` in `app/services/project_visibility.py` (also
# mirrored locally by `task_delay_variance.py` for the same reason) rather
# than importing it - that module pulls in `app.routes.projects_v2` for
# `get_project`, a route-layer dependency this pure sweep-logic service has
# no reason to carry.
TERMINAL_STATUSES = ("completed", "cancelled")

ESCALATION_HOURS = 6
"""How long a `followup`-stage tracking row must have been open before an
escalation sweep will re-check and potentially advance it to
`admin_escalation`."""


def _aware(value: datetime) -> datetime:
    """Postgres `timestamptz` columns always round-trip as timezone-aware
    via psycopg, but SQLite (this test suite's harness) silently drops
    tzinfo on read - treat a naive value as UTC rather than let a
    naive/aware subtraction raise `TypeError`. Mirrors
    `project_visibility.py`'s own `_aware` helper."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class EscalationService:
    def __init__(self, db: Session):
        self.db = db

    # ---- shared tracking helpers -----------------------------------------

    def _has_open_tracking(self, entity_type: str, entity_id: uuid.UUID, stage: str) -> bool:
        return (
            self.db.scalar(
                select(EscalationTracking.id).where(
                    EscalationTracking.entity_type == entity_type,
                    EscalationTracking.entity_id == entity_id,
                    EscalationTracking.stage == stage,
                    EscalationTracking.resolved_at.is_(None),
                )
            )
            is not None
        )

    def _open_followups(self, entity_type: str, cutoff: datetime) -> list[EscalationTracking]:
        return list(
            self.db.scalars(
                select(EscalationTracking).where(
                    EscalationTracking.entity_type == entity_type,
                    EscalationTracking.stage == "followup",
                    EscalationTracking.resolved_at.is_(None),
                    EscalationTracking.triggered_at <= cutoff,
                )
            ).all()
        )

    def _commit(self) -> None:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _commit_new_tracking(self) -> bool:
        """Commits a newly-added open `EscalationTracking` row (plus
        whatever else is pending in the session, e.g. the paired outbox
        emit). `_has_open_tracking`'s pre-check only guards against
        re-tracking within a single sweep call - it cannot see a row
        another concurrent sweep is committing right now. Returns False if
        that race is lost: `uq_v2_escalation_tracking_entity_stage_open`
        raises `IntegrityError`, treated as a benign "someone else already
        opened this escalation" rather than a real failure."""
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return False
        except Exception:
            self.db.rollback()
            raise
        return True

    # ---- task staleness (reused from project_visibility.py's shape) -----

    def _stale_tasks(self, now: datetime) -> list[Task]:
        """Adapts `ProjectVisibilityService._no_update_tasks`'s staleness
        query - same "no `TaskProgressUpdate` since an SLA-derived cutoff"
        condition - to a sweep across every project's tasks at once, rather
        than one already-loaded project's task list."""
        candidates = list(
            self.db.scalars(
                select(Task).where(
                    Task.update_sla_hours.isnot(None),
                    Task.lifecycle_status.notin_(TERMINAL_STATUSES),
                )
            ).all()
        )
        if not candidates:
            return []

        candidate_ids = [t.id for t in candidates]
        last_update_rows = self.db.execute(
            select(TaskProgressUpdate.task_id, func.max(TaskProgressUpdate.created_at))
            .where(TaskProgressUpdate.task_id.in_(candidate_ids))
            .group_by(TaskProgressUpdate.task_id)
        ).all()
        last_update_by_task = {task_id: last_at for task_id, last_at in last_update_rows}

        stale = []
        for task in candidates:
            last_activity_at = _aware(last_update_by_task.get(task.id, task.created_at))
            hours_since = (now - last_activity_at).total_seconds() / 3600
            if hours_since > task.update_sla_hours:
                stale.append(task)
        return stale

    def _is_task_stale(self, task: Task, now: datetime) -> bool:
        """Single-task live re-check of the same condition `_stale_tasks`
        computes in batch - used by `sweep_task_escalations` to re-derive
        "is this still stalled" for one already-tracked task rather than
        trusting the tracking row alone."""
        if task.update_sla_hours is None or task.lifecycle_status in TERMINAL_STATUSES:
            return False
        last_activity_at = self.db.scalar(
            select(func.max(TaskProgressUpdate.created_at)).where(TaskProgressUpdate.task_id == task.id)
        )
        last_activity_at = _aware(last_activity_at) if last_activity_at is not None else _aware(task.created_at)
        hours_since = (now - last_activity_at).total_seconds() / 3600
        return hours_since > task.update_sla_hours

    # ---- approval staleness ------------------------------------------------

    def _is_approval_still_awaiting_followup(self, approval: ProjectExternalApproval) -> bool:
        """An approval's "expected update not received" condition: still
        `assigned` (not yet submitted, approved, rejected, or unassigned).
        Live re-check used by `sweep_approval_escalations`."""
        return approval.status == "assigned"

    # ---- sweeps -----------------------------------------------------------

    def sweep_task_followups(self, now: datetime) -> list[Task]:
        """Tracks + emits `task.eod_followup_required` for every stale task
        (per `_stale_tasks`) with no existing open `followup`-stage tracking
        row. Returns only the tasks newly escalated by this call - a task
        already tracked (from a prior sweep) is skipped, not re-returned."""
        escalated: list[Task] = []
        for task in self._stale_tasks(now):
            if self._has_open_tracking("task", task.id, "followup"):
                continue
            self.db.add(EscalationTracking(
                entity_type="task", entity_id=task.id, stage="followup", triggered_at=now,
            ))
            OutboxService(self.db).emit(
                event_type="task.eod_followup_required",
                aggregate_type="task",
                aggregate_id=task.id,
                payload={
                    "task_id": str(task.id),
                    "project_id": str(task.project_id),
                    "lifecycle_status": task.lifecycle_status,
                    "update_sla_hours": task.update_sla_hours,
                },
                idempotency_key=f"task:{task.id}:task.eod_followup_required:{now.isoformat()}",
            )
            if not self._commit_new_tracking():
                continue
            escalated.append(task)
        return escalated

    def sweep_task_escalations(self, now: datetime) -> list[Task]:
        """For every open `followup`-stage task tracking row at least
        `ESCALATION_HOURS` old, re-derives staleness live: still stale ->
        escalate to `admin_escalation` (once); no longer stale (an update
        landed) -> resolve the `followup` row and escalate no further."""
        escalated: list[Task] = []
        cutoff = now - timedelta(hours=ESCALATION_HOURS)
        for tracking in self._open_followups("task", cutoff):
            task = self.db.get(Task, tracking.entity_id)
            if task is None:
                continue
            if not self._is_task_stale(task, now):
                tracking.resolved_at = now
                self.db.add(tracking)
                self._commit()
                continue
            if self._has_open_tracking("task", task.id, "admin_escalation"):
                continue
            self.db.add(EscalationTracking(
                entity_type="task", entity_id=task.id, stage="admin_escalation", triggered_at=now,
            ))
            OutboxService(self.db).emit(
                event_type="task.escalated_to_admin",
                aggregate_type="task",
                aggregate_id=task.id,
                payload={
                    "task_id": str(task.id),
                    "project_id": str(task.project_id),
                    "lifecycle_status": task.lifecycle_status,
                    "update_sla_hours": task.update_sla_hours,
                },
                idempotency_key=f"task:{task.id}:task.escalated_to_admin:{now.isoformat()}",
            )
            if not self._commit_new_tracking():
                continue
            escalated.append(task)
        return escalated

    def sweep_approval_followups(self, now: datetime) -> list[ProjectExternalApproval]:
        """Tracks + emits `project_external_approval.followup_required` for
        every `assigned` (not yet submitted) approval whose `due_at` is at
        or before `now`'s date, with no existing open `followup`-stage
        tracking row."""
        escalated: list[ProjectExternalApproval] = []
        today = now.date()
        candidates = list(
            self.db.scalars(
                select(ProjectExternalApproval).where(
                    ProjectExternalApproval.status == "assigned",
                    ProjectExternalApproval.due_at.isnot(None),
                    ProjectExternalApproval.due_at <= today,
                )
            ).all()
        )
        for approval in candidates:
            if self._has_open_tracking("project_external_approval", approval.id, "followup"):
                continue
            self.db.add(EscalationTracking(
                entity_type="project_external_approval", entity_id=approval.id, stage="followup", triggered_at=now,
            ))
            OutboxService(self.db).emit(
                event_type="project_external_approval.followup_required",
                aggregate_type="project_external_approval",
                aggregate_id=approval.id,
                payload={
                    "approval_id": str(approval.id),
                    "project_id": str(approval.project_id),
                    "assigned_to_user_id": str(approval.assigned_to_user_id) if approval.assigned_to_user_id else None,
                    "due_at": approval.due_at.isoformat(),
                },
                idempotency_key=f"project_external_approval:{approval.id}:project_external_approval.followup_required:{now.isoformat()}",
            )
            if not self._commit_new_tracking():
                continue
            escalated.append(approval)
        return escalated

    def sweep_approval_escalations(self, now: datetime) -> list[ProjectExternalApproval]:
        """For every open `followup`-stage approval tracking row at least
        `ESCALATION_HOURS` old, re-derives live whether the approval is
        still `assigned`: still assigned -> escalate to `admin_escalation`
        (once); moved past `assigned` (submitted/approved/rejected/
        unassigned) -> resolve the `followup` row and escalate no
        further."""
        escalated: list[ProjectExternalApproval] = []
        cutoff = now - timedelta(hours=ESCALATION_HOURS)
        for tracking in self._open_followups("project_external_approval", cutoff):
            approval = self.db.get(ProjectExternalApproval, tracking.entity_id)
            if approval is None:
                continue
            if not self._is_approval_still_awaiting_followup(approval):
                tracking.resolved_at = now
                self.db.add(tracking)
                self._commit()
                continue
            if self._has_open_tracking("project_external_approval", approval.id, "admin_escalation"):
                continue
            self.db.add(EscalationTracking(
                entity_type="project_external_approval", entity_id=approval.id, stage="admin_escalation", triggered_at=now,
            ))
            OutboxService(self.db).emit(
                event_type="project_external_approval.escalated_to_admin",
                aggregate_type="project_external_approval",
                aggregate_id=approval.id,
                payload={
                    "approval_id": str(approval.id),
                    "project_id": str(approval.project_id),
                    "assigned_to_user_id": str(approval.assigned_to_user_id) if approval.assigned_to_user_id else None,
                    "due_at": approval.due_at.isoformat() if approval.due_at else None,
                },
                idempotency_key=f"project_external_approval:{approval.id}:project_external_approval.escalated_to_admin:{now.isoformat()}",
            )
            if not self._commit_new_tracking():
                continue
            escalated.append(approval)
        return escalated

    # ---- gate due-date reminder --------------------------------------------

    def emit_gate_due_reminders(self, now: datetime) -> list[ProjectExternalApproval]:
        """Tracks nothing and emits `project_external_approval.due_reminder`
        for every `assigned` approval whose `due_at` is tomorrow - the doc's
        "1 day before due" gate reminder. No `EscalationTracking` row: that
        table exists to answer "is a followup/escalation stage already
        open", which a one-shot day-before reminder does not need.

        Idempotent PER CALENDAR DAY rather than per exact timestamp - the
        idempotency key incorporates `now.date()`, not the full timestamp,
        so however often `gate_reminder_scheduler.py` ticks in one day, an
        approval gets at most one reminder that day. Mirrors
        `DailyTaskPromptsService`'s identical per-day convention
        (`app.services.daily_task_prompts`)."""
        reminded: list[ProjectExternalApproval] = []
        tomorrow = now.date() + timedelta(days=1)
        candidates = list(
            self.db.scalars(
                select(ProjectExternalApproval).where(
                    ProjectExternalApproval.due_at == tomorrow,
                    ProjectExternalApproval.status == "assigned",
                )
            ).all()
        )
        for approval in candidates:
            event = OutboxService(self.db).emit(
                event_type="project_external_approval.due_reminder",
                aggregate_type="project_external_approval",
                aggregate_id=approval.id,
                payload={
                    "approval_id": str(approval.id),
                    "project_id": str(approval.project_id),
                    "assigned_to_user_id": str(approval.assigned_to_user_id) if approval.assigned_to_user_id else None,
                    "due_at": approval.due_at.isoformat(),
                },
                idempotency_key=f"project_external_approval:{approval.id}:project_external_approval.due_reminder:{now.date().isoformat()}",
            )
            self._commit()
            if event is not None:
                reminded.append(approval)
        return reminded
