"""Plan Phase 8: the automated weekly report-summary pass, mirroring
`daily_task_prompts_scheduler.py`'s/`gate_reminder_scheduler.py`'s exact
shape - see either module's own docstring for the shape's rationale.

For each active `V2Project` (`status == 'active'`, the same single-status-
equality convention `evidence_retention.py`'s `_eligible_projects` already
uses for its own project scan - a draft/on_hold/completed/archived project
has no ongoing weekly cadence to report on), this pass checks whether a new
weekly `ReportSnapshot` is due (7+ days since the most recent one's
`period_end` - see `_is_weekly_summary_due`'s own docstring for why
`period_end`, not `period_start`, is the correct field to gate on for a
trailing-window report - or no weekly snapshot yet exists) and, if so, calls
`ReportGenerationService.generate` with a trailing 7-day window ending
`now`, attributed to the shared system actor
(`app.services.scheduler_actor.get_system_actor` - see that module's
docstring for why one dedicated `User` row is reused here and by Phase 9's
scheduler rather than a per-service bypass).

On a successful generate, emits `report.weekly_summary_generated`
(`aggregate_type="project"`) - already routed to PM/Supervisor by
`message_dispatch.py`'s existing `project` branch, plus Admin via this
phase's `_ADMIN_CC_PROJECT_EVENTS` allowlist, with zero further wiring
needed here.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.project_models import V2Project
from app.report_models import ReportSnapshot
from app.services.outbox import OutboxService
from app.services.report_generation import ReportGenerationService
from app.services.scheduler_actor import get_system_actor

logger = logging.getLogger(__name__)

TASK_ATTRIBUTE = "weekly_summary_task"

WEEKLY_CADENCE_DAYS = 7
"""How often a project's weekly summary re-generates - the doc's "weekly"
cadence, and the window width `run_weekly_summary_pass` uses for the report
itself (a trailing 7-day window ending `now`)."""


def _aware(value: datetime) -> datetime:
    """Postgres `timestamptz` columns always round-trip as timezone-aware
    via psycopg, but SQLite (this test suite's harness) silently drops
    tzinfo on read - treat a naive value as UTC rather than let a
    naive/aware subtraction raise `TypeError`. Mirrors
    `project_visibility.py`'s/`escalation.py`'s own identical `_aware`
    helper."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _latest_weekly_snapshot(db: Session, project_id: uuid.UUID) -> ReportSnapshot | None:
    return db.scalar(
        select(ReportSnapshot)
        .where(ReportSnapshot.project_id == project_id, ReportSnapshot.report_type == "weekly")
        .order_by(ReportSnapshot.period_end.desc())
        .limit(1)
    )


def _is_weekly_summary_due(db: Session, project_id: uuid.UUID, now: datetime) -> bool:
    """No prior weekly snapshot -> due (the project's first one). Otherwise
    due once `WEEKLY_CADENCE_DAYS` have passed since the latest snapshot's
    `period_end`.

    Gated on `period_end`, not `period_start`: every window this pass builds
    is a TRAILING 7-day window ending at generation time (`period_end ==
    now` at the moment a snapshot is written), so `period_start` is already
    exactly `WEEKLY_CADENCE_DAYS` in the past the instant a snapshot is
    created. Comparing elapsed time against `period_start` is therefore
    equivalent to `elapsed_since_generation >= 0` - true immediately,
    which would regenerate a report on every tick instead of every 7 days.
    `period_end` is the actual generation instant, so gating on it is what
    makes "7 days have passed since the last weekly report" mean what it
    says."""
    last = _latest_weekly_snapshot(db, project_id)
    if last is None:
        return True
    return (now - _aware(last.period_end)) >= timedelta(days=WEEKLY_CADENCE_DAYS)


def run_weekly_summary_pass() -> int:
    """One pass, in its own session - see outbox_scheduler.py's
    `run_dispatch_pass` for why a pass owns its own session rather than
    sharing one across the process lifetime.

    `now` is captured once and threaded through the due-check and the
    generated report's window, so every project in one pass is evaluated
    against (and reported over a window ending at) the exact same instant.
    Returns the number of projects a new weekly report was generated for.
    """
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=WEEKLY_CADENCE_DAYS)
    with SessionLocal() as db:
        actor = get_system_actor(db)
        generator = ReportGenerationService(db)
        generated = 0
        projects = list(db.scalars(select(V2Project).where(V2Project.status == "active")).all())
        for project in projects:
            if not _is_weekly_summary_due(db, project.id, now):
                continue
            snapshot = generator.generate(project.id, "weekly", period_start, now, actor)
            OutboxService(db).emit(
                event_type="report.weekly_summary_generated",
                aggregate_type="project",
                aggregate_id=project.id,
                payload={"project_id": str(project.id), "report_snapshot_id": str(snapshot.id)},
                # Keyed on the snapshot's own id - unique per generate() call,
                # so a re-run of this same pass before the next 7-day window
                # opens (the due-check above already prevents that, but this
                # is the belt to that braces) can never double-emit for the
                # same report.
                idempotency_key=f"project:{project.id}:report.weekly_summary_generated:{snapshot.id}",
            )
            db.commit()
            generated += 1
        return generated


async def weekly_summary_loop(interval_seconds: float, runner=run_weekly_summary_pass) -> None:
    """Sleeps before the first pass so application startup never waits on
    the database. Every failure mode other than cancellation is swallowed
    and logged, so one bad pass never ends the schedule."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            # Off the event loop: this pass is blocking SQLAlchemy, and
            # running it inline would stall every request handler for the
            # duration of the pass.
            generated = await asyncio.to_thread(runner)
            if generated:
                logger.info("Weekly summary pass generated %s report(s).", generated)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Weekly summary pass failed; the schedule continues.")


def start_weekly_summary_scheduler(app) -> bool:
    """Starts the loop as a background task. Returns whether it started.

    Must be called from async context - it needs a running event loop to
    attach the task to.
    """
    if not settings.weekly_summary_enabled:
        logger.info("Weekly summary scheduler is disabled by configuration; weekly reports will never auto-generate.")
        return False
    task = asyncio.create_task(weekly_summary_loop(settings.weekly_summary_interval_seconds))
    setattr(app.state, TASK_ATTRIBUTE, task)
    return True


async def stop_weekly_summary_scheduler(app) -> None:
    """Cancels the loop and waits for it to finish.

    Without this a reload or a test that builds an app leaves the task
    running against a closed loop, which surfaces later as an unrelated and
    very confusing warning.
    """
    task = getattr(app.state, TASK_ATTRIBUTE, None)
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    setattr(app.state, TASK_ATTRIBUTE, None)
