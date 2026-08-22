"""Plan Phase 6 (second half): runs the external-approval gate due-date
reminder and the approval-side escalation sweep in one pass, mirroring
`outbox_scheduler.py`'s shape exactly - see that module's docstring for the
shape's own rationale.

Kept in a separate file from `daily_task_prompts_scheduler.py` on purpose:
a `ProjectExternalApproval` gate is a different aggregate on a different
cadence than a `Task`, per the plan's own phase framing - folding the two
into one file would blur that distinction for no benefit.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal
from app.services.escalation import EscalationService

logger = logging.getLogger(__name__)

TASK_ATTRIBUTE = "gate_reminder_task"


def run_gate_reminder_pass() -> int:
    """One pass, in its own session - see outbox_scheduler.py's
    `run_dispatch_pass` for why a pass owns its own session rather than
    sharing one across the process lifetime.

    `now` is captured once here and threaded through every call in this
    pass, matching `daily_task_prompts_scheduler.py`'s own discipline.
    Returns the total number of approvals that had an event emitted across
    all three calls.

    Each call is isolated from the others: one raising is logged and
    skipped rather than aborting the remaining calls in the same tick.
    """
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        escalation = EscalationService(db)
        processed = 0
        for label, call in (
            ("emit_gate_due_reminders", lambda: escalation.emit_gate_due_reminders(now)),
            ("sweep_approval_followups", lambda: escalation.sweep_approval_followups(now)),
            ("sweep_approval_escalations", lambda: escalation.sweep_approval_escalations(now)),
        ):
            try:
                processed += len(call())
            except Exception:
                logger.exception("Gate reminder pass: %s failed; continuing with the rest of the pass.", label)
                db.rollback()
        return processed


async def gate_reminder_loop(interval_seconds: float, runner=run_gate_reminder_pass) -> None:
    """Sleeps before the first pass so application startup never waits on
    the database. Every failure mode other than cancellation is swallowed
    and logged, so one bad pass never ends the schedule."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            # Off the event loop: this pass is blocking SQLAlchemy, and
            # running it inline would stall every request handler for the
            # duration of the pass.
            processed = await asyncio.to_thread(runner)
            if processed:
                logger.info("Gate reminder pass processed %s event(s).", processed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Gate reminder pass failed; the schedule continues.")


def start_gate_reminder_scheduler(app) -> bool:
    """Starts the loop as a background task. Returns whether it started.

    Must be called from async context - it needs a running event loop to
    attach the task to.
    """
    if not settings.gate_reminder_enabled:
        logger.info("Gate reminder scheduler is disabled by configuration; gate reminders will never fire.")
        return False
    task = asyncio.create_task(gate_reminder_loop(settings.gate_reminder_interval_seconds))
    setattr(app.state, TASK_ATTRIBUTE, task)
    return True


async def stop_gate_reminder_scheduler(app) -> None:
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
