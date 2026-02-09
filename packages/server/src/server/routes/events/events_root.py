"""Event ingestion routes."""

import logging

from fastapi import APIRouter
from shared.events import (
    BatchEventRequest,
    BatchEventResponse,
    EventRequest,
    EventResponse,
)

from server.services.event_processing import process_event

logger = logging.getLogger(__name__)

events_root_router = APIRouter(tags=["events"])


@events_root_router.post("/", response_model=EventResponse)
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


@events_root_router.post("/batch", response_model=BatchEventResponse)
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
