"""Workers service - reads worker data from Redis.

Workers write their own heartbeat data directly to Redis (via the SDK).
This module reads those keys for the dashboard.
"""

import json
import logging
from typing import Any

from shared.contracts import FunctionConfig, WorkerInstance, WorkerStats
from shared.keys import (
    function_definition_pattern,
    worker_definition_pattern,
    worker_instance_key,
    worker_instance_pattern,
)

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
        function_names=d.get("function_names", {}),
        concurrency=d.get("concurrency", 1),
        active_jobs=d.get("active_jobs", 0),
        jobs_processed=d.get("jobs_processed", 0),
        jobs_failed=d.get("jobs_failed", 0),
        hostname=d.get("hostname"),
    )


async def get_worker_instance(worker_id: str) -> WorkerInstance | None:
    """Get a worker instance by ID."""
    r = await get_redis()
    key = worker_instance_key(worker_id)
    try:
        data = await r.get(key)
    except Exception:
        return None

    if not data:
        return None

    try:
        return _parse_worker_instance(data)
    except Exception:
        logger.debug("Invalid worker instance payload for key=%s", key)
        return None


async def list_worker_instances() -> list[WorkerInstance]:
    """List all active worker instances from Redis."""
    r = await get_redis()
    instances: list[WorkerInstance] = []

    async for key in r.scan_iter(match=worker_instance_pattern(), count=100):
        try:
            data = await r.get(key)
        except Exception:
            logger.debug("Skipping unreadable worker key %s", key)
            continue

        if not data:
            continue

        try:
            instances.append(_parse_worker_instance(data))
        except Exception:
            logger.debug("Skipping malformed worker payload for key %s", key)
            continue

    return instances


async def get_worker_definitions() -> dict[str, dict[str, Any]]:
    """Get all persistent worker definitions from Redis."""
    r = await get_redis()
    defs: dict[str, dict[str, Any]] = {}

    async for key in r.scan_iter(match=worker_definition_pattern(), count=100):
        data = await r.get(key)
        if data:
            d = json.loads(data)
            defs[d["name"]] = d

    return defs


async def get_worker_stats() -> WorkerStats:
    """Get worker statistics."""
    r = await get_redis()
    total = 0
    async for _ in r.scan_iter(match=worker_instance_pattern(), count=100):
        total += 1
    return WorkerStats(total=total)


async def get_function_definitions() -> dict[str, FunctionConfig]:
    """Get all function definitions from Redis."""
    r = await get_redis()
    functions: dict[str, FunctionConfig] = {}

    async for key in r.scan_iter(match=function_definition_pattern(), count=100):
        data = await r.get(key)
        if data:
            payload = data.decode() if isinstance(data, bytes) else str(data)
            try:
                func_data = FunctionConfig.model_validate_json(payload)
            except Exception:
                logger.debug("Skipping malformed function payload for key %s", key)
                continue

            func_key = func_data.key or func_data.name
            if not func_key:
                continue
            functions[func_key] = func_data

    return functions
