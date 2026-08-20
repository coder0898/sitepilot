"""Runs the evidence retention sweep (`app.services.evidence_retention`) on
a schedule, mirroring `outbox_scheduler.py`'s shape exactly: a purge policy
nobody ever calls is not a purge policy.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.database import SessionLocal
from app.services.evidence_retention import purge_expired_evidence

logger = logging.getLogger(__name__)

TASK_ATTRIBUTE = "evidence_retention_task"


def run_retention_pass() -> int:
    """One sweep pass, in its own session - see outbox_scheduler.py's
    `run_dispatch_pass` for why a pass owns its own session rather than
    sharing one across the process lifetime."""
    with SessionLocal() as db:
        return purge_expired_evidence(db)


async def retention_loop(interval_seconds: float, runner=run_retention_pass) -> None:
    """Sleeps before the first pass so application startup never waits on
    the database. Every failure mode other than cancellation is swallowed
    and logged, so one bad pass never ends the schedule."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            purged = await asyncio.to_thread(runner)
            if purged:
                logger.info("Evidence retention pass purged evidence for %s project(s).", purged)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Evidence retention pass failed; the schedule continues.")


def start_retention_scheduler(app) -> bool:
    if not settings.evidence_retention_enabled:
        logger.info("Evidence retention scheduler is disabled by configuration; evidence will never expire.")
        return False
    task = asyncio.create_task(retention_loop(settings.evidence_retention_interval_seconds))
    setattr(app.state, TASK_ATTRIBUTE, task)
    return True


async def stop_retention_scheduler(app) -> None:
    task = getattr(app.state, TASK_ATTRIBUTE, None)
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    setattr(app.state, TASK_ATTRIBUTE, None)
