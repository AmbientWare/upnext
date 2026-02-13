import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from shared.contracts import WorkersSnapshotEvent
from shared.keys import WORKER_EVENTS_STREAM

from server.routes.workers.workers_root import list_workers_route
from server.routes.workers.workers_utils import (
    STREAMABLE_WORKER_EVENTS,
    parse_worker_signal_type,
)
from server.services.redis import get_redis

logger = logging.getLogger(__name__)

worker_stream_router = APIRouter(tags=["workers"])
_WORKERS_CACHE_LOCK = asyncio.Lock()
_WORKERS_CACHE_TTL_SECONDS = 0.75
_workers_snapshot_cache: tuple[float, str | None, int, Any] | None = None


async def _get_cached_workers_snapshot(*, event_token: str | None = None) -> Any:
    global _workers_snapshot_cache
    now = asyncio.get_running_loop().time()
    cached = _workers_snapshot_cache
    provider_id = id(list_workers_route)
    if cached and cached[0] > now:
        if cached[2] == provider_id and (
            event_token is None or cached[1] == event_token
        ):
            return cached[3]

    async with _WORKERS_CACHE_LOCK:
        cached = _workers_snapshot_cache
        if cached and cached[0] > now:
            if cached[2] == provider_id and (
                event_token is None or cached[1] == event_token
            ):
                return cached[3]
        snapshot = await list_workers_route()
        _workers_snapshot_cache = (
            now + _WORKERS_CACHE_TTL_SECONDS,
            event_token,
            provider_id,
            snapshot,
        )
        return snapshot


@worker_stream_router.get("/stream")
async def stream_workers(request: Request) -> StreamingResponse:
    """Stream realtime workers list snapshots via Server-Sent Events (SSE)."""
    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"

            initial = await _get_cached_workers_snapshot()
            initial_event = WorkersSnapshotEvent(
                at=datetime.now(UTC).isoformat(),
                workers=initial,
            )
            yield f"data: {initial_event.model_dump_json()}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                result = await redis_client.xread(
                    {WORKER_EVENTS_STREAM: last_id},
                    count=200,
                    block=15_000,
                )
                if not result:
                    yield ": keep-alive\n\n"
                    continue

                has_updates = False
                latest_relevant_event_id: str | None = None
                for _stream_name, entries in result:
                    for event_id, row in entries:
                        last_id = str(event_id)
                        signal_type = parse_worker_signal_type(row)
                        if signal_type not in STREAMABLE_WORKER_EVENTS:
                            continue
                        has_updates = True
                        latest_relevant_event_id = str(event_id)

                if not has_updates:
                    continue

                snapshot = await _get_cached_workers_snapshot(
                    event_token=latest_relevant_event_id
                )
                event = WorkersSnapshotEvent(
                    at=datetime.now(UTC).isoformat(),
                    workers=snapshot,
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
