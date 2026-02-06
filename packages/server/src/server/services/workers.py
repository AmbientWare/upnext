"""Workers service - manages worker registry in Redis."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from server.services.redis import get_redis
from shared.schemas import Worker, WorkerStats

logger = logging.getLogger(__name__)

# TTL for worker keys (seconds) - worker must heartbeat within this time
# With 3s heartbeat interval, this gives 10 missed heartbeats before expiry
WORKER_TTL = 30

# Redis key prefixes
WORKER_KEY_PREFIX = "conduit:workers:"
FUNCTION_KEY_PREFIX = "conduit:functions:"


def _worker_key(worker_id: str) -> str:
    """Get Redis key for a worker."""
    return f"{WORKER_KEY_PREFIX}{worker_id}"


def _function_key(name: str) -> str:
    """Get Redis key for a function definition."""
    return f"{FUNCTION_KEY_PREFIX}{name}"


async def register_worker(
    worker_id: str,
    worker_name: str,
    started_at: datetime | None,
    functions: list[str],
    concurrency: int,
    hostname: str | None,
    version: str | None,
    function_definitions: list[dict[str, Any]] | None = None,
) -> None:
    """Register a worker in Redis with TTL."""
    r = await get_redis()

    worker_data = {
        "id": worker_id,
        "worker_name": worker_name,
        "started_at": started_at.isoformat()
        if started_at
        else datetime.now(UTC).isoformat(),
        "last_heartbeat": datetime.now(UTC).isoformat(),
        "functions": functions,
        "concurrency": concurrency,
        "active_jobs": 0,
        "jobs_processed": 0,
        "jobs_failed": 0,
        "hostname": hostname,
        "version": version,
    }

    # Store worker with TTL
    await r.setex(
        _worker_key(worker_id),
        WORKER_TTL,
        json.dumps(worker_data),
    )

    # Store function definitions (no TTL - persist until overwritten)
    if function_definitions:
        for func_def in function_definitions:
            name = func_def.get("name")
            if not name:
                continue

            func_data = {
                "name": name,
                "type": func_def.get("type", "task"),
                "timeout": func_def.get("timeout"),
                "max_retries": func_def.get("max_retries"),
                "retry_delay": func_def.get("retry_delay"),
                "schedule": func_def.get("schedule"),
                "timezone": func_def.get("timezone"),
                "pattern": func_def.get("pattern"),
                "source": func_def.get("source"),
                "batch_size": func_def.get("batch_size"),
                "batch_timeout": func_def.get("batch_timeout"),
                "max_concurrency": func_def.get("max_concurrency"),
            }
            await r.set(_function_key(name), json.dumps(func_data))

    logger.info(f"Worker registered: {worker_id} ({worker_name})")


async def deregister_worker(worker_id: str) -> None:
    """Remove a worker from Redis."""
    r = await get_redis()
    await r.delete(_worker_key(worker_id))
    logger.info(f"Worker deregistered: {worker_id}")


async def heartbeat_worker(
    worker_id: str,
    active_jobs: int = 0,
    jobs_processed: int = 0,
    jobs_failed: int = 0,
    queued_jobs: int = 0,
) -> bool:
    """Update worker heartbeat - refreshes TTL. Returns False if worker not found."""
    r = await get_redis()
    key = _worker_key(worker_id)

    # Get existing worker data
    data = await r.get(key)
    if not data:
        return False

    worker_data = json.loads(data)

    # Update heartbeat and stats
    worker_data["last_heartbeat"] = datetime.now(UTC).isoformat()
    worker_data["active_jobs"] = active_jobs
    worker_data["jobs_processed"] = jobs_processed
    worker_data["jobs_failed"] = jobs_failed
    worker_data["queued_jobs"] = queued_jobs

    # Refresh TTL
    await r.setex(key, WORKER_TTL, json.dumps(worker_data))
    return True


async def get_worker(worker_id: str) -> Worker | None:
    """Get a worker by ID."""
    r = await get_redis()
    data = await r.get(_worker_key(worker_id))

    if not data:
        return None

    worker_data = json.loads(data)
    return Worker(
        id=worker_data["id"],
        started_at=worker_data["started_at"],
        last_heartbeat=worker_data["last_heartbeat"],
        functions=worker_data.get("functions", []),
        concurrency=worker_data.get("concurrency", 10),
        active_jobs=worker_data.get("active_jobs", 0),
        jobs_processed=worker_data.get("jobs_processed", 0),
        jobs_failed=worker_data.get("jobs_failed", 0),
        hostname=worker_data.get("hostname"),
        version=worker_data.get("version"),
    )


async def list_workers() -> list[Worker]:
    """List all active workers."""
    r = await get_redis()
    workers: list[Worker] = []

    # Scan for all worker keys
    async for key in r.scan_iter(match=f"{WORKER_KEY_PREFIX}*", count=100):
        data = await r.get(key)
        if data:
            worker_data = json.loads(data)
            workers.append(
                Worker(
                    id=worker_data["id"],
                    started_at=worker_data["started_at"],
                    last_heartbeat=worker_data["last_heartbeat"],
                    functions=worker_data.get("functions", []),
                    concurrency=worker_data.get("concurrency", 10),
                    active_jobs=worker_data.get("active_jobs", 0),
                    jobs_processed=worker_data.get("jobs_processed", 0),
                    jobs_failed=worker_data.get("jobs_failed", 0),
                    hostname=worker_data.get("hostname"),
                    version=worker_data.get("version"),
                )
            )

    return workers


async def get_worker_stats() -> WorkerStats:
    """Get worker statistics."""
    r = await get_redis()
    total = 0

    # Scan for all worker keys
    async for _ in r.scan_iter(match=f"{WORKER_KEY_PREFIX}*", count=100):
        total += 1

    return WorkerStats(total=total)


async def get_function_definitions() -> dict[str, dict[str, Any]]:
    """Get all function definitions from Redis."""
    r = await get_redis()
    functions: dict[str, dict[str, Any]] = {}

    # Scan for all function keys
    async for key in r.scan_iter(match=f"{FUNCTION_KEY_PREFIX}*", count=100):
        data = await r.get(key)
        if data:
            func_data = json.loads(data)
            functions[func_data["name"]] = func_data

    return functions
