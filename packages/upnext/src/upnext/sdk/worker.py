"""
Worker class with decorator-based registration.

This is the user-facing Worker that supports @worker.task(), @worker.cron(), etc.
Registration logic lives in _worker_registration.py.
Connection/lifecycle helpers live in _worker_connection.py.
"""

import asyncio
import contextlib
import importlib
import json
import logging
import pkgutil
import socket
import time as time_module
import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ParamSpec, TypeVar, overload

from shared.contracts import FunctionConfig, MissedRunPolicy
from shared.domain import Job
from shared.keys import worker_instance_key

from upnext.config import get_settings
from upnext.engine.backend_api import BackendAPI
from upnext.engine.handlers import EventHandle, TaskHandle
from upnext.engine.job_processor import JobProcessor
from upnext.engine.queue import RedisQueue
from upnext.engine.redis import create_redis_client
from upnext.engine.registry import CronDefinition, Registry
from upnext.engine.status import StatusPublisher, StatusPublisherConfig
from upnext.sdk._worker_connection import (
    heartbeat_loop,
    publish_worker_signal,
    seed_crons,
    write_function_definitions,
    write_worker_definition,
    write_worker_heartbeat,
)
from upnext.sdk._worker_registration import WorkerRegistration
from upnext.sdk.context import Context, set_current_context
from upnext.sdk.secrets import fetch_and_inject_secrets
from upnext.types import SyncExecutor

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])
P = ParamSpec("P")
R = TypeVar("R")

DEFAULT_CONCURRENCY = 2
DEFAULT_QUEUE_BATCH_SIZE = 100
DEFAULT_QUEUE_INBOX_SIZE = 1000
DEFAULT_QUEUE_OUTBOX_SIZE = 10_000
DEFAULT_QUEUE_FLUSH_INTERVAL_MS = 5.0
DEFAULT_QUEUE_CLAIM_TIMEOUT_MS = 30_000
DEFAULT_QUEUE_JOB_TTL_SECONDS = 86_400
DEFAULT_QUEUE_RESULT_TTL_SECONDS = 3_600
DEFAULT_QUEUE_STREAM_MAXLEN = 0
DEFAULT_QUEUE_DLQ_STREAM_MAXLEN = 10_000


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
    sync_executor: SyncExecutor = SyncExecutor.THREAD
    redis_url: str | None = None
    secrets: list[str] = field(default_factory=list)
    handle_signals: bool = True
    autodiscover_packages: list[str] = field(default_factory=list)

    # Internal state
    _registry: Registry = field(default_factory=Registry, init=False)
    _reg: WorkerRegistration = field(default=None, init=False)  # type: ignore[assignment]
    _redis_client: Any = field(default=None, init=False)
    _queue_backend: RedisQueue = field(default=None, init=False)  # type: ignore[assignment]
    _job_processor: JobProcessor | None = field(default=None, init=False)
    _status_buffer: StatusPublisher | None = field(default=None, init=False)
    _started_at: datetime | None = field(default=None, init=False)
    _registered_functions: list[str] = field(default_factory=list, init=False)
    _function_name_map: dict[str, str] = field(default_factory=dict, init=False)
    _function_definitions: list[FunctionConfig] = field(
        default_factory=list, init=False
    )
    _worker_id: str | None = field(default=None, init=False)
    _heartbeat_task: asyncio.Task[None] | None = field(default=None, init=False)
    _background_tasks: set[asyncio.Task[None]] = field(default_factory=set, init=False)
    _status_flush_timeout_seconds: float = field(default=2.0, init=False)

    def __post_init__(self) -> None:
        self._reg = WorkerRegistration(self.name, self._registry)
        if self.autodiscover_packages:
            self.autodiscover(*self.autodiscover_packages)

    # =========================================================================
    # REGISTRATION (delegated to WorkerRegistration)
    # =========================================================================

    @overload
    def task(
        self, __func: Callable[P, R] | Callable[P, Awaitable[R]]
    ) -> TaskHandle[P, R]: ...

    @overload
    def task(
        self,
        __func: None = None,
        *,
        name: str | None = None,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float = 30 * 60,
        cache_key: str | None = None,
        cache_ttl: int | None = None,
        rate_limit: str | None = None,
        max_concurrency: int | None = None,
        routing_group: str | None = None,
        group_max_concurrency: int | None = None,
        on_start: Callable[..., Any] | None = None,
        on_success: Callable[..., Any] | None = None,
        on_failure: Callable[..., Any] | None = None,
        on_retry: Callable[..., Any] | None = None,
        on_complete: Callable[..., Any] | None = None,
    ) -> Callable[[Callable[P, R] | Callable[P, Awaitable[R]]], TaskHandle[P, R]]: ...

    def task(
        self,
        __func: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float = 30 * 60,
        cache_key: str | None = None,
        cache_ttl: int | None = None,
        rate_limit: str | None = None,
        max_concurrency: int | None = None,
        routing_group: str | None = None,
        group_max_concurrency: int | None = None,
        on_start: Callable[..., Any] | None = None,
        on_success: Callable[..., Any] | None = None,
        on_failure: Callable[..., Any] | None = None,
        on_retry: Callable[..., Any] | None = None,
        on_complete: Callable[..., Any] | None = None,
    ) -> Any:
        """Decorator to register a task with this worker.

        Returns a TaskHandle with typed .submit() and .wait() methods.
        """
        decorator = self._reg.task(
            None,
            name=name,
            retries=retries,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            timeout=timeout,
            cache_key=cache_key,
            cache_ttl=cache_ttl,
            rate_limit=rate_limit,
            max_concurrency=max_concurrency,
            routing_group=routing_group,
            group_max_concurrency=group_max_concurrency,
            on_start=on_start,
            on_success=on_success,
            on_failure=on_failure,
            on_retry=on_retry,
            on_complete=on_complete,
            _worker=self,
        )
        if __func is None:
            return decorator
        return decorator(__func)

    def cron(
        self,
        schedule: str,
        *,
        name: str | None = None,
        timeout: float = 30 * 60,
        missed_run_policy: MissedRunPolicy = MissedRunPolicy.LATEST_ONLY,
        max_catch_up_seconds: float | None = None,
    ) -> Callable[[F], F]:
        """Decorator to register a cron job with this worker."""
        return self._reg.cron(
            schedule,
            name=name,
            timeout=timeout,
            missed_run_policy=missed_run_policy,
            max_catch_up_seconds=max_catch_up_seconds,
        )

    def event(self, pattern: str) -> EventHandle:
        """Create an event that handlers can subscribe to."""
        return self._reg.event(pattern, _worker=self, _queue=self._queue_backend)

    def autodiscover(self, *packages: str) -> None:
        """Import all modules in the given packages to trigger task registration.

        Example:
            worker = Worker("my-app")
            worker.autodiscover("myapp.tasks", "myapp.workflows")
        """

        for package_name in packages:
            package = importlib.import_module(package_name)
            for _, module_name, _ in pkgutil.walk_packages(
                package.__path__,
                prefix=f"{package_name}.",
            ):
                importlib.import_module(module_name)

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def initialize(
        self,
        redis_url: str | None = None,
        worker_id_prefix: str = "worker",
    ) -> str:
        """Set up Redis connection, queue backend, and wire handles.

        Safe to call multiple times -- only runs setup once.
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

        # Enforce inbox_size >= batch_size to prevent fetcher starvation.
        inbox_size = max(DEFAULT_QUEUE_INBOX_SIZE, DEFAULT_QUEUE_BATCH_SIZE)

        self._queue_backend = RedisQueue(
            client=self._redis_client,
            claim_timeout_ms=DEFAULT_QUEUE_CLAIM_TIMEOUT_MS,
            batch_size=DEFAULT_QUEUE_BATCH_SIZE,
            inbox_size=inbox_size,
            outbox_size=DEFAULT_QUEUE_OUTBOX_SIZE,
            flush_interval=DEFAULT_QUEUE_FLUSH_INTERVAL_MS / 1000,
            job_ttl_seconds=DEFAULT_QUEUE_JOB_TTL_SECONDS,
            result_ttl_seconds=DEFAULT_QUEUE_RESULT_TTL_SECONDS,
            stream_maxlen=DEFAULT_QUEUE_STREAM_MAXLEN,
            dlq_stream_maxlen=DEFAULT_QUEUE_DLQ_STREAM_MAXLEN,
        )

        # Connect task handles to queue
        for handle in self._reg.task_handles.values():
            handle._queue = self._queue_backend

        # Connect event handles to queue
        for handle in self._reg.event_handles.values():
            handle._queue = self._queue_backend

        # Generate worker ID for tracking
        worker_id = f"{worker_id_prefix}_{uuid.uuid4().hex[:8]}"
        self._worker_id = worker_id
        self._status_flush_timeout_seconds = max(
            0.1,
            settings.status_shutdown_flush_timeout_seconds,
        )
        durable_buffer_key = None
        if settings.status_durable_buffer_enabled:
            durable_candidate = settings.status_durable_buffer_key.strip()
            if durable_candidate:
                durable_buffer_key = durable_candidate

        self._status_buffer = StatusPublisher(
            self._redis_client,
            worker_id,
            config=StatusPublisherConfig(
                max_stream_len=settings.status_stream_max_len,
                retry_attempts=settings.status_publish_retry_attempts,
                retry_base_delay_seconds=max(0.0, settings.status_publish_retry_base_ms)
                / 1000,
                retry_max_delay_seconds=max(0.0, settings.status_publish_retry_max_ms)
                / 1000,
                pending_buffer_size=max(1, settings.status_pending_buffer_size),
                pending_flush_batch_size=max(
                    1, settings.status_pending_flush_batch_size
                ),
                durable_buffer_key=durable_buffer_key,
                durable_buffer_maxlen=max(1, settings.status_durable_buffer_maxlen),
                durable_probe_interval_seconds=max(
                    0.1, settings.status_durable_probe_interval_seconds
                ),
                durable_flush_interval_seconds=max(
                    0.05, settings.status_durable_flush_interval_seconds
                ),
                strict=settings.status_publish_strict,
            ),
        )

        return worker_id

    # =========================================================================
    # LIFECYCLE (delegated to _worker_connection helpers)
    # =========================================================================

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

    @property
    def resolved_redis_url(self) -> str | None:
        return self.redis_url

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

    async def start(self) -> None:
        """Start the worker: connect to Redis, seed crons, start processing."""
        worker_id = self.initialize(worker_id_prefix="worker")

        if self.secrets:
            backend = BackendAPI()
            try:
                await fetch_and_inject_secrets(self.secrets, backend)
            finally:
                await backend.close()

        catalog = self._reg.build_catalog()

        self._started_at = datetime.now(UTC)
        self._registered_functions = catalog.function_keys
        self._function_name_map = catalog.function_name_map
        self._function_definitions = catalog.function_definitions

        await write_worker_heartbeat(self._redis_client, worker_id, self._worker_data())
        await write_worker_definition(
            self._redis_client,
            self.name,
            self._registered_functions,
            self._function_name_map,
            self.concurrency,
        )
        await write_function_definitions(self._redis_client, self._function_definitions)
        self._heartbeat_task = asyncio.create_task(
            heartbeat_loop(self._redis_client, worker_id, self._worker_data)
        )
        logger.debug(f"Worker instance registered: {worker_id}")

        self._job_processor = JobProcessor(
            queue=self._queue_backend,
            registry=self._registry,
            concurrency=self.concurrency,
            functions=catalog.function_keys,
            sync_executor=self.sync_executor,
            status_buffer=self._status_buffer,
            handle_signals=self.handle_signals,
        )

        if self._reg.cron_definitions:
            await seed_crons(self._reg.cron_definitions, self._queue_backend)
            logger.debug(f"Seeded {len(self._reg.cron_definitions)} cron jobs")

        await self._job_processor.start()

    async def execute(
        self,
        function_name: str,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a single function directly (for CLI testing/debugging)."""
        kwargs = kwargs or {}

        task_handle = self._reg.task_handles.get(function_name)
        if not task_handle:
            task_handle = next(
                (
                    h
                    for h in self._reg.task_handles.values()
                    if h.function_key == function_name
                ),
                None,
            )
        if not task_handle:
            available = list(self._reg.task_handles.keys())
            raise ValueError(
                f"Function '{function_name}' not found. "
                f"Available: {', '.join(available) if available else 'none'}"
            )

        self.initialize(worker_id_prefix="call")

        job = Job(
            function=task_handle.function_key,
            function_name=task_handle.name,
            kwargs=kwargs,
        )

        try:
            job.root_id = job.id
            job.mark_started(self._worker_id or "call")
            ctx = Context.from_job(job)
            set_current_context(ctx)

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
                queue_wait_ms=round(
                    max(
                        0.0,
                        (time_module.time() - job.scheduled_at.timestamp()) * 1000,
                    ),
                    3,
                ),
            )

            start = time_module.time()
            func = task_handle.func
            if task_handle.definition.is_async:
                result = await func(**kwargs)
            else:
                result = func(**kwargs)

            duration_ms = (time_module.time() - start) * 1000

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

            return result

        except Exception as e:
            await self._emit_status_event(
                "record_job_failed",
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
            if self._status_buffer:
                with contextlib.suppress(Exception):
                    await self._status_buffer.close(
                        timeout_seconds=self._status_flush_timeout_seconds
                    )
            if self._queue_backend:
                await self._queue_backend.close()

    async def stop(self, timeout: float = 30.0) -> None:
        """Stop the worker gracefully."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task

        if self._job_processor:
            await self._job_processor.stop(timeout)
        elif self._status_buffer:
            with contextlib.suppress(Exception):
                await self._status_buffer.close(
                    timeout_seconds=self._status_flush_timeout_seconds
                )

        if self._background_tasks:
            _, pending = await asyncio.wait(self._background_tasks, timeout=0.5)
            for task in pending:
                task.cancel()
            if pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*pending, return_exceptions=True)
            self._background_tasks.clear()

        if self._redis_client and self._worker_id:
            try:
                await self._redis_client.delete(worker_instance_key(self._worker_id))
                await publish_worker_signal(
                    self._redis_client, self._worker_id, self.name, "worker.stopped"
                )
            except Exception:
                pass
        if self._queue_backend:
            await self._queue_backend.close()

        logger.debug(f"Worker '{self.name}' stopped")

    # =========================================================================
    # ACCESSORS
    # =========================================================================

    @property
    def tasks(self) -> dict[str, TaskHandle[Any, Any]]:
        return dict(self._reg.task_handles)

    @property
    def crons(self) -> list[CronDefinition]:
        return list(self._reg.cron_definitions)

    @property
    def events(self) -> dict[str, EventHandle]:
        return dict(self._reg.event_handles)

    def __repr__(self) -> str:
        return (
            f"Worker(name={self.name!r}, concurrency={self.concurrency}, "
            f"tasks={len(self._reg.task_handles)}, crons={len(self._reg.cron_definitions)}, "
            f"events={len(self._reg.event_handles)})"
        )
