"""Queue service - gets queue stats from worker reports.

Since this is a SaaS, the API cannot connect to the user's Redis directly.
Instead, workers report queue stats in their heartbeats, and we aggregate here.
"""

import json
import logging
from datetime import datetime

from api.services.redis import get_redis

logger = logging.getLogger(__name__)

# Redis key prefix for workers (must match workers service)
WORKER_KEY_PREFIX = "conduit:workers:"


async def get_queue_stats() -> tuple[int, int]:
    """
    Get active and queued job counts from worker reports.

    Returns (active, queued) aggregated from all registered workers.

    - active = sum of active_jobs from all workers (each reports their own)
    - queued = from most recently heartbeated worker (all see same queue)
    """
    try:
        r = await get_redis()

        total_active = 0
        latest_queued = 0
        latest_heartbeat: datetime | None = None

        # Scan all worker keys and aggregate stats
        async for key in r.scan_iter(match=f"{WORKER_KEY_PREFIX}*", count=100):
            data = await r.get(key)
            if data:
                worker_data = json.loads(data)

                # Sum active jobs across all workers (each has its own)
                total_active += worker_data.get("active_jobs", 0)

                # Use queued_jobs from most recent heartbeat
                # (all workers see the same queue, so pick freshest data)
                heartbeat_str = worker_data.get("last_heartbeat")
                if heartbeat_str:
                    heartbeat = datetime.fromisoformat(heartbeat_str)
                    if latest_heartbeat is None or heartbeat > latest_heartbeat:
                        latest_heartbeat = heartbeat
                        latest_queued = worker_data.get("queued_jobs", 0)

        return total_active, latest_queued

    except Exception as e:
        logger.debug(f"Could not get queue stats: {e}")
        return 0, 0
