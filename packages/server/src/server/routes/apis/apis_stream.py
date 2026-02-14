import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from shared.contracts import (
    ApiRequestEvent,
    ApiRequestEventsResponse,
    ApiRequestSnapshotEvent,
    ApiSnapshotEvent,
    ApisSnapshotEvent,
    ApiTrendsSnapshotEvent,
)
from shared.keys import API_REQUESTS_STREAM

from server.config import get_settings
from server.routes.apis.apis_root import get_api, get_api_trends, list_apis
from server.routes.apis.apis_utils import parse_api_request_event
from server.services.apis.request_events import (
    iter_api_request_rows,
    stream_id_ceil,
    stream_id_floor,
)
from server.routes.sse import SSE_BLOCK_MS, SSE_HEADERS, SSE_READ_COUNT
from server.services.redis import get_redis

logger = logging.getLogger(__name__)

api_stream_router = APIRouter(tags=["apis"])


@api_stream_router.get("/trends/stream")
async def stream_api_trends(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
) -> StreamingResponse:
    """Stream realtime API trends snapshots via Server-Sent Events (SSE)."""
    hours_window = hours if isinstance(hours, int) else 24

    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"

            initial = await get_api_trends(hours=hours_window)
            initial_event = ApiTrendsSnapshotEvent(
                at=datetime.now(UTC).isoformat(),
                trends=initial,
            )
            yield f"data: {initial_event.model_dump_json()}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                result = await redis_client.xread(
                    {API_REQUESTS_STREAM: last_id},
                    count=SSE_READ_COUNT,
                    block=SSE_BLOCK_MS,
                )
                if not result:
                    yield ": keep-alive\n\n"
                    continue

                has_updates = False
                for _stream_name, entries in result:
                    for event_id, row in entries:
                        event_id_str = str(event_id)
                        last_id = event_id_str
                        if parse_api_request_event(event_id_str, row) is None:
                            continue
                        has_updates = True

                if not has_updates:
                    continue

                snapshot = await get_api_trends(hours=hours_window)
                event = ApiTrendsSnapshotEvent(
                    at=datetime.now(UTC).isoformat(),
                    trends=snapshot,
                )
                yield f"data: {event.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("API trends stream error: %s", exc)
            yield 'event: error\ndata: {"error": "stream disconnected"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@api_stream_router.get("/events", response_model=ApiRequestEventsResponse)
async def list_api_request_events(
    api_name: str | None = Query(None, description="Optional API name filter"),
    method: str | None = Query(None, description="Optional HTTP method filter"),
    path: str | None = Query(None, description="Optional API path filter"),
    status: int | None = Query(None, description="Optional status code filter"),
    instance_id: str | None = Query(None, description="Optional instance filter"),
    after: datetime | None = Query(None, description="Filter by event time after"),
    before: datetime | None = Query(None, description="Filter by event time before"),
    limit: int | None = Query(
        None,
        ge=1,
        le=2000,
        description="Maximum number of recent request events",
    ),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> ApiRequestEventsResponse:
    """List recent API request events from the Redis request stream."""
    api_name_filter = api_name if isinstance(api_name, str) and api_name else None
    method_filter = method.upper() if isinstance(method, str) and method else None
    path_filter = path if isinstance(path, str) and path else None
    status_filter = status if isinstance(status, int) else None
    instance_filter = (
        instance_id if isinstance(instance_id, str) and instance_id else None
    )
    after_filter = after if isinstance(after, datetime) else None
    before_filter = before if isinstance(before, datetime) else None
    limit_value = limit if isinstance(limit, int) else None
    offset_value = offset if isinstance(offset, int) else 0
    try:
        redis_client = await get_redis()
    except RuntimeError:
        return ApiRequestEventsResponse(events=[], total=0, has_more=False)

    default_limit = max(get_settings().api_request_events_default_limit, 1)
    effective_limit = min(max(limit_value or default_limit, 1), 2000)
    effective_offset = max(offset_value, 0)
    read_count = min(max(effective_limit * 4, 500), 5000)
    max_id = stream_id_ceil(before_filter) if before_filter is not None else "+"
    min_id = stream_id_floor(after_filter) if after_filter is not None else "-"

    events: list[ApiRequestEvent] = []
    total_matching = 0

    async for event_id, row in iter_api_request_rows(
        redis_client,
        max_id=max_id,
        min_id=min_id,
        count=read_count,
    ):
        parsed = parse_api_request_event(event_id, row)
        if parsed is None:
            continue
        if api_name_filter and parsed.api_name != api_name_filter:
            continue
        if method_filter and parsed.method != method_filter:
            continue
        if path_filter and parsed.path != path_filter:
            continue
        if status_filter is not None and parsed.status != status_filter:
            continue
        if instance_filter:
            if instance_filter == "__none__":
                if parsed.instance_id:
                    continue
            elif parsed.instance_id != instance_filter:
                continue

        total_matching += 1
        if total_matching <= effective_offset:
            continue
        if len(events) < effective_limit:
            events.append(parsed)

    has_more = (effective_offset + len(events)) < total_matching
    return ApiRequestEventsResponse(
        events=events, total=total_matching, has_more=has_more
    )


@api_stream_router.get("/events/stream")
async def stream_api_request_events(
    request: Request,
    api_name: str | None = Query(None, description="Optional API name filter"),
) -> StreamingResponse:
    """Stream realtime API request events via Server-Sent Events (SSE)."""
    api_name_filter = api_name if isinstance(api_name, str) and api_name else None

    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"
            while True:
                if await request.is_disconnected():
                    break

                result = await redis_client.xread(
                    {API_REQUESTS_STREAM: last_id},
                    count=100,
                    block=SSE_BLOCK_MS,
                )
                if not result:
                    yield ": keep-alive\n\n"
                    continue

                for _stream_name, entries in result:
                    for event_id, row in entries:
                        event_id_str = str(event_id)
                        last_id = event_id_str
                        parsed = parse_api_request_event(event_id_str, row)
                        if parsed is None:
                            continue
                        if api_name_filter and parsed.api_name != api_name_filter:
                            continue

                        payload = ApiRequestSnapshotEvent(at=parsed.at, request=parsed)
                        yield f"data: {payload.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("API request events stream error: %s", exc)
            yield 'event: error\ndata: {"error": "stream disconnected"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@api_stream_router.get("/stream")
async def stream_apis(request: Request) -> StreamingResponse:
    """Stream realtime API list snapshots via Server-Sent Events (SSE)."""
    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"

            initial = await list_apis()
            initial_event = ApisSnapshotEvent(
                at=datetime.now(UTC).isoformat(),
                apis=initial,
            )
            yield f"data: {initial_event.model_dump_json()}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                result = await redis_client.xread(
                    {API_REQUESTS_STREAM: last_id},
                    count=SSE_READ_COUNT,
                    block=SSE_BLOCK_MS,
                )
                if not result:
                    yield ": keep-alive\n\n"
                    continue

                has_updates = False
                for _stream_name, entries in result:
                    for event_id, row in entries:
                        last_id = str(event_id)
                        if parse_api_request_event(last_id, row) is None:
                            continue
                        has_updates = True

                if not has_updates:
                    continue

                snapshot = await list_apis()
                event = ApisSnapshotEvent(
                    at=datetime.now(UTC).isoformat(),
                    apis=snapshot,
                )
                yield f"data: {event.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("APIs list stream error: %s", exc)
            yield 'event: error\ndata: {"error": "stream disconnected"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@api_stream_router.get("/{api_name}/stream")
async def stream_api(api_name: str, request: Request) -> StreamingResponse:
    """Stream realtime snapshot for a single API via SSE."""
    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"

            initial = await get_api(api_name)
            initial_event = ApiSnapshotEvent(
                at=datetime.now(UTC).isoformat(),
                api=initial,
            )
            yield f"data: {initial_event.model_dump_json()}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                result = await redis_client.xread(
                    {API_REQUESTS_STREAM: last_id},
                    count=SSE_READ_COUNT,
                    block=SSE_BLOCK_MS,
                )
                if not result:
                    yield ": keep-alive\n\n"
                    continue

                has_updates = False
                for _stream_name, entries in result:
                    for event_id, row in entries:
                        event_id_str = str(event_id)
                        last_id = event_id_str
                        parsed = parse_api_request_event(event_id_str, row)
                        if parsed is None:
                            continue
                        if parsed.api_name != api_name:
                            continue
                        has_updates = True

                if not has_updates:
                    continue

                snapshot = await get_api(api_name)
                event = ApiSnapshotEvent(
                    at=datetime.now(UTC).isoformat(),
                    api=snapshot,
                )
                yield f"data: {event.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("API detail stream error: %s", exc)
            yield 'event: error\ndata: {"error": "stream disconnected"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
