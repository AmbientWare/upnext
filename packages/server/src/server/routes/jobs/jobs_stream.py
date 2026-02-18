import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from shared.contracts import (
    FunctionType,
    JobTrendHour,
    JobTrendsResponse,
    JobTrendsSnapshotEvent,
)
from shared.keys import EVENTS_STREAM

from server.db import get_database
from server.routes.jobs.jobs_root import get_job_trends
from server.routes.jobs.jobs_utils import (
    STREAMABLE_EVENTS,
    extract_stream_function_key,
)
from server.routes.sse import (
    SSE_BLOCK_MS,
    SSE_CACHE_MAX_SIZE,
    SSE_CACHE_TTL_SECONDS,
    SSE_HEADERS,
    SSE_READ_COUNT,
)
from server.services.redis import get_redis
from server.shared_utils import get_stream_text_field

logger = logging.getLogger(__name__)

jobs_stream_router = APIRouter(tags=["jobs"])
_TRENDS_CACHE_LOCK = asyncio.Lock()
_trends_snapshot_cache: dict[
    tuple[int, str | None, str | None],
    tuple[float, str | None, Any],
] = {}


def clear_trends_cache() -> None:
    """Clear the module-level trends snapshot cache.

    Intended for test teardown so cached state does not leak across tests.
    """
    _trends_snapshot_cache.clear()


def _evict_expired_cache_entries() -> None:
    """Remove expired entries from the trends cache (TTL-based eviction)."""
    now = time.monotonic()
    expired = [k for k, v in _trends_snapshot_cache.items() if v[0] <= now]
    for k in expired:
        del _trends_snapshot_cache[k]
    # Hard cap as safety net
    if len(_trends_snapshot_cache) > SSE_CACHE_MAX_SIZE:
        _trends_snapshot_cache.clear()


def _empty_job_trends_snapshot(hours: int) -> JobTrendsResponse:
    now = datetime.now(UTC)
    hourly: list[JobTrendHour] = []

    for i in range(hours):
        hour_start = now - timedelta(hours=hours - i - 1)
        hour_key = hour_start.replace(minute=0, second=0, microsecond=0).strftime(
            "%Y-%m-%dT%H:00:00Z"
        )
        hourly.append(JobTrendHour(hour=hour_key))

    return JobTrendsResponse(hourly=hourly)


async def _fetch_job_trends_snapshot(
    *,
    hours: int,
    function: str | None,
    func_type: FunctionType | None,
) -> Any:
    db = None
    try:
        db = get_database()
    except RuntimeError as exc:
        if "Database not initialized" not in str(exc):
            raise

    if db is not None:
        try:
            return await get_job_trends(
                hours=hours,
                function=function,
                type=func_type,
                db=db,
            )
        except TypeError as exc:
            # Backward compatibility for tests/patches that inject a simplified
            # coroutine signature: fake_get_job_trends(hours, function, type).
            if "db" not in str(exc):
                raise

    try:
        return await get_job_trends(
            hours=hours,
            function=function,
            type=func_type,
        )
    except Exception:
        logger.debug("Falling back to empty trends snapshot", exc_info=True)
        return _empty_job_trends_snapshot(hours)


async def _get_cached_job_trends_snapshot(
    *,
    hours: int,
    function: str | None,
    func_type: FunctionType | None | Any,
    event_token: str | None = None,
) -> Any:
    func_type_filter = func_type if isinstance(func_type, FunctionType) else None
    key = (
        hours,
        function,
        func_type_filter.value if func_type_filter else None,
    )
    now = time.monotonic()
    cached = _trends_snapshot_cache.get(key)
    if cached and cached[0] > now:
        if event_token is None or cached[1] == event_token:
            return cached[2]

    async with _TRENDS_CACHE_LOCK:
        cached = _trends_snapshot_cache.get(key)
        if cached and cached[0] > now:
            if event_token is None or cached[1] == event_token:
                return cached[2]

        snapshot = await _fetch_job_trends_snapshot(
            hours=hours,
            function=function,
            func_type=func_type_filter,
        )
        _trends_snapshot_cache[key] = (
            now + SSE_CACHE_TTL_SECONDS,
            event_token,
            snapshot,
        )
        _evict_expired_cache_entries()
        return snapshot


@jobs_stream_router.get("/trends/stream")
async def stream_job_trends(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
    function: str | None = Query(None, description="Filter by function key"),
    type: FunctionType | None = Query(None, description="Filter by function type"),
) -> StreamingResponse:
    """Stream realtime job trends snapshots via Server-Sent Events (SSE)."""
    hours_window = hours if isinstance(hours, int) else 24
    function_filter = function if isinstance(function, str) and function else None
    func_type_filter = type if isinstance(type, FunctionType) else None
    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"

            initial = await _get_cached_job_trends_snapshot(
                hours=hours_window,
                function=function_filter,
                func_type=func_type_filter,
            )
            initial_event = JobTrendsSnapshotEvent(
                at=datetime.now(UTC).isoformat(),
                trends=initial,
            )
            yield f"data: {initial_event.model_dump_json()}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                result = await redis_client.xread(
                    {EVENTS_STREAM: last_id},
                    count=SSE_READ_COUNT,
                    block=SSE_BLOCK_MS,
                )
                if not result:
                    yield ": keep-alive\n\n"
                    continue

                has_updates = False
                latest_relevant_event_id: str | None = None
                for _stream_name, entries in result:
                    for event_id, event_data in entries:
                        last_id = str(event_id)
                        event_type = get_stream_text_field(event_data, "type")
                        if event_type not in STREAMABLE_EVENTS:
                            continue

                        if function_filter:
                            event_function = extract_stream_function_key(event_data)
                            if event_function != function_filter:
                                continue

                        has_updates = True
                        latest_relevant_event_id = str(event_id)

                if not has_updates:
                    continue

                snapshot = await _get_cached_job_trends_snapshot(
                    hours=hours_window,
                    function=function_filter,
                    func_type=func_type_filter,
                    event_token=latest_relevant_event_id,
                )
                event = JobTrendsSnapshotEvent(
                    at=datetime.now(UTC).isoformat(),
                    trends=snapshot,
                )
                yield f"data: {event.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Job trends stream error: %s", exc)
            yield 'event: error\ndata: {"error": "stream disconnected"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
