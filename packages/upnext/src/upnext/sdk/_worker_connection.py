"""Connection and lifecycle helpers for Worker.

Extracted from worker.py to separate Redis connection, heartbeat,
function definition publishing, and cron seeding from registration logic.
"""

import asyncio
import json
import logging
import time as time_module
from datetime import UTC, datetime
from typing import Any

from shared.contracts import FunctionConfig, WorkerDefinition, WorkerSignalStreamEvent
from shared.domain import CronSource, Job
from shared.keys import (
    DEFAULT_WORKSPACE_ID,
    FUNCTION_DEF_TTL,
    WORKER_DEF_TTL,
    WORKER_HEARTBEAT_INTERVAL,
    WORKER_TTL,
    cron_registry_member_key,
    function_definition_key,
    normalize_workspace_id,
    worker_events_stream_key,
    worker_definition_key,
    worker_instance_key,
)

from upnext.engine.cron import calculate_next_cron_run
from upnext.engine.queue import RedisQueue
from upnext.engine.registry import CronDefinition

logger = logging.getLogger(__name__)


async def seed_crons(
    crons: list[CronDefinition],
    queue: RedisQueue,
) -> None:
    """Seed cron jobs using Redis-based scheduling."""
    for cron_def in crons:
        try:
            next_run = calculate_next_cron_run(cron_def.schedule)

            job = Job(
                function=cron_def.key,
                function_name=cron_def.display_name,
                kwargs={},
                key=cron_registry_member_key(cron_def.key),
                timeout=cron_def.timeout,
                source=CronSource(schedule=cron_def.schedule),
            )

            was_seeded = await queue.seed_cron(job, next_run.timestamp())
            if was_seeded:
                logger.debug(
                    f"Seeded cron '{cron_def.display_name}' ({cron_def.key}) → {next_run}"
                )
            else:
                reconciled = await queue.reconcile_cron_startup(
                    job,
                    now_ts=time_module.time(),
                )
                if reconciled:
                    logger.debug(
                        "Cron '%s' (%s) startup reconciliation enqueued catch-up run",
                        cron_def.display_name,
                        cron_def.key,
                    )
                else:
                    logger.debug(
                        f"Cron '{cron_def.display_name}' ({cron_def.key}) already registered"
                    )

        except ValueError:
            raise

        except Exception as e:
            logger.error(
                f"Failed to seed cron job '{cron_def.display_name}' ({cron_def.key}): {e}"
            )


async def write_worker_heartbeat(
    redis_client: Any,
    worker_id: str,
    worker_data: str,
    *,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> None:
    """Write worker data to Redis with TTL."""
    normalized_workspace_id = normalize_workspace_id(workspace_id)
    key = worker_instance_key(worker_id, workspace_id=normalized_workspace_id)
    await redis_client.setex(key, WORKER_TTL, worker_data)
    await publish_worker_signal(
        redis_client,
        worker_id,
        "",
        "worker.heartbeat",
        workspace_id=normalized_workspace_id,
    )


async def write_worker_definition(
    redis_client: Any,
    worker_name: str,
    registered_functions: list[str],
    function_name_map: dict[str, str],
    concurrency: int,
    *,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> None:
    """Write persistent worker definition to Redis with 30-day TTL."""
    normalized_workspace_id = normalize_workspace_id(workspace_id)
    key = worker_definition_key(worker_name, workspace_id=normalized_workspace_id)
    definition = WorkerDefinition(
        name=worker_name,
        functions=registered_functions,
        function_names=function_name_map,
        concurrency=concurrency,
    )
    await redis_client.setex(key, WORKER_DEF_TTL, definition.model_dump_json())
    await publish_worker_signal(
        redis_client,
        "",
        worker_name,
        "worker.definition.updated",
        workspace_id=normalized_workspace_id,
    )


async def write_function_definitions(
    redis_client: Any,
    function_definitions: list[FunctionConfig],
    *,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> None:
    """Write function definitions to Redis with a 30-day TTL."""
    normalized_workspace_id = normalize_workspace_id(workspace_id)
    keys = [
        function_definition_key(func_def.key, workspace_id=normalized_workspace_id)
        for func_def in function_definitions
    ]
    existing_rows = await redis_client.mget(keys) if keys else []

    async with redis_client.pipeline(transaction=False) as pipe:
        for func_def, key, existing in zip(
            function_definitions,
            keys,
            existing_rows,
            strict=False,
        ):
            updated_def = func_def
            if existing:
                payload = (
                    existing.decode() if isinstance(existing, bytes) else str(existing)
                )
                try:
                    existing_def = FunctionConfig.model_validate_json(payload)
                    updated_def = func_def.model_copy(
                        update={"paused": existing_def.paused}
                    )
                except Exception:
                    pass
            pipe.setex(
                key,
                FUNCTION_DEF_TTL,
                updated_def.model_dump_json(),
            )
        await pipe.execute()


async def publish_worker_signal(
    redis_client: Any,
    worker_id: str,
    worker_name: str,
    signal_type: str,
    *,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> None:
    """Publish worker heartbeat/lifecycle signal for realtime dashboards."""
    normalized_workspace_id = normalize_workspace_id(workspace_id)
    payload = WorkerSignalStreamEvent(
        type=signal_type,
        workspace_id=normalized_workspace_id,
        at=datetime.now(UTC).isoformat(),
        worker_id=worker_id or None,
        worker_name=worker_name or None,
    )
    stream_key = worker_events_stream_key(workspace_id=normalized_workspace_id)
    try:
        try:
            await redis_client.xadd(
                stream_key,
                {"data": payload.model_dump_json()},
                maxlen=10_000,
                approximate=True,
            )
        except TypeError:
            await redis_client.xadd(
                stream_key,
                {"data": payload.model_dump_json()},
                maxlen=10_000,
            )
    except Exception as e:
        logger.debug(f"Failed to publish worker signal '{signal_type}': {e}")


async def heartbeat_loop(
    redis_client: Any,
    worker_id: str,
    get_worker_data: Any,
    *,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> None:
    """Refresh worker heartbeat TTL in Redis periodically."""
    while True:
        try:
            await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL)
            await write_worker_heartbeat(
                redis_client,
                worker_id,
                get_worker_data(),
                workspace_id=workspace_id,
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Worker heartbeat error: {e}")
            await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL)
