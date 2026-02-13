"""High-performance async job processor for UpNext.

Architecture:
    [Queue] → [dequeue()] → [Processors] → [finish()] → [Queue]

Batching optimizations are encapsulated within the queue implementation:
- RedisQueue uses internal inbox/outbox for batched Redis operations

Note: This is the internal execution engine. Users interact with upnext.sdk.Worker,
which delegates to JobProcessor for actual job processing.
"""

import asyncio
import contextlib
import contextvars
import logging
import multiprocessing
import os
import queue as thread_queue
import signal
import time
import traceback as tb
import uuid
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from typing import Any, cast

from shared.contracts import DispatchReason
from shared.domain import Job, JobStatus

from upnext.engine.cron import calculate_next_cron_timestamp
from upnext.engine.queue.base import BaseQueue
from upnext.engine.registry import Registry, TaskDefinition
from upnext.sdk.context import Context, set_current_context
from upnext.types import (
    CommandQueueLike,
    ContextCommand,
    ContextCommandOrSentinel,
    SyncExecutor,
)

logger = logging.getLogger(__name__)


def _run_sync_task_with_context(
    func: Callable[..., Any],
    kwargs: dict[str, Any],
    ctx: Context,
) -> Any:
    """Process-pool wrapper that sets context in the child process."""
    set_current_context(ctx)
    try:
        return func(**kwargs)
    finally:
        set_current_context(None)


class JobProcessor:
    """
    High-performance async job processor for UpNext.

    This is the internal execution engine that actually processes jobs.
    Users should use upnext.Worker (the SDK Worker) which provides the
    decorator-based API and delegates to JobProcessor for execution.

    Features:
    - Configurable concurrency (default 100 concurrent jobs)
    - Queue abstraction handles batching internally
    - Support for both sync and async task functions
    - Graceful shutdown with job completion
    - Automatic retry handling with exponential backoff

    Example:
        processor = JobProcessor(
            queue=redis_queue,
            registry=registry,
            concurrency=100,
        )
        await processor.start()
    """

    def __init__(
        self,
        queue: BaseQueue,
        registry: Registry,
        *,
        concurrency: int = 100,
        functions: list[str] | None = None,
        sync_executor: SyncExecutor = SyncExecutor.THREAD,
        sync_pool_size: int | None = None,
        dequeue_timeout: float = 5.0,
        status_buffer: Any | None = None,  # StatusPublisher
        status_flush_timeout_seconds: float = 2.0,
        handle_signals: bool = True,
    ) -> None:
        """
        Initialize the processor.

        Args:
            queue: Queue backend (Redis)
            registry: Function registry with task definitions
            concurrency: Maximum concurrent jobs
            functions: Function names to process
            sync_executor: Executor type for sync tasks (THREAD or PROCESS)
            sync_pool_size: Pool size for sync executor. Defaults to min(32, concurrency) for thread, cpu_count for process.
            dequeue_timeout: Timeout for dequeue operations
            status_buffer: Status buffer for batched event reporting
            status_flush_timeout_seconds: Max time budget for draining pending
                status events during shutdown.
            handle_signals: Whether to set up SIGTERM/SIGINT handlers (default True).
                Set to False when signals are handled at a higher level.
        """
        self._queue = queue
        self._registry = registry
        self._concurrency = concurrency
        self._functions = functions or []
        self._dequeue_timeout = dequeue_timeout
        self._status_buffer = status_buffer
        self._status_flush_timeout_seconds = max(0.1, status_flush_timeout_seconds)
        self._handle_signals = handle_signals

        # Worker identity
        self._worker_id = f"worker_{uuid.uuid4().hex[:8]}"

        # Executor pool for sync functions
        if sync_executor == SyncExecutor.PROCESS:
            pool_size = sync_pool_size or os.cpu_count() or 4
            self._sync_pool = ProcessPoolExecutor(max_workers=pool_size)
        else:
            pool_size = sync_pool_size or min(32, concurrency)
            self._sync_pool = ThreadPoolExecutor(
                max_workers=pool_size,
                thread_name_prefix="upnext-worker-",
            )

        # Active processor tasks
        self._tasks: set[asyncio.Task[None]] = set()

        # Active jobs tracked for auto-heartbeating
        self._active_jobs: dict[str, Job] = {}
        self._heartbeat_task: asyncio.Task[None] | None = None

        # Shutdown coordination
        self._stop_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()

        # Statistics
        self._jobs_processed = 0
        self._jobs_failed = 0
        self._jobs_retried = 0

    @property
    def worker_id(self) -> str:
        """Get worker identifier."""
        return self._worker_id

    @property
    def is_running(self) -> bool:
        """Check if worker is running."""
        return not self._stop_event.is_set()

    @property
    def active_jobs(self) -> int:
        """Get number of jobs currently being executed."""
        return len(self._active_jobs)

    @property
    def stats(self) -> dict[str, int]:
        """Get worker statistics."""
        return {
            "processed": self._jobs_processed,
            "failed": self._jobs_failed,
            "retried": self._jobs_retried,
            "active": self.active_jobs,
        }

    @property
    def active_job_count(self) -> int:
        """Get number of jobs currently being executed."""
        return len(self._active_jobs)

    @property
    def jobs_processed(self) -> int:
        """Get total jobs processed."""
        return self._jobs_processed

    @property
    def jobs_failed(self) -> int:
        """Get total jobs failed."""
        return self._jobs_failed

    async def start(self) -> None:
        """
        Start the processor.

        This method blocks until shutdown is requested.
        """
        if self._functions:
            logger.debug(f"Processing {len(self._functions)} functions")
        else:
            logger.debug("No functions specified")

        # Set up signal handlers (only if not handled at a higher level)
        loop = asyncio.get_running_loop()
        if self._handle_signals:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._handle_signal)

        try:
            # Start the queue (initializes batching)
            await self._queue.start(functions=self._functions)

            # Start auto-heartbeat loop
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Spawn processor tasks
            for _ in range(self._concurrency):
                self._spawn_processor()

            # Wait for shutdown
            await self._stop_event.wait()

            # Stop heartbeat loop
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass

            # Cancel all processor tasks (most are idle, waiting on dequeue)
            for task in list(self._tasks):
                task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)

        finally:
            if self._status_buffer and hasattr(self._status_buffer, "close"):
                try:
                    await self._status_buffer.close(
                        timeout_seconds=self._status_flush_timeout_seconds
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to flush status publisher during shutdown: %s",
                        exc,
                    )
            # Close the queue (flushes pending operations and closes connections)
            await self._queue.close()

            # Cleanup
            self._sync_pool.shutdown(wait=False)
            self._shutdown_event.set()

        logger.debug(f"Worker {self._worker_id} stopped. Stats: {self.stats}")

    async def stop(self, timeout: float = 30.0) -> None:
        """
        Request graceful shutdown.

        Args:
            timeout: Maximum time to wait for active jobs to complete
        """
        logger.debug(f"Stop requested for worker {self._worker_id}")
        self._stop_event.set()

        # Wait for shutdown with timeout
        try:
            async with asyncio.timeout(timeout):
                await self._shutdown_event.wait()
        except TimeoutError:
            logger.warning(f"Shutdown timeout, {len(self._tasks)} jobs still active")
            # Cancel remaining tasks
            for task in self._tasks:
                task.cancel()

    async def _heartbeat_loop(self) -> None:
        """Periodically heartbeat active jobs to prevent XAUTOCLAIM from reclaiming them."""
        # Heartbeat at 1/3 of claim timeout to leave plenty of margin.
        # Default claim timeout is 30s, so this runs every 10s.
        interval = getattr(self._queue, "_claim_timeout_ms", 30_000) / 1000 / 3

        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(interval)

                jobs = list(self._active_jobs.values())
                if jobs:
                    await self._queue.heartbeat_active_jobs(jobs)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Heartbeat loop error: {e}")

    def _handle_signal(self) -> None:
        """Handle shutdown signal."""
        logger.debug("Received shutdown signal")
        self._stop_event.set()

    async def _emit_status_event(
        self,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if not self._status_buffer:
            return
        method = getattr(self._status_buffer, method_name, None)
        if method is None:
            return
        try:
            await method(*args, **kwargs)
        except Exception as exc:
            job_id = args[0] if args else "unknown"
            logger.warning(
                "Status publish failed method=%s job_id=%s: %s",
                method_name,
                job_id,
                exc,
            )

    def _spawn_processor(self, previous: asyncio.Task[None] | None = None) -> None:
        """
        Spawn a new processor task.

        Uses done callback for zero-latency respawn.
        """
        if previous:
            self._tasks.discard(previous)

        if not self._stop_event.is_set():
            task = asyncio.create_task(self._process_one())
            task.add_done_callback(self._spawn_processor)
            self._tasks.add(task)

    async def _process_one(self) -> None:
        """Process a single job from the queue."""
        try:
            # Get job directly from queue
            job = await self._queue.dequeue(
                self._functions,
                timeout=self._dequeue_timeout,
            )

            if not job:
                return

            # Job might have been cancelled after dequeue/prefetch.
            is_cancelled = False
            try:
                is_cancelled = await self._queue.is_cancelled(job.id)
            except AttributeError:
                is_cancelled = False
            if is_cancelled:
                await self._queue.record_dispatch_reason(
                    job.function,
                    DispatchReason.CANCELLED,
                    job_id=job.id,
                )
                await self._queue.finish(
                    job,
                    JobStatus.CANCELLED,
                    error="Cancelled before execution",
                )
                logger.debug(
                    "Skipped cancelled job %s (%s)",
                    job.function_name,
                    job.id,
                )
                return

            # Function may have been paused after enqueue/dequeue.
            try:
                is_paused = await self._queue.is_function_paused(job.function)
            except AttributeError:
                is_paused = False
            if is_paused:
                await self._queue.record_dispatch_reason(
                    job.function,
                    DispatchReason.PAUSED,
                    job_id=job.id,
                )
                await self._queue.retry(job, delay=1.0)
                logger.debug(
                    "Deferred paused function job %s (%s)",
                    job.function_name,
                    job.id,
                )
                return

            # Mark job as started (records state transition)
            job.mark_started(self._worker_id)
            if not job.root_id:
                job.root_id = job.id

            # Get task definition
            task_def = self._registry.get_task(job.function)
            if not task_def:
                logger.error(f"Unknown task function: {job.function}")
                await self._queue.finish(
                    job,
                    JobStatus.FAILED,
                    error=f"Unknown task function: {job.function}",
                )
                self._jobs_failed += 1
                return

            # Log and report job started
            attempt_info = (
                f" (attempt {job.attempts}/{job.max_retries + 1})"
                if job.max_retries > 0
                else ""
            )
            logger.debug(
                "Starting %s (%s)%s",
                job.function_name,
                job.function,
                attempt_info,
            )

            queue_wait_ms: float | None = None
            if job.scheduled_at is not None:
                queue_wait_ms = round(
                    max(0.0, (time.time() - job.scheduled_at.timestamp()) * 1000),
                    3,
                )

            await self._emit_status_event(
                "record_job_started",
                job.id,
                job.function,
                job.function_name,
                job.attempts,
                job.max_retries,
                parent_id=job.parent_id,
                root_id=job.root_id,
                source=job.source_data,
                checkpoint=job.checkpoint,
                checkpoint_at=job.checkpoint_at,
                dlq_replayed_from=job.dlq_replayed_from,
                dlq_failed_at=job.dlq_failed_at,
                scheduled_at=job.scheduled_at,
                queue_wait_ms=queue_wait_ms,
            )

            # Execute job (track for auto-heartbeating)
            self._active_jobs[job.id] = job
            start_time = time.time()
            try:
                result = await self._execute_job(job, task_def)
                duration_ms = (time.time() - start_time) * 1000
                await self._handle_success(job, task_def, result, duration_ms)
            except Exception as e:
                await self._handle_failure(job, task_def, e)
            finally:
                self._active_jobs.pop(job.id, None)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error in processor: {e}")

    async def _execute_job(self, job: Job, task_def: TaskDefinition) -> Any:
        """
        Execute a job with timeout.

        Handles both sync and async functions.
        Active jobs are auto-heartbeated by the processor to prevent XAUTOCLAIM
        from reclaiming long-running jobs.
        """
        # Create context (no backend — commands flow through _cmd_queue)
        ctx = Context.from_job(job)

        # Call on_start hook
        if task_def.on_start:
            await self._call_hook(task_def.on_start, ctx)

        # Execute with timeout
        timeout = job.timeout or task_def.timeout

        try:
            if timeout:
                async with asyncio.timeout(timeout):
                    return await self._call_function(task_def, ctx, job)
            else:
                return await self._call_function(task_def, ctx, job)
        except TimeoutError as e:
            raise TimeoutError(f"Job {job.id} timed out after {timeout}s") from e

    async def _call_function(
        self,
        task_def: TaskDefinition,
        ctx: "Context",
        job: Job,
    ) -> Any:
        """Call the task function, handling sync/async.

        Creates a command queue appropriate for the executor mode, attaches it
        to the Context, and starts a drain task that dispatches commands to the
        real backend.  The drain task is awaited after the function returns so
        all pending commands are flushed.

        Context is always available via get_current_context().
        If the function signature accepts 'ctx' as first param, we also pass it explicitly.
        """
        kwargs = job.kwargs

        # Choose the right queue type for this executor mode
        cmd_queue: CommandQueueLike
        if task_def.is_async:
            cmd_queue = _AsyncQueueWrapper(asyncio.Queue[ContextCommandOrSentinel]())
        elif isinstance(self._sync_pool, ProcessPoolExecutor):
            cmd_queue = cast(CommandQueueLike, multiprocessing.Queue())
        else:
            cmd_queue = thread_queue.Queue[ContextCommandOrSentinel]()

        ctx._cmd_queue = cmd_queue

        # Create backend for drain task
        backend = self._create_context_backend(job)

        # Start drain task
        drain = asyncio.create_task(
            _drain_commands(cmd_queue, backend, is_async_queue=task_def.is_async)
        )
        poll_interval = 0.25 if (job.timeout or task_def.timeout or 0) <= 10 else 1.0
        cancel_poll = asyncio.create_task(
            self._poll_job_cancellation(
                job,
                ctx,
                interval_seconds=poll_interval,
            )
        )

        # Set context in contextvars so get_current_context() works
        set_current_context(ctx)

        try:
            if task_def.is_async:
                # Async function - call directly
                result = await task_def.func(**kwargs)
            else:
                # Sync function - run in thread/process pool
                loop = asyncio.get_running_loop()
                if isinstance(self._sync_pool, ProcessPoolExecutor):
                    result = await loop.run_in_executor(
                        self._sync_pool,
                        _run_sync_task_with_context,
                        task_def.func,
                        kwargs,
                        ctx,
                    )
                else:
                    func_with_args = partial(task_def.func, **kwargs)
                    ctx_copy = contextvars.copy_context()
                    result = await loop.run_in_executor(
                        self._sync_pool, ctx_copy.run, func_with_args
                    )

            return result

        finally:
            cancel_poll.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_poll
            # Signal drain to stop and wait for it to flush
            cmd_queue.put(None)
            await drain

            # Clear context
            set_current_context(None)

    async def _poll_job_cancellation(
        self,
        job: Job,
        ctx: "Context",
        *,
        interval_seconds: float = 0.5,
        max_interval_seconds: float = 2.0,
    ) -> None:
        """Set context cancellation flag when external cancellation is requested."""
        # Process pool tasks run in a separate process and receive a copy of Context,
        # so cancellation flag updates here cannot be observed there.
        if isinstance(self._sync_pool, ProcessPoolExecutor):
            return

        current_interval = max(0.1, interval_seconds)
        while True:
            try:
                if await self._queue.is_cancelled(job.id):
                    ctx._cancelled = True  # noqa: SLF001
                    return
            except Exception:
                return
            await asyncio.sleep(current_interval)
            current_interval = min(max_interval_seconds, current_interval * 1.5)

    async def _call_hook(
        self,
        hook: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Call a hook function, handling sync/async."""
        try:
            if asyncio.iscoroutinefunction(hook):
                await hook(*args, **kwargs)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    self._sync_pool,
                    partial(hook, *args, **kwargs),
                )
        except Exception as e:
            logger.warning(f"Hook {hook.__name__} raised exception: {e}")

    async def _handle_success(
        self,
        job: Job,
        task_def: TaskDefinition,
        result: Any,
        duration_ms: float | None = None,
    ) -> None:
        """Handle successful job completion."""
        # Call on_success hook
        if task_def.on_success:
            ctx = Context.from_job(job)
            await self._call_hook(task_def.on_success, ctx, result)

        # Mark job complete
        await self._queue.finish(job, JobStatus.COMPLETE, result=result)
        self._jobs_processed += 1

        # Report completion
        await self._emit_status_event(
            "record_job_completed",
            job.id,
            job.function,
            job.function_name,
            root_id=job.root_id,
            parent_id=job.parent_id,
            attempt=job.attempts,
            result=result,
            duration_ms=duration_ms,
        )

        duration_str = f" in {duration_ms:.0f}ms" if duration_ms else ""
        logger.debug(
            "Completed %s (%s)%s",
            job.function_name,
            job.function,
            duration_str,
        )

        # Reschedule cron jobs for next execution
        if job.is_cron:
            cron_base_ts = self._cron_reschedule_base(job)
            next_run_at = self._calculate_next_cron_run(
                job.schedule, base_ts=cron_base_ts
            )
            await self._queue.reschedule_cron(job, next_run_at)
            logger.debug(
                "Rescheduled cron %s (%s) → %s",
                job.function_name,
                job.function,
                datetime.fromtimestamp(next_run_at, UTC),
            )

        # Call on_complete hook
        if task_def.on_complete:
            ctx = Context.from_job(job)
            await self._call_hook(task_def.on_complete, ctx)

    async def _handle_failure(
        self,
        job: Job,
        task_def: TaskDefinition,
        error: Exception,
    ) -> None:
        """Handle job failure with retry logic."""

        error_msg = str(error)
        error_traceback = tb.format_exc()

        logger.warning(f"Job {job.id} failed (attempt {job.attempts}): {error_msg}")

        # Check if we can retry
        max_retries = task_def.retries
        if job.attempts <= max_retries:
            # Call on_retry hook
            if task_def.on_retry:
                ctx = Context.from_job(job)
                await self._call_hook(task_def.on_retry, ctx, error)

            # Calculate retry delay with exponential backoff
            delay = task_def.retry_delay * (
                task_def.retry_backoff ** (job.attempts - 1)
            )

            logger.info(
                f"Retrying job {job.id} in {delay}s (attempt {job.attempts + 1})"
            )

            # Mark as retrying (records state transition)
            job.mark_retrying(delay)

            # Report retry
            await self._emit_status_event(
                "record_job_retrying",
                job.id,
                job.function,
                job.function_name,
                job.root_id,
                error_msg,
                delay,
                current_attempt=job.attempts,
                next_attempt=job.attempts + 1,
                parent_id=job.parent_id,
            )

            # Reschedule job
            await self._queue.record_dispatch_reason(
                job.function,
                DispatchReason.RETRYING,
                job_id=job.id,
            )
            await self._queue.retry(job, delay)
            self._jobs_retried += 1
        else:
            # Max retries exceeded
            logger.error(
                f"Job {job.id} failed permanently after {job.attempts} attempts"
            )

            # Call on_failure hook
            if task_def.on_failure:
                ctx = Context.from_job(job)
                await self._call_hook(task_def.on_failure, ctx, error)

            # Mark job failed
            await self._queue.finish(job, JobStatus.FAILED, error=error_msg)
            self._jobs_failed += 1

            # Report failure
            await self._emit_status_event(
                "record_job_failed",
                job.id,
                job.function,
                job.function_name,
                job.root_id,
                error_msg,
                attempt=job.attempts,
                max_retries=job.max_retries,
                parent_id=job.parent_id,
                traceback=error_traceback,
                will_retry=False,
            )

            # IMPORTANT: Reschedule cron jobs even on failure
            # The execution failed, but the schedule must continue
            if job.is_cron:
                cron_base_ts = self._cron_reschedule_base(job)
                next_run_at = self._calculate_next_cron_run(
                    job.schedule,
                    base_ts=cron_base_ts,
                )
                await self._queue.reschedule_cron(job, next_run_at)
                logger.debug(
                    "Rescheduled cron %s (%s) → %s",
                    job.function_name,
                    job.function,
                    datetime.fromtimestamp(next_run_at, UTC),
                )

            # Call on_complete hook
            if task_def.on_complete:
                ctx = Context.from_job(job)
                await self._call_hook(task_def.on_complete, ctx)

    def _create_context_backend(self, job: Job) -> "JobContextBackend":
        """Create context backend for a job."""
        return JobContextBackend(
            self._queue,
            job,
            self._status_buffer,
        )

    def _cron_reschedule_base(self, job: Job) -> float | None:
        """Resolve optional cron scheduling base timestamp from job fields."""
        raw = job.cron_window_at
        try:
            return float(raw)  # type: ignore
        except (TypeError, ValueError):
            return None

    def _calculate_next_cron_run(
        self,
        schedule: str | None,
        *,
        base_ts: float | None = None,
    ) -> float:
        """
        Calculate the next run time for a cron schedule.

        Supports both 5-field (minute precision) and 6-field (second precision) formats.

        Args:
            schedule: Cron expression

        Returns:
            Unix timestamp of next run time
        """
        if not schedule:
            return time.time()

        if base_ts is None:
            return calculate_next_cron_timestamp(schedule)
        return calculate_next_cron_timestamp(
            schedule,
            datetime.fromtimestamp(base_ts, UTC),
        )


class JobContextBackend:
    """Context backend that delegates to queue and status buffer operations.

    Status events are written to Redis via StatusPublisher for batched API reporting:
    - Non-blocking writes (Redis is microseconds, HTTP is milliseconds)
    - Batched API calls (many events in one request)
    - Fault tolerance (any worker can flush pending events)
    """

    def __init__(
        self,
        queue: BaseQueue,
        job: Job,
        status_buffer: Any | None = None,  # StatusPublisher
    ) -> None:
        self._queue = queue
        self._job = job
        self._status_buffer = status_buffer

    async def _emit_status_event(
        self,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if not self._status_buffer:
            return
        method = getattr(self._status_buffer, method_name, None)
        if method is None:
            return
        try:
            await method(*args, **kwargs)
        except Exception as exc:
            job_id = args[0] if args else "unknown"
            logger.warning(
                "Status publish failed method=%s job_id=%s: %s",
                method_name,
                job_id,
                exc,
            )

    async def set_progress(
        self, job_id: str, progress: float, message: str | None = None
    ) -> None:
        await self._queue.update_progress(job_id, progress)
        await self._emit_status_event(
            "record_job_progress",
            job_id,
            self._job.root_id,
            progress,
            parent_id=self._job.parent_id,
            message=message,
        )

    async def checkpoint(self, job_id: str, state: dict[str, Any]) -> None:
        """Store checkpoint state for resumption after failures."""
        checkpointed_at = datetime.now(UTC).isoformat()
        if job_id == self._job.id:
            self._job.checkpoint = state
            self._job.checkpoint_at = checkpointed_at
        await self._queue.update_job_checkpoint(job_id, state, checkpointed_at)
        await self._emit_status_event(
            "record_job_checkpoint",
            job_id,
            self._job.root_id,
            state,
            parent_id=self._job.parent_id,
        )

    async def log(self, job_id: str, level: str, message: str, **extra: Any) -> None:
        """Send a log entry for this job."""
        await self._emit_status_event(
            "record_job_log",
            job_id,
            level,
            message,
            **extra,
        )

    async def check_cancelled(self, job_id: str) -> bool:
        job = await self._queue.get_job(job_id)
        return job is not None and job.status == JobStatus.CANCELLED


class _AsyncQueueWrapper:
    """Wraps asyncio.Queue to expose a sync .put() matching queue.Queue / multiprocessing.Queue."""

    __slots__ = ("_q",)

    def __init__(self, q: asyncio.Queue[ContextCommandOrSentinel]) -> None:
        self._q = q

    def put(
        self,
        item: ContextCommandOrSentinel,
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        _ = block, timeout
        self._q.put_nowait(item)

    async def get(self) -> ContextCommandOrSentinel:
        return await self._q.get()


async def _drain_commands(
    cmd_queue: Any,
    backend: JobContextBackend,
    *,
    is_async_queue: bool = False,
) -> None:
    """Drain command queue and dispatch to the real backend.

    Runs as an asyncio task alongside the job.  Reads command tuples pushed
    by Context methods and calls the corresponding async backend methods.
    Exits when it receives a ``None`` sentinel.

    For thread-safe / process-safe queues (queue.Queue, multiprocessing.Queue),
    we use a blocking ``get`` in an executor thread and rely on the sentinel
    write in ``_call_function`` for cooperative shutdown.
    """
    loop = asyncio.get_running_loop()

    while True:
        # Read next command
        if is_async_queue:
            cmd: ContextCommandOrSentinel = await cmd_queue.get()
        else:
            cmd = await loop.run_in_executor(None, cmd_queue.get)

        if cmd is None:
            # Sentinel — all commands flushed, exit
            return

        command = cast(ContextCommand, cmd)
        try:
            if command[0] == "set_progress":
                _, job_id, progress, message = command
                await backend.set_progress(job_id, progress, message)
            elif command[0] == "checkpoint":
                _, job_id, state = command
                await backend.checkpoint(job_id, state)
            elif command[0] == "send_log":
                _, job_id, level, message, extra = command
                await backend.log(job_id, level, message, **extra)
            else:
                logger.warning(f"Unknown drain command: {command[0]}")
        except Exception as e:
            logger.warning(f"Drain command {command[0]} failed: {e}")
