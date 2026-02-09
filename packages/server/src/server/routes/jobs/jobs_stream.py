import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from shared.events import EVENTS_STREAM
from shared.schemas import (
    JobTrendsSnapshotEvent,
)

from server.routes._shared import get_stream_text_field
from server.routes.jobs.jobs_root import get_job_trends
from server.routes.jobs.jobs_utils import (
    TREND_TRIGGER_EVENTS,
    extract_stream_function_key,
)
from server.services import get_redis

logger = logging.getLogger(__name__)

jobs_stream_router = APIRouter(tags=["jobs"])


@jobs_stream_router.get("/trends/stream")
async def stream_job_trends(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
    function: str | None = Query(None, description="Filter by function key"),
    type: str | None = Query(None, description="Filter by function type"),
) -> StreamingResponse:
    """Stream realtime job trends snapshots via Server-Sent Events (SSE)."""
    hours_window = hours if isinstance(hours, int) else 24
    function_filter = function if isinstance(function, str) and function else None
    type_filter = type if isinstance(type, str) and type else None
    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"

            initial = await get_job_trends(
                hours=hours_window,
                function=function_filter,
                type=type_filter,
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
                for _stream_name, entries in result:
                    for event_id, event_data in entries:
                        last_id = str(event_id)
                        event_type = get_stream_text_field(event_data, "type")
                        if event_type not in TREND_TRIGGER_EVENTS:
                            continue
                        if function_filter:
                            event_function = extract_stream_function_key(event_data)
                            if event_function != function_filter:
                                continue
                        has_updates = True

                if not has_updates:
                    continue

                snapshot = await get_job_trends(
                    hours=hours_window,
                    function=function_filter,
                    type=type_filter,
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
