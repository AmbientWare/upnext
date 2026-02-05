"""Event ingestion routes."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from shared.events import (
    BatchEventRequest,
    EventRequest,
    EventType,
    JobCheckpointEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobRetryingEvent,
    JobStartedEvent,
)

from server.db.repository import JobRepository
from server.db.session import get_database

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

    await _process_event(event_type, data, worker_id)

    return EventResponse(status="ok", event_type=event_type)


@router.post("/batch", response_model=BatchEventResponse)
async def ingest_batch(request: BatchEventRequest) -> BatchEventResponse:
    """
    Ingest a batch of events from a worker.

    This endpoint is used by StatusPublisher for efficient batched reporting.
    Multiple events are processed concurrently for high throughput.
    """
    logger.debug(
        f"Received batch of {len(request.events)} events from worker {request.worker_id}"
    )

    async def process_one(event: Any) -> bool:
        """Process a single event, return True on success."""
        try:
            data = {"job_id": event.job_id, **event.data}
            await _process_event(event.type, data, event.worker_id)
            return True
        except Exception as e:
            logger.error(f"Error processing batch event {event.type}: {e}")
            return False

    # Process all events concurrently
    results = await asyncio.gather(*[process_one(e) for e in request.events])
    processed = sum(results)
    errors = len(results) - processed

    if errors > 0:
        logger.warning(f"Batch complete: processed={processed}, errors={errors}")
    else:
        logger.debug(f"Batch complete: processed={processed}")

    return BatchEventResponse(status="ok", processed=processed, errors=errors)


async def _process_event(
    event_type: str, data: dict[str, Any], worker_id: str | None = None
) -> None:
    """Process a single event by type."""
    try:
        if event_type == EventType.JOB_STARTED:
            await _handle_job_started(JobStartedEvent(**data), worker_id)
        elif event_type == EventType.JOB_COMPLETED:
            await _handle_job_completed(JobCompletedEvent(**data))
        elif event_type == EventType.JOB_FAILED:
            await _handle_job_failed(JobFailedEvent(**data))
        elif event_type == EventType.JOB_RETRYING:
            await _handle_job_retrying(JobRetryingEvent(**data))
        elif event_type == EventType.JOB_PROGRESS:
            await _handle_job_progress(JobProgressEvent(**data))
        elif event_type == EventType.JOB_CHECKPOINT:
            await _handle_job_checkpoint(JobCheckpointEvent(**data))
        else:
            logger.debug(f"Ignoring event type: {event_type}")

    except Exception as e:
        logger.error(f"Error processing event {event_type}: {e}")
        # Don't fail the request - workers shouldn't be blocked by API errors
        raise


async def _handle_job_started(
    event: JobStartedEvent, worker_id: str | None = None
) -> None:
    """Handle job.started event - create job record."""
    logger.debug(
        f"Job started: {event.job_id} ({event.function}) "
        f"attempt={event.attempt} worker={event.worker_id or worker_id}"
    )

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            # Check if job already exists (retry case)
            existing = await repo.get_by_id(event.job_id)
            if existing:
                # Update existing job for retry
                existing.status = "active"
                existing.attempts = event.attempt
                existing.worker_id = event.worker_id or worker_id
                existing.started_at = event.started_at
            else:
                # Create new job record
                await repo.record_job(
                    {
                        "job_id": event.job_id,
                        "function": event.function,
                        "status": "active",
                        "kwargs": event.kwargs,
                        "attempts": event.attempt,
                        "max_retries": event.max_retries,
                        "worker_id": event.worker_id or worker_id,
                        "started_at": event.started_at,
                        "created_at": event.started_at,
                    }
                )
    except RuntimeError:
        # Database not initialized - skip persistence
        logger.debug("Database not available, skipping job persistence")


async def _handle_job_completed(event: JobCompletedEvent) -> None:
    """Handle job.completed event - update job with success."""
    logger.debug(
        f"Job completed: {event.job_id} ({event.function}) "
        f"duration={event.duration_ms}ms"
    )

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            existing = await repo.get_by_id(event.job_id)
            if existing:
                existing.status = "complete"
                existing.result = event.result
                existing.completed_at = event.completed_at
                existing.progress = 1.0
            else:
                # Job not found - create completed record
                await repo.record_job(
                    {
                        "job_id": event.job_id,
                        "function": event.function,
                        "status": "complete",
                        "result": event.result,
                        "completed_at": event.completed_at,
                        "attempts": event.attempt,
                        "progress": 1.0,
                    }
                )
    except RuntimeError:
        logger.debug("Database not available, skipping job persistence")


async def _handle_job_failed(event: JobFailedEvent) -> None:
    """Handle job.failed event - update job with failure."""
    logger.debug(
        f"Job failed: {event.job_id} ({event.function}) "
        f"error={event.error[:100]} will_retry={event.will_retry}"
    )

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            existing = await repo.get_by_id(event.job_id)
            if existing:
                existing.status = "failed"
                existing.error = event.error
                existing.completed_at = event.failed_at
            else:
                await repo.record_job(
                    {
                        "job_id": event.job_id,
                        "function": event.function,
                        "status": "failed",
                        "error": event.error,
                        "completed_at": event.failed_at,
                        "attempts": event.attempt,
                        "max_retries": event.max_retries,
                    }
                )
    except RuntimeError:
        logger.debug("Database not available, skipping job persistence")


async def _handle_job_retrying(event: JobRetryingEvent) -> None:
    """Handle job.retrying event - update job with retry status."""
    logger.debug(
        f"Job retrying: {event.job_id} ({event.function}) "
        f"attempt {event.current_attempt} -> {event.next_attempt} "
        f"delay={event.delay_seconds}s"
    )

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            existing = await repo.get_by_id(event.job_id)
            if existing:
                existing.status = "retrying"
                existing.attempts = event.current_attempt
                existing.error = event.error  # Store last error
    except RuntimeError:
        logger.debug("Database not available, skipping job persistence")


async def _handle_job_progress(event: JobProgressEvent) -> None:
    """Handle job.progress event - update progress."""
    logger.debug(
        f"Job progress: {event.job_id} "
        f"progress={event.progress:.1%} message={event.message}"
    )

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            existing = await repo.get_by_id(event.job_id)
            if existing:
                existing.progress = event.progress
    except RuntimeError:
        logger.debug("Database not available, skipping job persistence")


async def _handle_job_checkpoint(event: JobCheckpointEvent) -> None:
    """Handle job.checkpoint event - store checkpoint state."""
    logger.debug(
        f"Job checkpoint: {event.job_id} state_keys={list(event.state.keys())}"
    )

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            existing = await repo.get_by_id(event.job_id)
            if existing:
                existing.metadata_["checkpoint"] = event.state
                existing.metadata_["checkpoint_at"] = event.checkpointed_at.isoformat()
    except RuntimeError:
        logger.debug("Database not available, skipping checkpoint persistence")
