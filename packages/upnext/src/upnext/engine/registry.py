"""Function registry for UpNext."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.contracts.common import MissedRunPolicy
from shared.patterns import matches_event_pattern

from upnext.engine.cron import calculate_next_cron_run
from upnext.engine.queue.redis.rate_limit import parse_rate_limit


@dataclass
class TaskDefinition:
    """Metadata for a registered task function."""

    # Stable internal identity key (used for queue routing and worker matching).
    name: str
    # Human-readable label for UI/logs.
    display_name: str
    func: Callable[..., Any]
    is_async: bool

    # Retry configuration
    retries: int = 0
    retry_delay: float = 1.0
    retry_backoff: float = 2.0

    # Timeout
    timeout: float | None = None

    # Caching
    cache_key: str | None = None
    cache_ttl: int | None = None
    rate_limit: str | None = None
    max_concurrency: int | None = None
    routing_group: str | None = None
    group_max_concurrency: int | None = None

    # Hooks
    on_start: Callable[..., Any] | None = None
    on_success: Callable[..., Any] | None = None
    on_failure: Callable[..., Any] | None = None
    on_retry: Callable[..., Any] | None = None
    on_complete: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.retries < 0:
            raise ValueError(f"retries must be >= 0, got {self.retries}")
        if self.retry_delay < 0:
            raise ValueError(f"retry_delay must be >= 0, got {self.retry_delay}")
        if self.retry_backoff < 1:
            raise ValueError(f"retry_backoff must be >= 1, got {self.retry_backoff}")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {self.timeout}")
        if self.cache_ttl is not None and self.cache_ttl <= 0:
            raise ValueError(f"cache_ttl must be > 0, got {self.cache_ttl}")
        if self.rate_limit is not None:
            normalized = self.rate_limit.strip()
            if not normalized:
                raise ValueError("rate_limit must be a non-empty string")
            parse_rate_limit(normalized)
            self.rate_limit = normalized
        if self.max_concurrency is not None and self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self.routing_group is not None:
            normalized_group = self.routing_group.strip()
            if not normalized_group:
                raise ValueError("routing_group must be a non-empty string")
            self.routing_group = normalized_group
        if self.group_max_concurrency is not None and self.group_max_concurrency < 1:
            raise ValueError("group_max_concurrency must be >= 1")


@dataclass
class EventDefinition:
    """Metadata for a registered event."""

    event: str
    key: str
    display_name: str
    func: Callable[..., Any]
    is_async: bool
    # Retry configuration (propagated to TaskDefinition)
    retries: int = 0
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    timeout: float = 30 * 60  # 30 minutes
    rate_limit: str | None = None
    max_concurrency: int | None = None
    routing_group: str | None = None
    group_max_concurrency: int | None = None


@dataclass
class CronDefinition:
    """Metadata for a registered cron job."""

    key: str
    display_name: str
    schedule: str  # Cron expression
    func: Callable[..., Any]
    is_async: bool
    timeout: float = 30 * 60  # 30 minutes
    missed_run_policy: MissedRunPolicy = MissedRunPolicy.LATEST_ONLY
    max_catch_up_seconds: float | None = None

    def __post_init__(self) -> None:
        """Validate cron scheduling controls."""
        if self.timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {self.timeout}")

        if self.max_catch_up_seconds is not None and self.max_catch_up_seconds <= 0:
            raise ValueError("max_catch_up_seconds must be > 0")

        normalized_schedule = self.schedule.strip()
        if not normalized_schedule:
            raise ValueError("schedule must be a non-empty cron expression")

        try:
            calculate_next_cron_run(normalized_schedule)
        except Exception as exc:
            raise ValueError(f"Invalid cron schedule '{self.schedule}': {exc}") from exc

        self.schedule = normalized_schedule


@dataclass
class AppDefinition:
    """Metadata for a registered long-running app/service."""

    name: str
    func: Callable[..., Any]
    is_async: bool

    # Network configuration
    port: int | None = 8080  # None = no HTTP (background process)
    external: bool = False  # Expose to public internet

    # Scaling (ignored locally, used in deployment)
    replicas: int = 1

    # Resources (ignored locally, used in deployment)
    cpu: float | None = None  # CPU cores
    memory: str | None = None  # e.g., "512Mi", "1Gi"

    # Health check
    health_check: str | None = "/health"  # Endpoint path or None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.port is not None and (self.port < 0 or self.port > 65535):
            raise ValueError(f"port must be 0-65535, got {self.port}")
        if self.replicas < 1:
            raise ValueError(f"replicas must be >= 1, got {self.replicas}")
        if self.cpu is not None and self.cpu <= 0:
            raise ValueError(f"cpu must be > 0, got {self.cpu}")

    @property
    def is_http(self) -> bool:
        """Check if this app exposes HTTP."""
        return self.port is not None


class Registry:
    """
    Central registry for all UpNext functions.

    Stores metadata for tasks, events, cron jobs, and apps.
    Used by workers to look up function implementations and configuration.

    Example:
        registry = Registry()

        @registry.task(retries=3)
        async def my_task(ctx, data):
            return process(data)

        # Or register manually
        registry.register_task("my_task", my_func, retries=3)
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskDefinition] = {}
        self._events: dict[str, list[EventDefinition]] = {}  # event -> handlers
        self._crons: dict[str, CronDefinition] = {}
        self._apps: dict[str, AppDefinition] = {}

    def register_task(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        display_name: str | None = None,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float = 30 * 60,  # 30 minutes
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
    ) -> TaskDefinition:
        """
        Register a task function.

        Args:
            name: Unique task name
            func: Task function (sync or async)
            retries: Number of retry attempts
            retry_delay: Base delay between retries (seconds)
            retry_backoff: Exponential backoff multiplier
            timeout: Execution timeout (seconds)
            cache_key: Template for cache key (e.g., "user:{user_id}")
            cache_ttl: Cache TTL in seconds
            rate_limit: Rate limit string (e.g., "100/m")
            max_concurrency: Max number of concurrent active jobs for this function
            routing_group: Optional dispatch group identifier for shared quotas
            group_max_concurrency: Max active jobs allowed across a routing group
            on_start: Hook called before execution
            on_success: Hook called on success
            on_failure: Hook called on failure
            on_retry: Hook called before retry
            on_complete: Hook called after completion (success or failure)

        Returns:
            TaskDefinition with all metadata
        """
        if name in self._tasks:
            raise ValueError(f"Task '{name}' is already registered")

        definition = TaskDefinition(
            name=name,
            display_name=display_name or name,
            func=func,
            is_async=asyncio.iscoroutinefunction(func),
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
        )

        self._tasks[name] = definition
        return definition

    def register_event(
        self,
        key: str,
        display_name: str,
        func: Callable[..., Any],
        *,
        event: str,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float = 30 * 60,  # 30 minutes
        rate_limit: str | None = None,
        max_concurrency: int | None = None,
        routing_group: str | None = None,
        group_max_concurrency: int | None = None,
    ) -> EventDefinition:
        """Register an event."""
        event_pattern = event.strip()
        if not event_pattern:
            raise ValueError("event must be a non-empty pattern string")

        normalized_name = display_name.strip()
        if not normalized_name:
            raise ValueError("display_name must be a non-empty string")

        if key in self._tasks:
            raise ValueError(f"Task '{key}' is already registered")

        definition = EventDefinition(
            event=event_pattern,
            key=key,
            display_name=normalized_name,
            func=func,
            is_async=asyncio.iscoroutinefunction(func),
            retries=retries,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            timeout=timeout,
            rate_limit=rate_limit,
            max_concurrency=max_concurrency,
            routing_group=routing_group,
            group_max_concurrency=group_max_concurrency,
        )

        # Register by key for worker lookup (with retry/timeout config)
        self._tasks[key] = TaskDefinition(
            name=key,
            display_name=normalized_name,
            func=func,
            is_async=asyncio.iscoroutinefunction(func),
            retries=retries,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            timeout=timeout,
            rate_limit=rate_limit,
            max_concurrency=max_concurrency,
            routing_group=routing_group,
            group_max_concurrency=group_max_concurrency,
        )

        # Register by event pattern for routing
        if event_pattern not in self._events:
            self._events[event_pattern] = []
        self._events[event_pattern].append(definition)

        return definition

    def register_cron(
        self,
        *,
        key: str,
        display_name: str,
        schedule: str,
        func: Callable[..., Any],
        timeout: float = 30 * 60,  # 30 minutes
        missed_run_policy: MissedRunPolicy = MissedRunPolicy.LATEST_ONLY,
        max_catch_up_seconds: float | None = None,
    ) -> CronDefinition:
        """Register a cron job."""
        if key in self._crons:
            raise ValueError(f"Cron job '{key}' is already registered")

        definition = CronDefinition(
            key=key,
            display_name=display_name,
            schedule=schedule,
            func=func,
            is_async=asyncio.iscoroutinefunction(func),
            timeout=timeout,
            missed_run_policy=missed_run_policy,
            max_catch_up_seconds=max_catch_up_seconds,
        )

        self._crons[key] = definition
        return definition

    def register_app(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        port: int | None = 8080,
        external: bool = False,
        replicas: int = 1,
        cpu: float | None = None,
        memory: str | None = None,
        health_check: str | None = "/health",
    ) -> AppDefinition:
        """
        Register a long-running app/service.

        Args:
            name: Unique app name
            func: App factory function (returns ASGI/WSGI app or runs forever)
            port: HTTP port (None = no HTTP, background process)
            external: Expose to public internet (default: False)
            replicas: Number of instances (ignored locally)
            cpu: CPU cores (ignored locally)
            memory: Memory limit, e.g., "512Mi" (ignored locally)
            health_check: Health check endpoint path (for HTTP apps)

        Returns:
            AppDefinition with all metadata
        """
        if name in self._apps:
            raise ValueError(f"App '{name}' is already registered")

        definition = AppDefinition(
            name=name,
            func=func,
            is_async=asyncio.iscoroutinefunction(func),
            port=port,
            external=external,
            replicas=replicas,
            cpu=cpu,
            memory=memory,
            health_check=health_check,
        )

        self._apps[name] = definition
        return definition

    def get_task(self, name: str) -> TaskDefinition | None:
        """Get a registered task by stable key."""
        return self._tasks.get(name)

    def get_events_for_event_name(self, name: str) -> list[EventDefinition]:
        """
        Get all events matching an event name.

        Supports wildcard patterns (e.g., "user.*" matches "user.signup").
        """
        matching: list[EventDefinition] = []

        for pattern, handlers in self._events.items():
            if matches_event_pattern(name, pattern):
                matching.extend(handlers)

        return matching

    def get_cron(self, name: str) -> CronDefinition | None:
        """Get a registered cron job by stable key."""
        return self._crons.get(name)

    def get_app(self, name: str) -> AppDefinition | None:
        """Get a registered app by name."""
        return self._apps.get(name)

    @property
    def tasks(self) -> dict[str, TaskDefinition]:
        """Get all registered tasks."""
        return dict(self._tasks)

    @property
    def events(self) -> dict[str, list[EventDefinition]]:
        """Get all registered events."""
        return dict(self._events)

    @property
    def crons(self) -> dict[str, CronDefinition]:
        """Get all registered cron jobs."""
        return dict(self._crons)

    @property
    def apps(self) -> dict[str, AppDefinition]:
        """Get all registered apps."""
        return dict(self._apps)

    def clear(self) -> None:
        """Clear all registrations (useful for testing)."""
        self._tasks.clear()
        self._events.clear()
        self._crons.clear()
        self._apps.clear()

    def get_task_names(self) -> list[str]:
        """Get all registered task keys."""
        return list(self._tasks.keys())
