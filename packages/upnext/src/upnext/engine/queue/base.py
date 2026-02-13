"""Base queue abstraction for UpNext."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.contracts import DispatchReason
from shared.domain import CronSource, Job, JobStatus


class BaseQueue(ABC):
    """
    Abstract base class for queue implementations.

    All queue backends must implement this interface.

    Lifecycle:
        queue = RedisQueue(...)
        await queue.start()      # Start background tasks
        # ... use queue ...
        await queue.close()      # Stop and cleanup
    """

    # =========================================================================
    # LIFECYCLE - Override if queue needs background tasks
    # =========================================================================

    async def start(
        self,
        functions: list[str] | None = None,
    ) -> None:
        """
        Start the queue and any background tasks.

        Called before the queue is used. Override to start background
        tasks like batch fetching, sweep loops, etc.

        Args:
            functions: List of function keys this worker handles.
        """
        pass

    async def close(self) -> None:
        """
        Stop background tasks and close connections.

        Called when shutting down. Override to clean up resources.
        """
        pass

    # =========================================================================
    # CORE - Must implement these
    # =========================================================================

    @abstractmethod
    async def enqueue(
        self,
        job: Job,
        *,
        delay: float = 0.0,
    ) -> str:
        """
        Add a job to the queue.

        Args:
            job: Job to enqueue
            delay: Delay in seconds before job becomes available (0 = immediate)

        Returns:
            Job ID

        Raises:
            DuplicateJobError: If a job with the same key already exists
        """
        ...

    @abstractmethod
    async def dequeue(
        self,
        functions: list[str],
        *,
        timeout: float = 5.0,
    ) -> Job | None:
        """
        Get the next available job.

        Blocks up to `timeout` seconds waiting for a job.
        Jobs are atomically moved from queued to active state.

        Args:
            functions: Function names to poll for jobs
            timeout: Maximum seconds to wait for a job

        Returns:
            Job if available, None if timeout
        """
        ...

    @abstractmethod
    async def finish(
        self,
        job: Job,
        status: JobStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """
        Mark a job as finished (complete, failed, or cancelled).

        Args:
            job: Job to finish
            status: Final status (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED)
            result: Job result (if successful)
            error: Error message (if failed)
        """
        ...

    @abstractmethod
    async def retry(
        self,
        job: Job,
        delay: float,
    ) -> None:
        """
        Reschedule a job for retry.

        Args:
            job: Job to retry
            delay: Delay in seconds before retry
        """
        ...

    @abstractmethod
    async def get_job(
        self,
        job_id: str,
    ) -> Job | None:
        """
        Get a job by ID.

        Args:
            job_id: Job ID

        Returns:
            Job if found, None otherwise
        """
        ...

    @abstractmethod
    async def cancel(
        self,
        job_id: str,
    ) -> bool:
        """
        Cancel a job.

        Args:
            job_id: ID of job to cancel

        Returns:
            True if job was cancelled, False if not found or already complete
        """
        ...

    # =========================================================================
    # OPTIONAL - Sensible defaults, override for richer functionality
    # =========================================================================

    async def update_progress(
        self,
        job_id: str,
        progress: float,
    ) -> None:
        """
        Update job progress (0.0 to 1.0).

        Default: no-op. Override to track progress.
        """
        pass

    async def heartbeat_active_jobs(
        self,
        jobs: list[Job],
    ) -> None:
        """
        Heartbeat all active jobs to prevent them from being reclaimed.

        Called periodically by the job processor to keep long-running
        jobs alive. Resets the idle time on each job's stream message
        so XAUTOCLAIM won't steal them.

        Default: no-op. Override for queue backends that need it.
        """
        pass

    async def update_job_checkpoint(
        self,
        job_id: str,
        state: dict[str, Any],
        checkpointed_at: str,
    ) -> None:
        """
        Persist the latest checkpoint state for a job.

        Default: no-op. Override to persist checkpoint state.
        """
        _ = (job_id, state, checkpointed_at)

    async def is_cancelled(self, job_id: str) -> bool:  # noqa: ARG002
        """
        Check whether a job has been cancelled before execution starts.

        Default: returns False. Override when the backend can track cancellation markers.
        """
        return False

    async def is_function_paused(self, function: str) -> bool:
        """
        Check whether dispatch is paused for a function key.

        Default: returns False (not paused).
        """
        _ = function
        return False

    async def get_runnable_functions(self, functions: list[str]) -> list[str]:
        """
        Filter a function list down to currently runnable functions.

        Default: returns input unchanged.
        """
        return list(functions)

    async def record_dispatch_reason(
        self,
        function: str,
        reason: DispatchReason,
        *,
        job_id: str | None = None,
    ) -> None:
        """
        Record why a job was deferred or not dispatched.

        Default: no-op. Override for queue backends that track dispatch diagnostics.
        """
        _ = (function, reason, job_id)

    async def subscribe_job(
        self,
        job_id: str,
        timeout: float | None = None,
    ) -> str:
        """
        Wait for job completion.

        Default: polls get_job() until terminal state.
        Override for efficient pubsub-based notification.

        Args:
            job_id: Job ID to wait for
            timeout: Maximum seconds to wait (None waits indefinitely)

        Returns:
            Final job status

        Raises:
            TimeoutError: If timeout reached before completion
        """
        poll_interval = 0.1

        deadline = None if timeout is None else time.time() + timeout

        while True:
            job = await self.get_job(job_id)
            if job and job.status.is_terminal():
                return job.status.value

            if deadline is None:
                await asyncio.sleep(poll_interval)
                continue

            remaining = deadline - time.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining))

        raise TimeoutError(f"Timeout waiting for job {job_id}")

    async def publish_event(
        self,
        event_name: str,
        data: dict[str, Any],
    ) -> None:
        """
        Publish an event for events.

        Default: no-op. Events require Redis streams.
        """
        pass

    async def get_queue_stats(
        self,
        function: str,
    ) -> "QueueStats":
        """
        Get statistics for a event's queue.

        Default: returns empty stats.
        """
        _ = function
        return QueueStats()

    async def stats(self) -> dict[str, int]:
        """
        Get overall queue statistics.

        Default: returns zeros.
        """
        return {"queued": 0, "active": 0, "scheduled": 0}

    async def get_queued_jobs(
        self,
        function: str,
        *,
        limit: int = 100,
    ) -> list[Job]:
        """
        Get queued jobs without dequeuing them.

        Default: returns empty list.
        """
        _ = (function, limit)
        return []

    async def get_dead_letters(
        self,
        function: str,
        *,
        limit: int = 100,
    ) -> list["DeadLetterEntry"]:
        """
        List dead-letter records for a function.

        Default: returns empty list.
        """
        _ = (function, limit)
        return []

    async def replay_dead_letter(
        self,
        function: str,
        entry_id: str,
    ) -> str | None:
        """
        Replay a dead-letter record by ID.

        Returns the new job ID if replayed, else None when the record is missing.
        Default: no-op.
        """
        _ = (function, entry_id)
        return None

    # =========================================================================
    # CRON - Defaults use enqueue with delay
    # =========================================================================

    async def seed_cron(
        self,
        job: Job,
        next_run_at: float,
    ) -> bool:
        """
        Seed a cron job (idempotent).

        Args:
            job: Cron job to seed
            next_run_at: Unix timestamp for next execution

        Returns:
            True if seeded, False if already exists
        """
        delay = max(0.0, next_run_at - time.time())
        try:
            await self.enqueue(job, delay=delay)
            return True
        except DuplicateJobError:
            return False

    async def reschedule_cron(
        self,
        job: Job,
        next_run_at: float,
    ) -> str:
        """
        Reschedule a cron job for its next execution.

        Args:
            job: Completed cron job
            next_run_at: Unix timestamp for next execution

        Returns:
            New job ID
        """
        schedule = job.schedule
        if not schedule:
            raise ValueError(f"Cron job '{job.id}' is missing schedule")

        new_job = Job(
            function=job.function,
            function_name=job.function_name,
            kwargs=job.kwargs,
            key=f"cron:{job.function}",
            status=JobStatus.PENDING,
            timeout=job.timeout,
            source=CronSource(
                schedule=schedule,
                cron_window_at=job.cron_window_at,
                startup_reconciled=job.startup_reconciled,
                startup_policy=job.startup_policy,
            ),
            checkpoint=job.checkpoint,
            checkpoint_at=job.checkpoint_at,
            dlq_replayed_from=job.dlq_replayed_from,
            dlq_failed_at=job.dlq_failed_at,
        )

        delay = max(0.0, next_run_at - time.time())
        return await self.enqueue(new_job, delay=delay)

    async def reconcile_cron_startup(
        self,
        job: Job,
        *,
        now_ts: float | None = None,
    ) -> bool:
        """
        Reconcile cron schedule state at startup.

        Returns True when reconciliation enqueued or adjusted schedule state.
        Default: no-op.
        """
        _ = (job, now_ts)
        return False

    # =========================================================================
    # STREAMS - No-op defaults (events require Redis)
    # =========================================================================

    async def create_stream_group(
        self,
        stream_name: str,
        group: str,
        *,
        start_id: str = "0",
        mkstream: bool = True,
    ) -> bool:
        """
        Create a consumer group for a stream.

        Args:
            stream_name: Stream name
            group: Consumer group name
            start_id: Message ID to start reading from
            mkstream: Create stream if it doesn't exist

        Returns:
            True if created, False if already exists

        Default: no-op, returns False.
        """
        _ = (stream_name, group, start_id, mkstream)
        return False

    async def read_stream(
        self,
        stream_name: str,
        *,
        group: str,
        consumer: str,
        count: int = 100,
        block: int = 5000,
        start_id: str = ">",
    ) -> list[tuple[str, dict[str, Any]]]:
        """
        Read messages from a stream using XREADGROUP.

        Args:
            stream_name: Stream name
            group: Consumer group name
            consumer: Consumer name
            count: Max messages to read
            block: Block timeout in ms (0 = no block)
            start_id: Message ID to start from (">" for new messages)

        Returns:
            List of (message_id, data) tuples

        Default: returns empty list.
        """
        _ = (stream_name, group, consumer, count, block, start_id)
        return []

    async def ack_stream(
        self,
        stream_name: str,
        group: str,
        *event_ids: str,
    ) -> int:
        """
        Acknowledge stream messages.

        Args:
            stream_name: Stream name
            group: Consumer group name
            *event_ids: Message IDs to acknowledge

        Returns:
            Number of messages acknowledged

        Default: no-op, returns 0.
        """
        _ = (stream_name, group, event_ids)
        return 0


# =============================================================================
# Supporting Classes
# =============================================================================


class QueueStats:
    """Statistics for a queue."""

    def __init__(
        self,
        queued: int = 0,
        active: int = 0,
        scheduled: int = 0,
        completed: int = 0,
        failed: int = 0,
    ) -> None:
        self.queued = queued
        self.active = active
        self.scheduled = scheduled
        self.completed = completed
        self.failed = failed

    def __repr__(self) -> str:
        return (
            f"QueueStats(queued={self.queued}, active={self.active}, "
            f"scheduled={self.scheduled}, completed={self.completed}, "
            f"failed={self.failed})"
        )


@dataclass
class DeadLetterEntry:
    """Dead-letter queue entry."""

    entry_id: str
    function: str
    job: Job
    failed_at: datetime | None = None
    reason: str | None = None


class QueueError(Exception):
    """Base exception for queue errors."""

    pass


class DuplicateJobError(QueueError):
    """Raised when trying to enqueue a job with a duplicate key."""

    def __init__(self, job_key: str) -> None:
        self.job_key = job_key
        super().__init__(f"Job with key '{job_key}' already exists")


class JobNotFoundError(QueueError):
    """Raised when a job is not found."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Job '{job_id}' not found")
