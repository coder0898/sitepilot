import asyncio
import logging

from app.config import settings
from app.services.notification_delivery import run_worker_cycle


logger = logging.getLogger("siteops.notification_worker")


async def notification_worker_loop():
    while True:
        try:
            result = await asyncio.to_thread(run_worker_cycle)
            if any(result.values()):
                logger.info("Mock notification cycle: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Mock notification worker cycle failed")
        await asyncio.sleep(max(settings.notification_worker_interval_seconds, 1))
