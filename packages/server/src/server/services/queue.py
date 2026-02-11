"""Queue metrics service - reads queue depth from Redis streams."""

import json
import logging
from dataclasses import dataclass

from shared.queue import QUEUE_CONSUMER_GROUP, QUEUE_KEY_PREFIX
from shared.workers import WORKER_INSTANCE_KEY_PREFIX

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueueDepthStats:
    """Aggregate queue depth metrics."""

    running: int
    waiting: int
    claimed: int
    capacity: int
    total: int


def _coerce_int(value: object) -> int:
    """Convert Redis mixed int/str/bytes payloads to int safely."""
    if isinstance(value, int):
        return value
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


async def get_queue_depth_stats() -> QueueDepthStats:
    """
    Get total queue depth directly from Redis.

    - waiting: sum of stream consumer-group lag (not yet claimed)
    - claimed: sum of consumer-group pending (claimed, not acked)
    - running: sum of worker heartbeat active_jobs (currently executing)
    - capacity: sum of worker heartbeat concurrency
    - total: running + waiting
    """
    try:
        r = await get_redis()
        stream_pattern = f"{QUEUE_KEY_PREFIX}:fn:*:stream"

        waiting = 0
        claimed = 0
        async for stream_key in r.scan_iter(match=stream_pattern, count=100):
            try:
                groups = await r.xinfo_groups(stream_key)
            except Exception:
                continue

            for group in groups:
                if not isinstance(group, dict):
                    continue
                name = group.get("name", group.get(b"name"))
                if isinstance(name, bytes):
                    name = name.decode()
                if name != QUEUE_CONSUMER_GROUP:
                    continue

                lag = _coerce_int(group.get("lag", group.get(b"lag", 0)))
                pending = _coerce_int(group.get("pending", group.get(b"pending", 0)))
                waiting += max(lag, 0)
                claimed += max(pending, 0)
                break

        running = 0
        capacity = 0
        async for worker_key in r.scan_iter(
            match=f"{WORKER_INSTANCE_KEY_PREFIX}:*", count=100
        ):
            data = await r.get(worker_key)
            if not data:
                continue
            try:
                payload = json.loads(data)
            except Exception:
                continue
            running += max(_coerce_int(payload.get("active_jobs", 0)), 0)
            capacity += max(_coerce_int(payload.get("concurrency", 0)), 0)

        return QueueDepthStats(
            running=running,
            waiting=waiting,
            claimed=claimed,
            capacity=capacity,
            total=running + waiting,
        )
    except Exception as e:
        logger.debug("Could not get queue depth stats: %s", e)
        return QueueDepthStats(running=0, waiting=0, claimed=0, capacity=0, total=0)
