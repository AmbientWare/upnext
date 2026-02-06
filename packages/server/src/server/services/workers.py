"""Workers service - reads worker data from Redis.

Workers write their own heartbeat data directly to Redis (via the SDK).
This module reads those keys for the dashboard.
"""

import json
import logging
from typing import Any

from shared.schemas import WorkerInstance, WorkerStats
from shared.workers import FUNCTION_KEY_PREFIX, WORKER_DEF_PREFIX, WORKER_KEY_PREFIX

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


def _parse_worker_instance(data: str) -> WorkerInstance:
    """Parse a worker instance from a Redis JSON value."""
    d = json.loads(data)
    return WorkerInstance(
        id=d["id"],
        worker_name=d.get("worker_name", ""),
        started_at=d["started_at"],
        last_heartbeat=d["last_heartbeat"],
        functions=d.get("functions", []),
        concurrency=d.get("concurrency", 1),
        active_jobs=d.get("active_jobs", 0),
        jobs_processed=d.get("jobs_processed", 0),
        jobs_failed=d.get("jobs_failed", 0),
        hostname=d.get("hostname"),
    )


async def get_worker_instance(worker_id: str) -> WorkerInstance | None:
    """Get a worker instance by ID."""
    r = await get_redis()
    data = await r.get(f"{WORKER_KEY_PREFIX}:{worker_id}")
    if not data:
        return None
    return _parse_worker_instance(data)


async def list_worker_instances() -> list[WorkerInstance]:
    """List all active worker instances from Redis."""
    r = await get_redis()
    instances: list[WorkerInstance] = []

    async for key in r.scan_iter(match=f"{WORKER_KEY_PREFIX}:*", count=100):
        data = await r.get(key)
        if data:
            instances.append(_parse_worker_instance(data))

    return instances


async def get_worker_definitions() -> dict[str, dict[str, Any]]:
    """Get all persistent worker definitions from Redis."""
    r = await get_redis()
    defs: dict[str, dict[str, Any]] = {}

    async for key in r.scan_iter(match=f"{WORKER_DEF_PREFIX}:*", count=100):
        data = await r.get(key)
        if data:
            d = json.loads(data)
            defs[d["name"]] = d

    return defs


async def get_worker_stats() -> WorkerStats:
    """Get worker statistics."""
    r = await get_redis()
    total = 0

    async for _ in r.scan_iter(match=f"{WORKER_KEY_PREFIX}:*", count=100):
        total += 1

    return WorkerStats(total=total)


async def get_function_definitions() -> dict[str, dict[str, Any]]:
    """Get all function definitions from Redis."""
    r = await get_redis()
    functions: dict[str, dict[str, Any]] = {}

    async for key in r.scan_iter(match=f"{FUNCTION_KEY_PREFIX}:*", count=100):
        data = await r.get(key)
        if data:
            func_data = json.loads(data)
            functions[func_data["name"]] = func_data

    return functions
