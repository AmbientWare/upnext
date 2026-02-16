"""Registration helpers for Worker.

Extracted from worker.py to separate decorator-based registration logic
from connection/lifecycle concerns.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar, overload

from shared.contracts import FunctionConfig, FunctionType, MissedRunPolicy

from upnext.engine.function_identity import build_function_key
from upnext.engine.handlers import EventHandle, TaskHandle
from upnext.engine.registry import CronDefinition, Registry

F = TypeVar("F", bound=Callable[..., Any])
P = ParamSpec("P")


@dataclass(frozen=True)
class FunctionCatalog:
    """Immutable snapshot of all registered functions."""

    function_keys: list[str]
    function_name_map: dict[str, str]
    function_definitions: list[FunctionConfig]


class WorkerRegistration:
    """Manages task, cron, and event registration for a Worker."""

    def __init__(self, name: str, registry: Registry) -> None:
        self._name = name
        self._registry = registry
        self._task_handles: dict[str, TaskHandle] = {}
        self._crons: list[CronDefinition] = []
        self._event_handles: dict[str, EventHandle] = {}

    @property
    def task_handles(self) -> dict[str, TaskHandle]:
        return self._task_handles

    @property
    def cron_definitions(self) -> list[CronDefinition]:
        return self._crons

    @property
    def event_handles(self) -> dict[str, EventHandle]:
        return self._event_handles

    # Overload for bare decorator: @worker.task
    @overload
    def task(
        self,
        __func: Callable[P, Any],
        *,
        _worker: Any = None,
    ) -> TaskHandle[P]: ...

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
        _worker: Any = None,
    ) -> Callable[[Callable[P, Any]], TaskHandle[P]]: ...

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
        _worker: Any = None,
    ) -> Any:
        """Register a task. Returns a TaskHandle with typed .submit()/.wait()."""

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
                    f"Task name '{task_name}' is already registered on worker '{self._name}'"
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
                max_concurrency=max_concurrency,
                routing_group=routing_group,
                group_max_concurrency=group_max_concurrency,
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
                _worker=_worker,
            )

            self._task_handles[task_name] = handle
            return handle

        if __func is not None:
            return decorator(__func)
        return decorator

    def cron(
        self,
        schedule: str,
        *,
        name: str | None = None,
        timeout: float = 30 * 60,
        missed_run_policy: MissedRunPolicy = MissedRunPolicy.LATEST_ONLY,
        max_catch_up_seconds: float | None = None,
    ) -> Callable[[F], F]:
        """Register a cron job."""

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
                missed_run_policy=missed_run_policy,
                max_catch_up_seconds=max_catch_up_seconds,
            )

            self._registry.register_task(
                name=function_key,
                display_name=cron_name,
                func=func,
                timeout=timeout,
            )

            self._crons.append(definition)
            return func

        return decorator

    def event(
        self, pattern: str, *, _worker: Any = None, _queue: Any = None
    ) -> EventHandle:
        """Create an event handle that handlers can subscribe to."""
        if not pattern.strip():
            raise ValueError("Event pattern must be a non-empty string")

        existing = self._event_handles.get(pattern)
        if existing is not None:
            return existing

        handle = EventHandle(pattern=pattern, _worker=_worker)
        if _queue is not None:
            handle._queue = _queue
        self._event_handles[pattern] = handle
        return handle

    def build_catalog(self) -> FunctionCatalog:
        """Build immutable snapshot of all registered functions."""
        function_keys: list[str] = []
        function_name_map: dict[str, str] = {}
        function_definitions: list[FunctionConfig] = []

        for display_name, handle in self._task_handles.items():
            function_key = handle.function_key
            function_keys.append(function_key)
            function_name_map[function_key] = display_name
            function_definitions.append(
                FunctionConfig(
                    key=function_key,
                    name=display_name,
                    type=FunctionType.TASK,
                    timeout=handle.definition.timeout,
                    max_retries=handle.definition.retries,
                    retry_delay=handle.definition.retry_delay,
                    rate_limit=handle.definition.rate_limit,
                    max_concurrency=handle.definition.max_concurrency,
                    routing_group=handle.definition.routing_group,
                    group_max_concurrency=handle.definition.group_max_concurrency,
                )
            )

        for cron_def in self._crons:
            if cron_def.key not in function_keys:
                function_keys.append(cron_def.key)
            function_name_map[cron_def.key] = cron_def.display_name
            function_definitions.append(
                FunctionConfig(
                    key=cron_def.key,
                    name=cron_def.display_name,
                    type=FunctionType.CRON,
                    schedule=cron_def.schedule,
                    timeout=cron_def.timeout,
                    missed_run_policy=cron_def.missed_run_policy,
                    max_catch_up_seconds=cron_def.max_catch_up_seconds,
                )
            )

        for handle in self._event_handles.values():
            for handler in handle.handler_configs():
                handler_key = handler["key"]
                if handler_key not in function_keys:
                    function_keys.append(handler_key)
                function_name_map[handler_key] = handler["name"]
                function_definitions.append(
                    FunctionConfig(
                        key=handler_key,
                        name=handler["name"],
                        type=FunctionType.EVENT,
                        pattern=handle.pattern,
                        timeout=handler["timeout"],
                        max_retries=handler["max_retries"],
                        retry_delay=handler["retry_delay"],
                        rate_limit=handler["rate_limit"],
                        max_concurrency=handler["max_concurrency"],
                        routing_group=handler["routing_group"],
                        group_max_concurrency=handler["group_max_concurrency"],
                    )
                )

        return FunctionCatalog(
            function_keys=function_keys,
            function_name_map=function_name_map,
            function_definitions=function_definitions,
        )
