"""Shared event processing logic for job lifecycle updates."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from shared.events import (
    EventType,
    JobCheckpointEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobRetryingEvent,
    JobStartedEvent,
)

from server.db.repository import ArtifactRepository, JobRepository
from server.db.session import get_database

logger = logging.getLogger(__name__)

EventProcessor = Callable[[dict[str, Any], str | None], Awaitable[bool]]


def _as_utc_aware(ts: datetime | None) -> datetime | None:
    """Normalize datetimes to UTC-aware for safe comparison across DB backends."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


async def process_event(
    event_type: str, data: dict[str, Any], worker_id: str | None = None
) -> bool:
    """Process a single event by type."""
    try:
        processor = EVENT_PROCESSORS.get(event_type)
        if processor is None:
            logger.debug("Ignoring event type: %s", event_type)
            return False
        return await processor(data, worker_id)
    except Exception as e:
        logger.error("Error processing event %s: %s", event_type, e)
        raise


async def _promote_pending_artifacts(session: Any, job_id: str) -> None:
    """Promote queued artifacts once the job row exists."""
    artifact_repo = ArtifactRepository(session)
    promoted = await artifact_repo.promote_pending_for_job(job_id)
    if promoted > 0:
        logger.debug("Promoted %d pending artifact(s) for job %s", promoted, job_id)


async def _handle_job_started(
    event: JobStartedEvent, worker_id: str | None = None
) -> bool:
    """Handle job.started event - create or refresh job record."""
    logger.debug(
        "Job started: %s (%s) attempt=%s worker=%s",
        event.job_id,
        event.function,
        event.attempt,
        event.worker_id or worker_id,
    )

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)
            existing = await repo.get_by_id(event.job_id)
            if existing:
                existing_attempts = existing.attempts or 0
                existing_started_at = _as_utc_aware(existing.started_at)
                existing_completed_at = _as_utc_aware(existing.completed_at)
                incoming_started_at = _as_utc_aware(event.started_at)
                is_terminal = existing.status in {"complete", "failed"}
                is_stale_attempt = event.attempt < existing_attempts
                is_duplicate_start = (
                    event.attempt == existing_attempts
                    and existing_started_at is not None
                    and incoming_started_at is not None
                    and incoming_started_at <= existing_started_at
                )
                is_older_than_completion = (
                    existing_completed_at is not None
                    and incoming_started_at is not None
                    and incoming_started_at <= existing_completed_at
                )

                if is_stale_attempt or is_duplicate_start or is_older_than_completion or (
                    is_terminal and event.attempt <= existing_attempts
                ):
                    logger.debug(
                        "Ignoring stale job.started for %s "
                        "(existing=%s/%s completed_at=%s, incoming=%s/%s)",
                        event.job_id,
                        existing.status,
                        existing_attempts,
                        existing_completed_at.isoformat()
                        if existing_completed_at
                        else None,
                        event.attempt,
                        incoming_started_at.isoformat()
                        if incoming_started_at
                        else None,
                    )
                    return False

                existing.status = "active"
                existing.attempts = max(existing_attempts, event.attempt)
                existing.worker_id = event.worker_id or worker_id
                existing.started_at = event.started_at
                existing.completed_at = None
                existing.progress = 0.0
                existing.error = None
                existing.result = None
            else:
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

            await session.flush()
            await _promote_pending_artifacts(session, event.job_id)
        return True
    except RuntimeError:
        logger.debug("Database not available, skipping job persistence")
        return True


async def _handle_job_completed(event: JobCompletedEvent) -> None:
    """Handle job.completed event - update job with success."""
    logger.debug(
        "Job completed: %s (%s) duration=%sms",
        event.job_id,
        event.function,
        event.duration_ms,
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

            await session.flush()
            await _promote_pending_artifacts(session, event.job_id)
    except RuntimeError:
        logger.debug("Database not available, skipping job persistence")


async def _handle_job_failed(event: JobFailedEvent) -> None:
    """Handle job.failed event - update job with failure."""
    logger.debug(
        "Job failed: %s (%s) error=%s will_retry=%s",
        event.job_id,
        event.function,
        event.error[:100],
        event.will_retry,
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

            await session.flush()
            await _promote_pending_artifacts(session, event.job_id)
    except RuntimeError:
        logger.debug("Database not available, skipping job persistence")


async def _handle_job_retrying(event: JobRetryingEvent) -> None:
    """Handle job.retrying event - update job with retry status."""
    logger.debug(
        "Job retrying: %s (%s) attempt %s -> %s delay=%ss",
        event.job_id,
        event.function,
        event.current_attempt,
        event.next_attempt,
        event.delay_seconds,
    )

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            existing = await repo.get_by_id(event.job_id)
            if existing:
                existing.status = "retrying"
                existing.attempts = event.current_attempt
                existing.error = event.error
                await session.flush()
                await _promote_pending_artifacts(session, event.job_id)
    except RuntimeError:
        logger.debug("Database not available, skipping job persistence")


async def _handle_job_progress(event: JobProgressEvent) -> None:
    """Handle job.progress event - update progress."""
    logger.debug(
        "Job progress: %s progress=%.1f%% message=%s",
        event.job_id,
        event.progress * 100,
        event.message,
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
        "Job checkpoint: %s state_keys=%s", event.job_id, list(event.state.keys())
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


async def _process_job_started(
    data: dict[str, Any], worker_id: str | None
) -> bool:
    return await _handle_job_started(JobStartedEvent(**data), worker_id)


async def _process_job_completed(
    data: dict[str, Any], _: str | None
) -> bool:
    await _handle_job_completed(JobCompletedEvent(**data))
    return True


async def _process_job_failed(
    data: dict[str, Any], _: str | None
) -> bool:
    await _handle_job_failed(JobFailedEvent(**data))
    return True


async def _process_job_retrying(
    data: dict[str, Any], _: str | None
) -> bool:
    await _handle_job_retrying(JobRetryingEvent(**data))
    return True


async def _process_job_progress(
    data: dict[str, Any], _: str | None
) -> bool:
    await _handle_job_progress(JobProgressEvent(**data))
    return True


async def _process_job_checkpoint(
    data: dict[str, Any], _: str | None
) -> bool:
    await _handle_job_checkpoint(JobCheckpointEvent(**data))
    return True


EVENT_PROCESSORS: dict[str, EventProcessor] = {
    EventType.JOB_STARTED: _process_job_started,
    EventType.JOB_COMPLETED: _process_job_completed,
    EventType.JOB_FAILED: _process_job_failed,
    EventType.JOB_RETRYING: _process_job_retrying,
    EventType.JOB_PROGRESS: _process_job_progress,
    EventType.JOB_CHECKPOINT: _process_job_checkpoint,
}
