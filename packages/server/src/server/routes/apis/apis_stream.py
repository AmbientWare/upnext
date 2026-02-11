import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from shared.events import API_REQUESTS_STREAM
from shared.schemas import (
    ApiRequestEvent,
    ApiRequestEventsResponse,
    ApiRequestSnapshotEvent,
    ApiSnapshotEvent,
    ApisSnapshotEvent,
    ApiTrendsSnapshotEvent,
)

from server.config import get_settings
from server.routes.apis.apis_root import get_api, get_api_trends, list_apis
from server.routes.apis.apis_utils import parse_api_request_event
from server.services import get_redis

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
                    count=200,
                    block=15_000,
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

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@api_stream_router.get("/events", response_model=ApiRequestEventsResponse)
async def list_api_request_events(
    api_name: str | None = Query(None, description="Optional API name filter"),
    limit: int | None = Query(
        None,
        ge=1,
        le=2000,
        description="Maximum number of recent request events",
    ),
) -> ApiRequestEventsResponse:
    """List recent API request events from the Redis request stream."""
    api_name_filter = api_name if isinstance(api_name, str) and api_name else None
    limit_value = limit if isinstance(limit, int) else None
    try:
        redis_client = await get_redis()
    except RuntimeError:
        return ApiRequestEventsResponse(events=[], total=0)

    default_limit = max(get_settings().api_request_events_default_limit, 1)
    effective_limit = min(max(limit_value or default_limit, 1), 2000)
    read_count = min(max(effective_limit * 4, effective_limit), 5000)

    rows = await redis_client.xrevrange(API_REQUESTS_STREAM, count=read_count)
    events: list[ApiRequestEvent] = []
    for event_id, row in rows:
        parsed = parse_api_request_event(str(event_id), row)
        if parsed is None:
            continue
        if api_name_filter and parsed.api_name != api_name_filter:
            continue
        events.append(parsed)
        if len(events) >= effective_limit:
            break

    return ApiRequestEventsResponse(events=events, total=len(events))


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
                    block=15_000,
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

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
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
                    count=200,
                    block=15_000,
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

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
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
                    count=200,
                    block=15_000,
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

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
