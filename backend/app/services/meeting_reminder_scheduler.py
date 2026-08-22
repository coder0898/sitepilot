"""Plan Phase 9: the automated meeting-reminder pass, mirroring
`weekly_summary_scheduler.py`'s exact shape - see that module's own
docstring for the shape's rationale (itself following
`outbox_scheduler.py`'s convention, documented once in Phase 1c of the
plan).

An Admin can create a `Broadcast` with `send_mode == "scheduled"`
(`app.services.broadcast_service.create_broadcast`), which persists it with
`status == "scheduled"` and a `scheduled_at` timestamp but never delivers
it - today the only way to actually deliver it is a human clicking
`POST /{broadcast_id}/send` (`app.routes.broadcasts.post_send`), which calls
`send_scheduled_broadcast(db, actor, broadcast)`. Nothing watches
`scheduled_at` automatically. This pass is that missing automatic caller,
and nothing more - it does not touch `send_scheduled_broadcast` itself,
mirroring `outbox_scheduler.py`'s own framing of itself for the equivalent
gap.

The doc's "announcement now + reminder before the meeting" (SS9 #28/#29) is
satisfied at the Admin-workflow level, not here: an Admin creates two
`Broadcast` rows (one `send_mode="now"`, one `send_mode="scheduled"` set to
fire shortly before the meeting) - this pass just makes the second row's
`scheduled_at` actually get honoured without a manual click.

Idempotency: `send_scheduled_broadcast` flips `broadcast.status` away from
`"scheduled"` (to `"sent"`, `"partially_failed"`, or `"failed"` via
`_status_from_recipients`) as part of the same call, and commits. Because
this pass's own selection query filters on `status == "scheduled"`, a
broadcast that was just sent is structurally excluded from every subsequent
pass - there is no separate idempotency-key mechanism here (unlike the
outbox's event-emission schedulers), because this is a direct, committed
state transition on the row being selected, not a fire-and-forget event
emission that could be re-selected before its own effect is visible.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broadcast_models import Broadcast
from app.config import settings
from app.database import SessionLocal
from app.services.broadcast_service import send_scheduled_broadcast
from app.services.scheduler_actor import get_system_actor

logger = logging.getLogger(__name__)

TASK_ATTRIBUTE = "meeting_reminder_task"


def _aware(value: datetime) -> datetime:
    """Postgres `timestamptz` columns always round-trip as timezone-aware
    via psycopg, but SQLite (this test suite's harness) silently drops
    tzinfo on read - treat a naive value as UTC rather than let a
    naive/aware comparison raise `TypeError`. Mirrors
    `weekly_summary_scheduler.py`'s own identical `_aware` helper."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def run_meeting_reminder_pass() -> int:
    """One pass, in its own session - see outbox_scheduler.py's
    `run_dispatch_pass` for why a pass owns its own session rather than
    sharing one across the process lifetime.

    `now` is captured once so every broadcast in one pass is judged "due"
    against the same instant. Returns the number of broadcasts sent.
    """
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        actor = get_system_actor(db)
        due = list(db.scalars(
            select(Broadcast).where(Broadcast.status == "scheduled")
        ).all())
        sent = 0
        for broadcast in due:
            if broadcast.scheduled_at is None or _aware(broadcast.scheduled_at) > now:
                continue
            try:
                send_scheduled_broadcast(db, actor, broadcast)
            except Exception:
                # One broadcast failing to send must not stop every other
                # due broadcast in this pass from going out.
                logger.exception("Failed to send scheduled broadcast %s; skipping and continuing.", broadcast.id)
                db.rollback()
                continue
            sent += 1
        return sent


async def meeting_reminder_loop(interval_seconds: float, runner=run_meeting_reminder_pass) -> None:
    """Sleeps before the first pass so application startup never waits on
    the database. Every failure mode other than cancellation is swallowed
    and logged, so one bad pass never ends the schedule."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            # Off the event loop: this pass is blocking SQLAlchemy, and
            # running it inline would stall every request handler for the
            # duration of the pass.
            sent = await asyncio.to_thread(runner)
            if sent:
                logger.info("Meeting reminder pass sent %s broadcast(s).", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Meeting reminder pass failed; the schedule continues.")


def start_meeting_reminder_scheduler(app) -> bool:
    """Starts the loop as a background task. Returns whether it started.

    Must be called from async context - it needs a running event loop to
    attach the task to.
    """
    if not settings.meeting_reminder_enabled:
        logger.info("Meeting reminder scheduler is disabled by configuration; scheduled broadcasts will never auto-send.")
        return False
    task = asyncio.create_task(meeting_reminder_loop(settings.meeting_reminder_interval_seconds))
    setattr(app.state, TASK_ATTRIBUTE, task)
    return True


async def stop_meeting_reminder_scheduler(app) -> None:
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
