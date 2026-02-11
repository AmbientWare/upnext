"""
Worker class with decorator-based registration.

This is the user-facing Worker that supports @worker.task(), @worker.cron(), etc.
"""

import asyncio
import contextlib
import json
import logging
import socket
import time as time_module
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ParamSpec, TypeVar, overload

from shared.models import Job
from shared.schemas import FunctionConfig, FunctionType
from shared.workers import (
    FUNCTION_DEF_TTL,
    FUNCTION_KEY_PREFIX,
    WORKER_DEF_PREFIX,
    WORKER_DEF_TTL,
    WORKER_HEARTBEAT_INTERVAL,
    WORKER_EVENTS_STREAM,
    WORKER_INSTANCE_KEY_PREFIX,
    WORKER_TTL,
)

from upnext.config import get_settings
from upnext.engine.cron import calculate_next_cron_run
from upnext.engine.function_identity import build_function_key
from upnext.engine.handlers import EventHandle, TaskHandle
from upnext.engine.job_processor import JobProcessor
from upnext.engine.queue import RedisQueue
from upnext.engine.redis import create_redis_client
from upnext.engine.registry import (
    CronDefinition,
    Registry,
)
from upnext.engine.status import StatusPublisher
from upnext.sdk.context import Context, set_current_context
from upnext.types import SyncExecutor

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])
P = ParamSpec("P")

DEFAULT_CONCURRENCY = 2


@dataclass
class Worker:
    """
    Worker class with decorator-based registration.

    Example:
        import upnext

        worker = upnext.Worker("my-worker", concurrency=50)

        @worker.task(retries=3)
        async def process_order(order_id: str):
            ...

        @worker.cron("0 9 * * *")
        async def daily_report():
            ...

        # Run with: upnext run service.py
    """

    name: str = field(default_factory=lambda: f"worker-{uuid.uuid4().hex[:8]}")
    concurrency: int = DEFAULT_CONCURRENCY
    prefetch: int = 1  # Max jobs buffered locally from Redis.
    sync_executor: SyncExecutor = SyncExecutor.THREAD  # THREAD or PROCESS
    sync_pool_size: int | None = (
        None  # Executor pool size. Default: min(32, concurrency) for thread, cpu_count for process.
    )
    redis_url: str | None = None  # Uses config.settings.redis_url if not specified

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
    _status_buffer: StatusPublisher | None = field(default=None, init=False)
    _started_at: datetime | None = field(default=None, init=False)
    _registered_functions: list[str] = field(default_factory=list, init=False)
    _function_name_map: dict[str, str] = field(default_factory=dict, init=False)
    _function_definitions: list[dict[str, Any]] = field(
        default_factory=list, init=False
    )
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

        settings = get_settings()

        if redis_url:
            self.redis_url = redis_url
        else:
            self.redis_url = self.redis_url or settings.redis_url

        if not self.redis_url:
            raise ValueError(
                "Redis is required. Set redis_url on the Worker "
                "or UPNEXT_REDIS_URL in the environment."
            )
        self._redis_client = create_redis_client(self.redis_url)
        self._queue_backend = RedisQueue(
            client=self._redis_client,
            inbox_size=self.prefetch,
            job_ttl_seconds=settings.queue_job_ttl_seconds,
            result_ttl_seconds=settings.queue_result_ttl_seconds,
            stream_maxlen=settings.queue_stream_maxlen,
            dlq_stream_maxlen=settings.queue_dlq_stream_maxlen,
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

        # Create status publisher for writing events to Redis stream
        self._status_buffer = StatusPublisher(self._redis_client, worker_id)

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
        name: str | None = None,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float = 30 * 60,  # 30 minutes
        cache_key: str | None = None,
        cache_ttl: int | None = None,
        rate_limit: str | None = None,
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
        name: str | None = None,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float = 30 * 60,  # 30 minutes
        cache_key: str | None = None,
        cache_ttl: int | None = None,
        rate_limit: str | None = None,
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
            from upnext import get_current_context

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
            task_name = name or fn.__name__
            function_key = build_function_key(
                "task",
                module=fn.__module__,
                qualname=fn.__qualname__,
                name=task_name,
            )
            if task_name in self._task_handles:
                raise ValueError(
                    f"Task name '{task_name}' is already registered on worker '{self.name}'"
                )

            definition = self._registry.register_task(
                name=function_key,
                display_name=task_name,
                func=fn,
                retries=retries,
                retry_delay=retry_delay,
                retry_backoff=retry_backoff,
                timeout=timeout,
                cache_key=cache_key,
                cache_ttl=cache_ttl,
                rate_limit=rate_limit,
                on_start=on_start,
                on_success=on_success,
                on_failure=on_failure,
                on_retry=on_retry,
                on_complete=on_complete,
            )

            handle = TaskHandle(
                name=task_name,
                function_key=function_key,
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
        timeout: float = 30 * 60,  # 30 minutes
    ) -> Callable[[F], F]:
        """
        Decorator to register a cron job with this worker.

        Example:
            @worker.cron("0 9 * * *")  # Every day at 9 AM
            async def daily_report():
                ...

            @worker.cron("*/5 * * * *")
            def health_check():
                ...
        """

        def decorator(func: F) -> F:
            cron_name = name or func.__name__
            function_key = build_function_key(
                "cron",
                module=func.__module__,
                qualname=func.__qualname__,
                name=cron_name,
                schedule=schedule,
            )

            definition = self._registry.register_cron(
                key=function_key,
                display_name=cron_name,
                schedule=schedule,
                func=func,
                timeout=timeout,
            )

            # Also register as a task so worker can execute it
            self._registry.register_task(
                name=function_key,
                display_name=cron_name,
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

        This connects to Redis, optionally connects to the UpNext API
        for tracking, schedules cron jobs, and starts processing tasks.
        """

        worker_id = self.initialize(worker_id_prefix="worker")

        # Build registered function keys and definitions
        registered_functions: list[str] = []
        function_name_map: dict[str, str] = {}
        function_definitions: list[dict[str, Any]] = []

        # Add tasks
        for display_name, handle in self._task_handles.items():
            function_key = handle.function_key
            registered_functions.append(function_key)
            function_name_map[function_key] = display_name
            function_definitions.append(
                {
                    "key": function_key,
                    "name": display_name,
                    "type": FunctionType.TASK,
                    "timeout": handle.definition.timeout,
                    "max_retries": handle.definition.retries,
                    "retry_delay": handle.definition.retry_delay,
                    "rate_limit": handle.definition.rate_limit,
                }
            )

        # Add crons
        for cron_def in self._crons:
            if cron_def.key not in registered_functions:
                registered_functions.append(cron_def.key)
            function_name_map[cron_def.key] = cron_def.display_name
            function_definitions.append(
                {
                    "key": cron_def.key,
                    "name": cron_def.display_name,
                    "type": FunctionType.CRON,
                    "schedule": cron_def.schedule,
                    "timeout": cron_def.timeout,
                }
            )

        # Add event handlers (one definition per handler key)
        for handle in self._event_handles.values():
            for handler in handle.handler_configs():
                handler_key = handler["key"]
                handler_name = handler["name"]
                if handler_key not in registered_functions:
                    registered_functions.append(handler_key)
                function_name_map[handler_key] = handler_name
                function_definitions.append(
                    {
                        "key": handler_key,
                        "name": handler_name,
                        "type": FunctionType.EVENT,
                        "pattern": handle.pattern,
                        "timeout": handler["timeout"],
                        "max_retries": handler["max_retries"],
                        "retry_delay": handler["retry_delay"],
                        "rate_limit": handler["rate_limit"],
                    }
                )

        # Register worker instance and definitions in Redis
        self._started_at = datetime.now(UTC)
        self._registered_functions = registered_functions
        self._function_name_map = function_name_map
        self._function_definitions = function_definitions
        await self._write_worker_heartbeat()
        await self._write_worker_definition()
        await self._write_function_definitions()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.debug(f"Worker instance registered: {worker_id}")

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
            next_run = calculate_next_cron_run(cron_def.schedule)

            job = Job(
                function=cron_def.key,
                function_name=cron_def.display_name,
                kwargs={},
                key=f"cron:{cron_def.key}",
                timeout=cron_def.timeout,
                schedule=cron_def.schedule,
                metadata={"cron": True, "cron_name": cron_def.display_name},
            )

            try:
                if self._queue_backend:
                    was_seeded = await self._queue_backend.seed_cron(
                        job, next_run.timestamp()
                    )
                    if was_seeded:
                        logger.debug(
                            f"Seeded cron '{cron_def.display_name}' ({cron_def.key}) → {next_run}"
                        )
                    else:
                        logger.debug(
                            f"Cron '{cron_def.display_name}' ({cron_def.key}) already registered"
                        )
            except Exception as e:
                logger.error(
                    f"Failed to seed cron job '{cron_def.display_name}' ({cron_def.key}): {e}"
                )

    def _worker_data(self) -> str:
        """Build JSON worker data for Redis."""
        active_jobs = 0
        jobs_processed = 0
        jobs_failed = 0

        if self._job_processor:
            active_jobs = self._job_processor.active_job_count
            jobs_processed = self._job_processor.jobs_processed
            jobs_failed = self._job_processor.jobs_failed

        return json.dumps(
            {
                "id": self._worker_id,
                "worker_name": self.name,
                "started_at": self._started_at.isoformat() if self._started_at else "",
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "functions": self._registered_functions,
                "function_names": self._function_name_map,
                "concurrency": self.concurrency,
                "active_jobs": active_jobs,
                "jobs_processed": jobs_processed,
                "jobs_failed": jobs_failed,
                "hostname": socket.gethostname(),
            }
        )

    async def _write_worker_heartbeat(self) -> None:
        """Write worker data to Redis with TTL."""
        if not self._redis_client or not self._worker_id:
            return
        key = f"{WORKER_INSTANCE_KEY_PREFIX}:{self._worker_id}"
        await self._redis_client.setex(key, WORKER_TTL, self._worker_data())
        await self._publish_worker_signal("worker.heartbeat")

    async def _write_worker_definition(self) -> None:
        """Write persistent worker definition to Redis with 30-day TTL.

        Key is `upnext:worker_defs:{worker_name}` — a config registry
        refreshed each time a worker starts.  Active/inactive is derived
        from live instance heartbeats, not key existence.
        """
        if not self._redis_client:
            return
        key = f"{WORKER_DEF_PREFIX}:{self.name}"
        data = json.dumps(
            {
                "name": self.name,
                "functions": self._registered_functions,
                "function_names": self._function_name_map,
                "concurrency": self.concurrency,
            }
        )
        await self._redis_client.setex(key, WORKER_DEF_TTL, data)
        await self._publish_worker_signal("worker.definition.updated")

    async def _write_function_definitions(self) -> None:
        """Write function definitions to Redis with a 30-day TTL.

        Keys are `upnext:functions:{key}` — a config registry refreshed
        each time a worker starts.  Active/inactive is determined by live
        worker heartbeats, not by key existence.  The 30-day TTL ensures
        stale definitions self-clean (matches API registry TTL).
        """
        if not self._redis_client:
            return
        for func_def in self._function_definitions:
            function_key = func_def.get("key")
            if not function_key:
                continue
            key = f"{FUNCTION_KEY_PREFIX}:{function_key}"
            existing = await self._redis_client.get(key)
            if existing:
                payload = (
                    existing.decode() if isinstance(existing, bytes) else str(existing)
                )
                try:
                    existing_def = FunctionConfig.model_validate_json(payload)
                    if "paused" not in func_def:
                        func_def["paused"] = existing_def.paused
                except Exception:
                    pass
            await self._redis_client.setex(key, FUNCTION_DEF_TTL, json.dumps(func_def))

    async def _publish_worker_signal(self, signal_type: str) -> None:
        """Publish worker heartbeat/lifecycle signal for realtime dashboards."""
        if not self._redis_client or not self._worker_id:
            return

        payload = json.dumps(
            {
                "type": signal_type,
                "at": datetime.now(UTC).isoformat(),
                "worker_id": self._worker_id,
                "worker_name": self.name,
            }
        )
        try:
            try:
                await self._redis_client.xadd(
                    WORKER_EVENTS_STREAM,
                    {"data": payload},
                    maxlen=10_000,
                    approximate=True,
                )
            except TypeError:
                # Compatibility fallback for Redis clients lacking approximate trim.
                await self._redis_client.xadd(
                    WORKER_EVENTS_STREAM,
                    {"data": payload},
                    maxlen=10_000,
                )
        except Exception as e:
            logger.debug(f"Failed to publish worker signal '{signal_type}': {e}")

    async def _heartbeat_loop(self) -> None:
        """Refresh worker heartbeat TTL in Redis periodically."""
        while True:
            try:
                await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL)
                await self._write_worker_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Worker heartbeat error: {e}")
                await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL)

    async def execute(
        self,
        function_name: str,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """
        Execute a single function directly (for CLI testing/debugging).

        This initializes the worker (connects to Redis, etc.),
        runs the specified function once, and then shuts down cleanly.

        Args:
            function_name: Task display name or stable function key
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
            task_handle = next(
                (
                    h
                    for h in self._task_handles.values()
                    if h.function_key == function_name
                ),
                None,
            )
        if not task_handle:
            available = list(self._task_handles.keys())
            raise ValueError(
                f"Function '{function_name}' not found. "
                f"Available: {', '.join(available) if available else 'none'}"
            )

        # Shared initialization (queue, emit, task handles, worker ID, status buffer)
        self.initialize(worker_id_prefix="call")

        job = Job(
            function=task_handle.function_key,
            function_name=task_handle.name,
            kwargs=kwargs,
        )

        try:
            # Initialize job and execution context
            job.root_id = job.id
            job.mark_started(self._worker_id or "call")
            ctx = Context.from_job(job)
            set_current_context(ctx)

            # Report job started
            if self._status_buffer:
                await self._status_buffer.record_job_started(
                    job.id,
                    job.function,
                    job.function_name,
                    job.attempts,
                    job.max_retries,
                    parent_id=job.parent_id,
                    root_id=job.root_id,
                    metadata=job.metadata,
                )

            # Execute the function
            start = time_module.time()
            func = task_handle.func
            if task_handle.definition.is_async:
                result = await func(**kwargs)
            else:
                result = func(**kwargs)

            duration_ms = (time_module.time() - start) * 1000

            # Report job completed
            if self._status_buffer:
                await self._status_buffer.record_job_completed(
                    job.id,
                    job.function,
                    job.function_name,
                    root_id=job.root_id,
                    parent_id=job.parent_id,
                    attempt=job.attempts,
                    result=result,
                    duration_ms=duration_ms,
                )

            return result

        except Exception as e:
            # Report job failed
            if self._status_buffer:
                await self._status_buffer.record_job_failed(
                    job.id,
                    job.function,
                    job.function_name,
                    root_id=job.root_id,
                    error=str(e),
                    attempt=job.attempts,
                    max_retries=job.max_retries,
                    parent_id=job.parent_id,
                    traceback=traceback.format_exc(),
                    will_retry=False,
                )
            raise

        finally:
            set_current_context(None)
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

        # Remove worker from Redis and close connections
        if self._redis_client and self._worker_id:
            try:
                await self._redis_client.delete(
                    f"{WORKER_INSTANCE_KEY_PREFIX}:{self._worker_id}"
                )
                await self._publish_worker_signal("worker.stopped")
            except Exception:
                pass
        if self._queue_backend:
            await self._queue_backend.close()

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
