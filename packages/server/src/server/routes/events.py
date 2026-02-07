"""Event ingestion routes."""

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from shared.events import (
    EVENTS_PUBSUB_CHANNEL,
    BatchEventRequest,
    EventRequest,
)

from server.services.event_processing import process_event
from server.services import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


class EventResponse(BaseModel):
    """Event response."""

    status: str = "ok"
    event_type: str


class BatchEventResponse(BaseModel):
    """Batch event response."""

    status: str = "ok"
    processed: int
    errors: int = 0


@router.get("/stream")
async def stream_events() -> StreamingResponse:
    """Stream job events via Server-Sent Events (SSE)."""
    redis_client = await get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(EVENTS_PUBSUB_CHANNEL)

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            yield "event: open\ndata: connected\n\n"
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=15.0,
                )
                if message and message.get("type") == "message":
                    data = message.get("data")
                    if isinstance(data, bytes):
                        data = data.decode()
                    yield f"data: {data}\n\n"
                else:
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            pass

        finally:
            await pubsub.unsubscribe(EVENTS_PUBSUB_CHANNEL)
            await pubsub.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/", response_model=EventResponse)
async def ingest_event(request: EventRequest) -> EventResponse:
    """
    Ingest a job event from a worker.

    This is the main endpoint workers use to report job status updates.
    Events are persisted to the database for history and dashboard display.
    """
    event_type = request.type
    data = request.data
    worker_id = request.worker_id

    logger.debug(f"Received event: {event_type} from worker {worker_id}")

    applied = await process_event(event_type, data, worker_id)
    if not applied:
        logger.debug("Event ignored: %s (job_id=%s)", event_type, data.get("job_id"))

    return EventResponse(status="ok", event_type=event_type)


@router.post("/batch", response_model=BatchEventResponse)
async def ingest_batch(request: BatchEventRequest) -> BatchEventResponse:
    """
    Ingest a batch of events from a worker.

    This endpoint is used by batched status reporters.
    Events are processed in request order to preserve per-job transitions.
    """
    logger.debug(
        f"Received batch of {len(request.events)} events from worker {request.worker_id}"
    )

    processed = 0
    skipped = 0
    errors = 0

    for event in request.events:
        try:
            data = {**event.data, "job_id": event.job_id}
            applied = await process_event(event.type, data, event.worker_id)
            if applied:
                processed += 1
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            logger.error(f"Error processing batch event {event.type}: {e}")

    if errors > 0:
        logger.warning(
            f"Batch complete: processed={processed}, skipped={skipped}, errors={errors}"
        )
    else:
        logger.debug(f"Batch complete: processed={processed}, skipped={skipped}")

    return BatchEventResponse(status="ok", processed=processed, errors=errors)
