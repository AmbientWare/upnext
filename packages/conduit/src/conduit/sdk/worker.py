"""
Worker class with decorator-based registration.

This is the user-facing Worker that supports @worker.task(), @worker.cron(), etc.
"""

import asyncio
import contextlib
import logging
import time as time_module
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar, overload

from shared.models import Job

from conduit.config import get_settings
from conduit.engine.backend import BaseBackend, create_backend
from conduit.engine.cron import calculate_next_cron_run
from conduit.engine.handlers import EventHandle, TaskHandle
from conduit.engine.job_processor import JobProcessor
from conduit.engine.queue import RedisQueue
from conduit.engine.redis import create_redis_client
from conduit.engine.registry import (
    CronDefinition,
    Registry,
)
from conduit.engine.status import StatusBuffer, StatusBufferConfig
from conduit.sdk.context import Context, set_current_context
from conduit.types import BackendType, SyncExecutor

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])
P = ParamSpec("P")

DEFAULT_CONCURRENCY = 2


@dataclass
class Worker:
    """
    Worker class with decorator-based registration.

    Example:
        import conduit

        worker = conduit.Worker("my-worker", concurrency=50)

        @worker.task(retries=3)
        async def process_order(order_id: str):
            ...

        @worker.cron("0 9 * * *")
        async def daily_report():
            ...

        # Run with: conduit run service.py
    """

    name: str = field(default_factory=lambda: f"worker-{uuid.uuid4().hex[:8]}")
    concurrency: int = DEFAULT_CONCURRENCY
    prefetch: int = 1  # Max jobs buffered locally from Redis.
    sync_executor: SyncExecutor = SyncExecutor.THREAD  # THREAD or PROCESS
    sync_pool_size: int | None = (
        None  # Executor pool size. Default: min(32, concurrency) for thread, cpu_count for process.
    )
    redis_url: str | None = None  # Uses config.settings.redis_url if not specified

    # Backend controls persistence (queue type is separate):
    # - BackendType.REDIS: Redis persistence
    # - BackendType.API: Conduit API persistence
    backend: BackendType = BackendType.REDIS

    # Status buffer configuration (for batched reporting)
    status_flush_interval: float = 2.0  # How often to flush status events (seconds)
    status_batch_size: int = 100  # Max events per batch

    # Signal handling (set to False when signals are handled at a higher level)
    handle_signals: bool = True

    # Internal registry
    _registry: Registry = field(default_factory=Registry, init=False)

    # Task handles for .submit()/.wait() access
    _task_handles: dict[str, TaskHandle] = field(default_factory=dict, init=False)

    # Cron definitions
    _crons: list[CronDefinition] = field(default_factory=list, init=False)

    # Event handles
    _event_handles: dict[str, EventHandle] = field(default_factory=dict, init=False)

    # Runtime state
    _redis_client: Any = field(default=None, init=False)
    _queue_backend: RedisQueue = field(default=None, init=False)  # type: ignore[assignment]
    _job_processor: JobProcessor | None = field(default=None, init=False)
    _backend: BaseBackend | None = field(default=None, init=False)
    _status_buffer: StatusBuffer | None = field(default=None, init=False)
    _status_flush_task: asyncio.Task[None] | None = field(default=None, init=False)
    _worker_id: str | None = field(default=None, init=False)
    _heartbeat_task: asyncio.Task[None] | None = field(default=None, init=False)
    _background_tasks: set[asyncio.Task[None]] = field(default_factory=set, init=False)

    def initialize(
        self,
        redis_url: str | None = None,
        worker_id_prefix: str = "worker",
    ) -> str:
        """Set up Redis connection, queue backend, and wire handles.

        Called automatically by start()/execute() if not called explicitly.
        Can be called manually to pass a specific redis_url.

        Safe to call multiple times — only runs setup once.

        Returns:
            The generated worker ID.
        """
        if self._worker_id:
            return self._worker_id

        if redis_url:
            self.redis_url = redis_url
        else:
            self.redis_url = self.redis_url or get_settings().redis_url

        if not self.redis_url:
            raise ValueError(
                "Redis is required. Set redis_url on the Worker "
                "or CONDUIT_REDIS_URL in the environment."
            )
        self._redis_client = create_redis_client(self.redis_url)
        self._queue_backend = RedisQueue(
            client=self._redis_client, inbox_size=self.prefetch
        )

        # Connect task handles to queue
        for handle in self._task_handles.values():
            handle._queue = self._queue_backend

        # Connect event handles to queue
        for handle in self._event_handles.values():
            handle._queue = self._queue_backend

        # Generate worker ID for tracking
        worker_id = f"{worker_id_prefix}_{uuid.uuid4().hex[:8]}"
        self._worker_id = worker_id

        # Create status buffer for batched event reporting
        config = StatusBufferConfig(
            flush_interval=self.status_flush_interval,
            batch_size=self.status_batch_size,
        )
        self._status_buffer = StatusBuffer(self._redis_client, worker_id, config)
        logger.debug(
            f"Status buffering enabled "
            f"(interval={self.status_flush_interval}s, batch={self.status_batch_size})"
        )

        return worker_id

    @property
    def resolved_redis_url(self) -> str | None:
        """Resolved Redis URL."""
        return self.redis_url

    # Overload for bare decorator: @worker.task
    @overload
    def task(self, __func: Callable[P, Any]) -> TaskHandle[P]: ...

    # Overload for decorator factory: @worker.task() or @worker.task(retries=3)
    @overload
    def task(
        self,
        __func: None = None,
        *,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float | None = None,
        cache_key: str | None = None,
        cache_ttl: int | None = None,
        on_start: Callable[..., Any] | None = None,
        on_success: Callable[..., Any] | None = None,
        on_failure: Callable[..., Any] | None = None,
        on_retry: Callable[..., Any] | None = None,
        on_complete: Callable[..., Any] | None = None,
    ) -> Callable[[Callable[P, Any]], TaskHandle[P]]: ...

    def task(
        self,
        __func: Callable[..., Any] | None = None,
        *,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float | None = None,
        cache_key: str | None = None,
        cache_ttl: int | None = None,
        on_start: Callable[..., Any] | None = None,
        on_success: Callable[..., Any] | None = None,
        on_failure: Callable[..., Any] | None = None,
        on_retry: Callable[..., Any] | None = None,
        on_complete: Callable[..., Any] | None = None,
    ) -> Any:
        """
        Decorator to register a task with this worker.

        Returns a TaskHandle with typed .submit() and .wait() methods.
        Use get_current_context() inside the task to access the runtime context.

        Example:
            from conduit import get_current_context

            @worker.task
            async def simple_task(order_id: str):
                ctx = get_current_context()
                ctx.set_progress(50, "Processing...")
                return {"order_id": order_id}

            @worker.task(retries=3, timeout=30.0)
            async def process_order(order_id: str):
                ...

            # .submit() knows it needs order_id: str
            await process_order.submit(order_id="123")
        """

        def decorator(fn: Callable[..., Any]) -> TaskHandle[Any]:
            task_name = fn.__name__

            definition = self._registry.register_task(
                name=task_name,
                func=fn,
                retries=retries,
                retry_delay=retry_delay,
                retry_backoff=retry_backoff,
                timeout=timeout,
                cache_key=cache_key,
                cache_ttl=cache_ttl,
                on_start=on_start,
                on_success=on_success,
                on_failure=on_failure,
                on_retry=on_retry,
                on_complete=on_complete,
            )

            handle = TaskHandle(
                name=task_name,
                func=fn,
                definition=definition,
                _worker=self,
            )

            self._task_handles[task_name] = handle
            return handle

        # If __func is provided, we're being used as a bare decorator: @worker.task
        if __func is not None:
            return decorator(__func)
        # Otherwise, we're being used as a decorator factory: @worker.task(retries=3)
        return decorator

    def cron(
        self,
        schedule: str,
        *,
        name: str | None = None,
        timeout: float | None = None,
    ) -> Callable[[F], F]:
        """
        Decorator to register a cron job with this worker.

        Example:
            @worker.cron("0 9 * * *")  # Every day at 9 AM
            async def daily_report():
                ...

            @worker.cron("*/5 * * * *", timezone="America/New_York")
            def health_check():
                ...
        """

        def decorator(func: F) -> F:
            cron_name = name or func.__name__

            definition = self._registry.register_cron(
                schedule=schedule,
                func=func,
                name=cron_name,
                timeout=timeout,
            )

            # Also register as a task so worker can execute it
            self._registry.register_task(
                name=cron_name,
                func=func,
                timeout=timeout,
            )

            self._crons.append(definition)
            return func

        return decorator

    def event(self, pattern: str) -> EventHandle:
        """
        Create an event that handlers can subscribe to.

        Example:
            order_placed = worker.event("order.placed")

            @order_placed.on
            async def send_confirmation(event):
                ...

            @order_placed.on(retries=3)
            async def update_inventory(event):
                ...

            # Send - all handlers fire
            order_placed.send(order_id="123")
        """
        handle = EventHandle(pattern=pattern, _worker=self)
        self._event_handles[pattern] = handle
        return handle

    async def start(self) -> None:
        """
        Start the worker.

        This connects to Redis, optionally connects to the Conduit API
        for tracking, schedules cron jobs, and starts processing tasks.
        """

        worker_id = self.initialize(worker_id_prefix="worker")

        # Build registered function names and definitions
        registered_functions: list[str] = []
        function_definitions: list[dict[str, Any]] = []

        # Add tasks
        for name, handle in self._task_handles.items():
            registered_functions.append(name)
            function_definitions.append(
                {
                    "name": name,
                    "type": "task",
                    "timeout": handle.definition.timeout,
                    "max_retries": handle.definition.retries,
                    "retry_delay": handle.definition.retry_delay,
                }
            )

        # Add crons
        for cron_def in self._crons:
            cron_name = cron_def.name or cron_def.func.__name__
            if cron_name not in registered_functions:
                registered_functions.append(cron_name)
            function_definitions.append(
                {
                    "name": cron_name,
                    "type": "cron",
                    "schedule": cron_def.schedule,
                    "timeout": cron_def.timeout,
                }
            )

        # Add event handlers
        for pattern, handle in self._event_handles.items():
            for handler_name in handle.handler_names:
                if handler_name not in registered_functions:
                    registered_functions.append(handler_name)
            function_definitions.append(
                {
                    "name": pattern,
                    "type": "event",
                    "pattern": handle.pattern,
                    "handlers": handle.handler_names,
                }
            )

        # Connect to backend based on backend setting
        self._backend = await create_backend(self.backend, client=self._redis_client)
        if self._backend:
            connected = await self._backend.connect(
                worker_id,
                self.name,
                functions=registered_functions,
                function_definitions=function_definitions,
                concurrency=self.concurrency,
            )
            if connected:
                logger.debug("Connected to backend")
                # Start heartbeat loop (every 5 seconds)
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                if self._status_buffer:
                    self._status_flush_task = asyncio.create_task(
                        self._status_buffer.flush_loop(self._backend)
                    )
            else:
                logger.debug("Backend unavailable, running without backend")
                self._backend = None

        # Create job processor (internal execution engine)
        self._job_processor = JobProcessor(
            queue=self._queue_backend,
            registry=self._registry,
            concurrency=self.concurrency,
            functions=registered_functions,
            sync_executor=self.sync_executor,
            sync_pool_size=self.sync_pool_size,
            status_buffer=self._status_buffer,
            handle_signals=self.handle_signals,
        )

        # Seed cron jobs
        if self._crons:
            await self._seed_crons()
            logger.debug(f"Seeded {len(self._crons)} cron jobs")

        # Start processing
        await self._job_processor.start()

    async def _seed_crons(self) -> None:
        """Seed cron jobs using Redis-based scheduling."""
        for cron_def in self._crons:
            job_name = cron_def.name or cron_def.func.__name__
            next_run = calculate_next_cron_run(cron_def.schedule)

            job = Job(
                function=job_name,
                kwargs={},
                key=f"cron:{job_name}",
                timeout=cron_def.timeout,
                schedule=cron_def.schedule,
                metadata={"cron": True},
            )

            try:
                if self._queue_backend:
                    was_seeded = await self._queue_backend.seed_cron(
                        job, next_run.timestamp()
                    )
                    if was_seeded:
                        logger.debug(f"Seeded cron '{job_name}' → {next_run}")
                    else:
                        logger.debug(f"Cron '{job_name}' already registered")
            except Exception as e:
                logger.error(f"Failed to seed cron job '{job_name}': {e}")

    async def _heartbeat_loop(self) -> None:
        """Send heartbeats to the API with exponential backoff on failures."""
        if not self._backend or not self._worker_id:
            return

        consecutive_failures = 0
        base_interval = 3.0  # Normal heartbeat interval
        max_backoff = 60.0  # Max delay when API is down

        while True:
            try:
                # Get current stats from engine worker
                active_jobs = 0
                jobs_processed = 0
                jobs_failed = 0
                queued_jobs = 0

                if self._job_processor:
                    active_jobs = self._job_processor.active_job_count
                    jobs_processed = self._job_processor.jobs_processed
                    jobs_failed = self._job_processor.jobs_failed

                if not self._backend:
                    return

                success = await self._backend.heartbeat(
                    self._worker_id,
                    active_jobs=active_jobs,
                    jobs_processed=jobs_processed,
                    jobs_failed=jobs_failed,
                    queued_jobs=queued_jobs,
                )

                if success:
                    if consecutive_failures > 0:
                        logger.info("API connection restored")
                    consecutive_failures = 0
                    await asyncio.sleep(base_interval)
                else:
                    consecutive_failures += 1
                    backoff = min(
                        base_interval * (2**consecutive_failures), max_backoff
                    )
                    logger.debug(
                        f"Heartbeat failed (attempt {consecutive_failures}), "
                        f"retrying in {backoff:.1f}s..."
                    )
                    await asyncio.sleep(backoff)
                    # Try to re-register with the API
                    await self._backend.connect(
                        self._worker_id,
                        self.name,
                        functions=list(self._task_handles.keys()),
                        concurrency=self.concurrency,
                    )

            except asyncio.CancelledError:
                break

            except Exception as e:
                consecutive_failures += 1
                backoff = min(base_interval * (2**consecutive_failures), max_backoff)
                logger.debug(f"Heartbeat error: {e}, retrying in {backoff:.1f}s")
                await asyncio.sleep(backoff)

    async def execute(
        self,
        function_name: str,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """
        Execute a single function directly (for CLI testing/debugging).

        This initializes the worker (connects to Redis, API backend, etc.),
        runs the specified function once, and then shuts down cleanly.

        Args:
            function_name: Name of the task to execute
            kwargs: Arguments to pass to the function

        Returns:
            The function's return value

        Raises:
            ValueError: If the function is not found
            Exception: Any exception raised by the function
        """

        kwargs = kwargs or {}

        # Find the function
        task_handle = self._task_handles.get(function_name)
        if not task_handle:
            available = list(self._task_handles.keys())
            raise ValueError(
                f"Function '{function_name}' not found. "
                f"Available: {', '.join(available) if available else 'none'}"
            )

        # Shared initialization (queue, emit, task handles, worker ID, status buffer)
        worker_id = self.initialize(worker_id_prefix="call")

        # Connect to backend based on backend setting
        self._backend = await create_backend(self.backend, client=self._redis_client)
        if self._backend:
            connected = await self._backend.connect(
                worker_id,
                self.name,
                functions=[function_name],
                concurrency=1,
            )
            if not connected:
                self._backend = None

        job: Job | None = None
        try:
            # Create job and context
            job = Job(
                function=function_name,
                kwargs=kwargs,
            )
            ctx = Context.from_job(job)
            set_current_context(ctx)

            # Report job started
            if self._backend:
                await self._backend.job_started(job, worker_id=worker_id)

            # Execute the function
            start = time_module.time()
            func = task_handle.func
            if task_handle.definition.is_async:
                result = await func(**kwargs)
            else:
                result = func(**kwargs)

            duration_ms = (time_module.time() - start) * 1000

            # Report job completed
            if self._backend:
                await self._backend.job_completed(
                    job, result=result, duration_ms=duration_ms
                )

            return result

        except Exception as e:
            # Report job failed
            if self._backend and job:
                await self._backend.job_failed(
                    job,
                    error=str(e),
                    traceback=traceback.format_exc(),
                    will_retry=False,
                )
            raise

        finally:
            set_current_context(None)
            if self._backend:
                await self._backend.disconnect()
            if self._queue_backend:
                await self._queue_backend.close()

    async def stop(self, timeout: float = 30.0) -> None:
        """Stop the worker gracefully.

        The timeout applies to the job processor (finishing active jobs).
        Other cleanup uses small fixed timeouts (~1s total overhead).
        """
        # Stop heartbeat loop
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task

        # Flush status buffer (0.5s max)
        if self._status_buffer:
            self._status_buffer.stop()
        if self._status_flush_task:
            try:
                await asyncio.wait_for(self._status_flush_task, timeout=0.5)
            except asyncio.TimeoutError:
                self._status_flush_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._status_flush_task

        # Stop job processor - this is where the timeout matters
        if self._job_processor:
            await self._job_processor.stop(timeout)

        # Cancel remaining background tasks (0.5s max)
        if self._background_tasks:
            _, pending = await asyncio.wait(self._background_tasks, timeout=0.5)
            for task in pending:
                task.cancel()
            if pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*pending, return_exceptions=True)
            self._background_tasks.clear()

        # Close connections
        if self._queue_backend:
            await self._queue_backend.close()
        if self._backend:
            await self._backend.disconnect()

        logger.debug(f"Worker '{self.name}' stopped")

    @property
    def tasks(self) -> dict[str, TaskHandle]:
        """Get all registered task handles."""
        return dict(self._task_handles)

    @property
    def crons(self) -> list[CronDefinition]:
        """Get all registered cron definitions."""
        return list(self._crons)

    @property
    def events(self) -> dict[str, EventHandle]:
        """Get all registered event handles."""
        return dict(self._event_handles)

    def __repr__(self) -> str:
        return (
            f"Worker(name={self.name!r}, concurrency={self.concurrency}, "
            f"tasks={len(self._task_handles)}, crons={len(self._crons)}, "
            f"events={len(self._event_handles)})"
        )
