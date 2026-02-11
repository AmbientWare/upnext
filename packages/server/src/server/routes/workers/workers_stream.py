import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from shared.schemas import (
    WorkersSnapshotEvent,
)
from shared.workers import WORKER_EVENTS_STREAM

from server.routes.workers.workers_root import list_workers_route
from server.routes.workers.workers_utils import (
    WORKER_SIGNAL_TYPES,
    parse_worker_signal_type,
)
from server.services import get_redis

logger = logging.getLogger(__name__)

worker_stream_router = APIRouter(tags=["workers"])


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

            initial = await list_workers_route()
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
                for _stream_name, entries in result:
                    for event_id, row in entries:
                        last_id = str(event_id)
                        signal_type = parse_worker_signal_type(row)
                        if signal_type not in WORKER_SIGNAL_TYPES:
                            continue
                        has_updates = True

                if not has_updates:
                    continue

                snapshot = await list_workers_route()
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
