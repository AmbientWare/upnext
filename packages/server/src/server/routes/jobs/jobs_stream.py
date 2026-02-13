import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from shared.contracts import FunctionType, JobTrendsSnapshotEvent
from shared.keys import EVENTS_STREAM

from server.routes.jobs.jobs_root import get_job_trends
from server.routes.jobs.jobs_utils import (
    STREAMABLE_EVENTS,
    extract_stream_function_key,
)
from server.services.redis import get_redis
from server.shared_utils import get_stream_text_field

logger = logging.getLogger(__name__)

jobs_stream_router = APIRouter(tags=["jobs"])
_TRENDS_CACHE_LOCK = asyncio.Lock()
_TRENDS_CACHE_TTL_SECONDS = 0.75
_trends_snapshot_cache: dict[
    tuple[int, str | None, str | None, int],
    tuple[float, str | None, Any],
] = {}


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
        id(get_job_trends),
    )
    now = asyncio.get_running_loop().time()
    cached = _trends_snapshot_cache.get(key)
    if cached and cached[0] > now:
        if event_token is None or cached[1] == event_token:
            return cached[2]

    async with _TRENDS_CACHE_LOCK:
        cached = _trends_snapshot_cache.get(key)
        if cached and cached[0] > now:
            if event_token is None or cached[1] == event_token:
                return cached[2]

        snapshot = await get_job_trends(
            hours=hours,
            function=function,
            type=func_type_filter,
        )
        _trends_snapshot_cache[key] = (
            now + _TRENDS_CACHE_TTL_SECONDS,
            event_token,
            snapshot,
        )
        if len(_trends_snapshot_cache) > 256:
            _trends_snapshot_cache.clear()
        return snapshot


@jobs_stream_router.get("/trends/stream")
async def stream_job_trends(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
    function: str | None = Query(None, description="Filter by function key"),
    func_type: FunctionType | None = Query(None, description="Filter by function type"),
) -> StreamingResponse:
    """Stream realtime job trends snapshots via Server-Sent Events (SSE)."""
    hours_window = hours if isinstance(hours, int) else 24
    function_filter = function if isinstance(function, str) and function else None
    func_type_filter = func_type if isinstance(func_type, FunctionType) else None
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
                    count=200,
                    block=15_000,
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

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
