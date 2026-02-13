"""Shared event processing logic for job lifecycle updates."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias

from shared.contracts import (
    ArtifactResponse,
    ArtifactStreamEvent,
    CronJobSource,
    EventJobSource,
    JobCheckpointEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobRetryingEvent,
    JobSource,
    JobStartedEvent,
)
from shared.domain import JobType
from shared.keys import ARTIFACT_EVENTS_STREAM
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import get_settings
from server.db.repositories import ArtifactRepository, JobRecordCreate, JobRepository
from server.db.session import get_database
from server.services.redis import get_redis
from server.shared_utils import as_utc_aware

logger = logging.getLogger(__name__)

JobLifecycleEvent: TypeAlias = (
    JobStartedEvent
    | JobCompletedEvent
    | JobFailedEvent
    | JobRetryingEvent
    | JobProgressEvent
    | JobCheckpointEvent
)

TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled"})


@dataclass
class _ProgressWriteState:
    progress: float
    written_at_monotonic: float


@dataclass(frozen=True)
class _SourceColumns:
    job_type: JobType
    schedule: str | None = None
    cron_window_at: float | None = None
    startup_reconciled: bool = False
    startup_policy: str | None = None
    event_pattern: str | None = None
    event_handler_name: str | None = None


_progress_write_state: dict[str, _ProgressWriteState] = {}


def _record_progress_write(job_id: str, progress: float) -> None:
    max_entries = max(get_settings().event_progress_state_max_entries, 0)
    if (
        max_entries > 0
        and job_id not in _progress_write_state
        and len(_progress_write_state) >= max_entries
    ):
        # Keep cache size bounded on long-lived servers.
        _progress_write_state.pop(next(iter(_progress_write_state)))
    _progress_write_state[job_id] = _ProgressWriteState(
        progress=progress,
        written_at_monotonic=time.monotonic(),
    )


def _should_persist_progress(job_id: str, progress: float) -> bool:
    settings = get_settings()
    min_interval = max(settings.event_progress_min_interval_ms, 0) / 1000
    min_delta = max(settings.event_progress_min_delta, 0.0)
    force_interval = max(settings.event_progress_force_interval_ms, 0) / 1000

    state = _progress_write_state.get(job_id)
    if state is None:
        return True

    now = time.monotonic()
    elapsed = now - state.written_at_monotonic
    delta = abs(progress - state.progress)

    if progress >= 1.0:
        return True
    if force_interval > 0 and elapsed >= force_interval:
        return True
    if delta >= min_delta:
        return True
    if min_delta <= 0 and elapsed >= min_interval:
        return True
    return False


def _source_columns(source: JobSource) -> _SourceColumns:
    """Map typed source payload to persisted typed columns."""
    # Cron jobs
    if isinstance(source, CronJobSource):
        return _SourceColumns(
            job_type=JobType.CRON,
            schedule=source.schedule,
            cron_window_at=source.cron_window_at,
            startup_reconciled=source.startup_reconciled,
            startup_policy=source.startup_policy,
        )

    # Event jobs
    if isinstance(source, EventJobSource):
        return _SourceColumns(
            job_type=JobType.EVENT,
            event_pattern=source.event_pattern,
            event_handler_name=source.event_handler_name,
        )

    # Task jobs
    return _SourceColumns(job_type=JobType.TASK)


async def process_event(
    event: JobLifecycleEvent,
    *,
    session: AsyncSession | None = None,
) -> bool:
    """Dispatch one typed lifecycle event and return whether it changed persisted state."""
    if isinstance(event, JobStartedEvent):
        return await _handle_job_started(event, session=session)
    if isinstance(event, JobCompletedEvent):
        return await _handle_job_completed(event, session=session)
    if isinstance(event, JobFailedEvent):
        return await _handle_job_failed(event, session=session)
    if isinstance(event, JobRetryingEvent):
        return await _handle_job_retrying(event, session=session)
    if isinstance(event, JobProgressEvent):
        return await _handle_job_progress(event, session=session)
    if isinstance(event, JobCheckpointEvent):
        return await _handle_job_checkpoint(event, session=session)
    logger.warning("Unsupported lifecycle event type: %s", type(event).__name__)
    return False


async def _promote_pending_artifacts(session: AsyncSession, job_id: str) -> None:
    """Promote queued artifacts once the job row exists."""
    artifact_repo = ArtifactRepository(session)
    promoted = await artifact_repo.promote_pending_for_job_with_artifacts(job_id)
    if promoted:
        logger.debug(
            "Promoted %d pending artifact(s) for job %s", len(promoted), job_id
        )
    for artifact in promoted:
        await _publish_artifact_event(
            ArtifactStreamEvent(
                type="artifact.promoted",
                at=datetime.now(UTC).isoformat(),
                job_id=artifact.job_id,
                artifact_id=artifact.id,
                pending_id=None,
                artifact=ArtifactResponse.model_validate(artifact),
            )
        )


async def _publish_artifact_event(event: ArtifactStreamEvent) -> None:
    """Publish artifact lifecycle updates for realtime UI consumers."""
    try:
        redis_client = await get_redis()
    except RuntimeError:
        return
    try:
        await redis_client.xadd(
            ARTIFACT_EVENTS_STREAM,
            {"data": event.model_dump_json()},
            maxlen=10_000,
            approximate=True,
        )
    except Exception as exc:  # pragma: no cover - best effort path
        logger.debug("Failed publishing artifact event: %s", exc)


async def _handle_job_started(
    event: JobStartedEvent,
    *,
    session: AsyncSession | None = None,
) -> bool:
    """Handle job.started event - create or refresh job record."""
    logger.debug(
        "Job started: %s (%s) attempt=%s worker=%s",
        event.job_id,
        event.function_name,
        event.attempt,
        event.worker_id,
    )

    if session is None:
        db = get_database()
        async with db.session() as managed_session:
            return await _handle_job_started(event, session=managed_session)

    repo = JobRepository(session)
    existing = await repo.get_by_id(event.job_id)
    parent_id = event.parent_id
    root_id = event.root_id
    queue_wait_ms = event.queue_wait_ms
    source_columns = _source_columns(event.source)

    if existing:
        existing_attempts = existing.attempts or 0
        existing_started_at = as_utc_aware(existing.started_at)
        existing_completed_at = as_utc_aware(existing.completed_at)
        incoming_started_at = as_utc_aware(event.started_at)
        if event.attempt < existing_attempts:
            return False
        if (
            existing.status in {"complete", "failed"}
            and event.attempt <= existing_attempts
        ):
            return False
        if (
            existing_completed_at
            and incoming_started_at
            and incoming_started_at <= existing_completed_at
        ):
            return False
        if (
            event.attempt == existing_attempts
            and existing_started_at
            and incoming_started_at
            and incoming_started_at <= existing_started_at
        ):
            return False
        existing.status = "active"
        existing.function = event.function
        existing.function_name = event.function_name
        existing.attempts = max(existing_attempts, event.attempt)
        existing.worker_id = event.worker_id
        existing.parent_id = parent_id
        existing.root_id = root_id
        existing.job_type = source_columns.job_type.value
        existing.started_at = event.started_at
        existing.scheduled_at = event.scheduled_at
        existing.queue_wait_ms = queue_wait_ms
        existing.schedule = source_columns.schedule
        existing.completed_at = None
        existing.progress = 0.0
        existing.error = None
        existing.result = None
        existing.cron_window_at = source_columns.cron_window_at
        existing.startup_reconciled = source_columns.startup_reconciled
        existing.startup_policy = source_columns.startup_policy
        existing.checkpoint = event.checkpoint
        existing.checkpoint_at = event.checkpoint_at
        existing.dlq_replayed_from = event.dlq_replayed_from
        existing.dlq_failed_at = event.dlq_failed_at
        existing.event_pattern = source_columns.event_pattern
        existing.event_handler_name = source_columns.event_handler_name
    else:
        await repo.record_job(
            JobRecordCreate(
                id=event.job_id,
                function=event.function,
                function_name=event.function_name,
                job_type=source_columns.job_type,
                status="active",
                kwargs=event.kwargs,
                schedule=source_columns.schedule,
                attempts=event.attempt,
                max_retries=event.max_retries,
                worker_id=event.worker_id,
                parent_id=parent_id,
                root_id=root_id,
                scheduled_at=event.scheduled_at,
                queue_wait_ms=queue_wait_ms,
                started_at=event.started_at,
                created_at=event.started_at,
                cron_window_at=source_columns.cron_window_at,
                startup_reconciled=source_columns.startup_reconciled,
                startup_policy=source_columns.startup_policy,
                checkpoint=event.checkpoint,
                checkpoint_at=event.checkpoint_at,
                dlq_replayed_from=event.dlq_replayed_from,
                dlq_failed_at=event.dlq_failed_at,
                event_pattern=source_columns.event_pattern,
                event_handler_name=source_columns.event_handler_name,
            )
        )

    await session.flush()
    await _promote_pending_artifacts(session, event.job_id)
    _record_progress_write(event.job_id, 0.0)
    return True


async def _handle_job_completed(
    event: JobCompletedEvent,
    *,
    session: AsyncSession | None = None,
) -> bool:
    """Handle job.completed event - update job with success."""
    logger.debug(
        "Job completed: %s (%s) duration=%sms",
        event.job_id,
        event.function_name,
        event.duration_ms,
    )

    if session is None:
        db = get_database()
        async with db.session() as managed_session:
            return await _handle_job_completed(event, session=managed_session)

    repo = JobRepository(session)
    existing = await repo.get_by_id(event.job_id)
    if existing:
        existing_attempts = existing.attempts or 0
        existing_completed_at = as_utc_aware(existing.completed_at)
        incoming_completed_at = as_utc_aware(event.completed_at)
        if event.attempt < existing_attempts:
            return False
        if (
            existing.status in TERMINAL_STATUSES
            and existing_completed_at
            and incoming_completed_at
            and incoming_completed_at <= existing_completed_at
        ):
            return False
        existing.status = "complete"
        existing.function = event.function
        existing.function_name = event.function_name
        existing.result = event.result
        existing.completed_at = event.completed_at
        existing.attempts = max(existing_attempts, event.attempt)
        existing.parent_id = event.parent_id
        existing.root_id = event.root_id
        existing.progress = 1.0
        if existing.created_at is None:
            existing.created_at = existing.started_at or event.completed_at
    else:
        await repo.record_job(
            JobRecordCreate(
                id=event.job_id,
                function=event.function,
                function_name=event.function_name,
                status="complete",
                created_at=event.completed_at,
                result=event.result,
                completed_at=event.completed_at,
                attempts=event.attempt,
                parent_id=event.parent_id,
                root_id=event.root_id,
                progress=1.0,
            )
        )

    await session.flush()
    await _promote_pending_artifacts(session, event.job_id)
    _progress_write_state.pop(event.job_id, None)
    return True


async def _handle_job_failed(
    event: JobFailedEvent,
    *,
    session: AsyncSession | None = None,
) -> bool:
    """Handle job.failed event - update job with failure."""
    logger.debug(
        "Job failed: %s (%s) error=%s will_retry=%s",
        event.job_id,
        event.function_name,
        event.error[:100],
        event.will_retry,
    )

    applied_terminal_state = False
    try:
        if session is None:
            db = get_database()
            async with db.session() as managed_session:
                return await _handle_job_failed(event, session=managed_session)

        repo = JobRepository(session)
        existing = await repo.get_by_id(event.job_id)
        if existing:
            existing_attempts = existing.attempts or 0
            existing_completed_at = as_utc_aware(existing.completed_at)
            incoming_failed_at = as_utc_aware(event.failed_at)
            if event.attempt < existing_attempts:
                return False
            if (
                existing.status in {"complete", "failed"}
                and existing_completed_at
                and incoming_failed_at
                and incoming_failed_at <= existing_completed_at
            ):
                return False
            existing.status = "failed"
            existing.function = event.function
            existing.function_name = event.function_name
            existing.error = event.error
            existing.completed_at = event.failed_at
            existing.attempts = max(existing_attempts, event.attempt)
            existing.max_retries = max(existing.max_retries or 0, event.max_retries)
            existing.parent_id = event.parent_id
            existing.root_id = event.root_id
            if existing.created_at is None:
                existing.created_at = existing.started_at or event.failed_at
            applied_terminal_state = True
        else:
            await repo.record_job(
                JobRecordCreate(
                    id=event.job_id,
                    function=event.function,
                    function_name=event.function_name,
                    status="failed",
                    created_at=event.failed_at,
                    error=event.error,
                    completed_at=event.failed_at,
                    attempts=event.attempt,
                    max_retries=event.max_retries,
                    parent_id=event.parent_id,
                    root_id=event.root_id,
                )
            )
            applied_terminal_state = True

        await session.flush()
        await _promote_pending_artifacts(session, event.job_id)
        return True
    finally:
        if applied_terminal_state:
            _progress_write_state.pop(event.job_id, None)


async def _handle_job_retrying(
    event: JobRetryingEvent,
    *,
    session: AsyncSession | None = None,
) -> bool:
    """Handle job.retrying event - update job with retry status."""
    logger.debug(
        "Job retrying: %s (%s) attempt %s -> %s delay=%ss",
        event.job_id,
        event.function_name,
        event.current_attempt,
        event.next_attempt,
        event.delay_seconds,
    )

    if session is None:
        db = get_database()
        async with db.session() as managed_session:
            return await _handle_job_retrying(event, session=managed_session)

    repo = JobRepository(session)
    existing = await repo.get_by_id(event.job_id)
    if existing:
        existing_attempts = existing.attempts or 0
        existing_completed_at = as_utc_aware(existing.completed_at)
        incoming_retry_at = as_utc_aware(event.retry_at)
        if event.current_attempt < existing_attempts:
            return False
        if (
            existing.status in TERMINAL_STATUSES
            and existing_completed_at
            and incoming_retry_at
            and incoming_retry_at <= existing_completed_at
        ):
            return False
        if existing.status == "retrying" and event.current_attempt <= existing_attempts:
            return False
        existing.status = "retrying"
        existing.function = event.function
        existing.function_name = event.function_name
        existing.attempts = max(existing_attempts, event.current_attempt)
        existing.error = event.error
        existing.parent_id = event.parent_id
        existing.root_id = event.root_id
        if existing.created_at is None:
            existing.created_at = existing.started_at or event.retry_at
        await session.flush()
        return True
    return False


async def _handle_job_progress(
    event: JobProgressEvent,
    *,
    session: AsyncSession | None = None,
) -> bool:
    """Handle job.progress event - update progress."""
    logger.debug(
        "Job progress: %s progress=%.1f%% message=%s",
        event.job_id,
        event.progress * 100,
        event.message,
    )

    if not _should_persist_progress(event.job_id, event.progress):
        logger.debug(
            "Coalescing job.progress write for %s (progress=%.3f)",
            event.job_id,
            event.progress,
        )
        return False

    updated = False
    if session is None:
        db = get_database()
        async with db.session() as managed_session:
            return await _handle_job_progress(event, session=managed_session)

    repo = JobRepository(session)
    existing = await repo.get_by_id(event.job_id)
    if existing:
        if existing.status in TERMINAL_STATUSES:
            logger.debug(
                "Ignoring job.progress for terminal job %s (status=%s)",
                event.job_id,
                existing.status,
            )
            _progress_write_state.pop(event.job_id, None)
            return False
        existing.progress = event.progress
        existing.parent_id = event.parent_id
        existing.root_id = event.root_id
        updated = True
    else:
        logger.debug(
            "Ignoring job.progress for unknown job %s",
            event.job_id,
        )
        return False
    if updated:
        _record_progress_write(event.job_id, event.progress)
    return updated


async def _handle_job_checkpoint(
    event: JobCheckpointEvent,
    *,
    session: AsyncSession | None = None,
) -> bool:
    """Handle job.checkpoint event - store checkpoint state."""
    logger.debug(
        "Job checkpoint: %s state_keys=%s", event.job_id, list(event.state.keys())
    )

    if session is None:
        db = get_database()
        async with db.session() as managed_session:
            return await _handle_job_checkpoint(event, session=managed_session)

    repo = JobRepository(session)
    existing = await repo.get_by_id(event.job_id)
    if existing:
        existing.checkpoint = event.state
        existing.checkpoint_at = event.checkpointed_at.isoformat()
        existing.parent_id = event.parent_id
        existing.root_id = event.root_id
        await session.flush()
        return True
    return False
