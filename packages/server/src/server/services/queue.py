"""Queue service - gets active job count from worker reports."""

import json
import logging

from shared.workers import WORKER_KEY_PREFIX

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


async def get_active_job_count() -> int:
    """
    Get total active job count from worker heartbeats.

    Sums active_jobs across all live worker instances.
    """
    try:
        r = await get_redis()
        total_active = 0

        async for key in r.scan_iter(match=f"{WORKER_KEY_PREFIX}:*", count=100):
            data = await r.get(key)
            if data:
                worker_data = json.loads(data)
                total_active += worker_data.get("active_jobs", 0)

        return total_active

    except Exception as e:
        logger.debug(f"Could not get active job count: {e}")
        return 0
