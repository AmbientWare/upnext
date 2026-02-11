from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    ParamSpec,
    TypedDict,
    TypeVar,
    overload,
)

from shared.models import Job
from upnext.engine.handlers.idempotency import normalize_idempotency_key
from upnext.engine.function_identity import build_function_key
from upnext.engine.queue.base import BaseQueue

if TYPE_CHECKING:
    from upnext.sdk.worker import Worker

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])
P = ParamSpec("P")


@dataclass
class _Handler:
    """Internal: a single subscriber to an event."""

    key: str
    display_name: str
    func: Callable[..., Any]
    is_async: bool
    retries: int = 0
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    timeout: float = 30 * 60  # 30 minutes
    rate_limit: str | None = None
    max_concurrency: int | None = None
    routing_group: str | None = None
    group_max_concurrency: int | None = None


class HandlerConfig(TypedDict):
    """Serializable handler config used for worker registration metadata."""

    key: str
    name: str
    timeout: float
    max_retries: int
    retry_delay: float
    rate_limit: str | None
    max_concurrency: int | None
    routing_group: str | None
    group_max_concurrency: int | None


class TypedEvent(Generic[P]):
    """Typed event that preserves the handler's parameter types."""

    def __init__(self, event: EventHandle, func: Callable[..., Any]) -> None:
        self._event = event
        self._func = func
        # Copy function metadata for better IDE support
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__

    async def send(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """Deliver the event with typed parameters."""
        # Merge positional args into kwargs based on function signature
        import inspect

        sig = inspect.signature(self._func)
        params = list(sig.parameters.keys())
        # Convert positional args to kwargs
        for i, arg in enumerate(args):
            if i < len(params):
                kwargs[params[i]] = arg
        await self._event._enqueue_handlers(kwargs)

    async def send_idempotent(
        self,
        idempotency_key: str,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        """Deliver event with typed parameters and idempotency key."""
        import inspect

        sig = inspect.signature(self._func)
        params = list(sig.parameters.keys())
        for i, arg in enumerate(args):
            if i < len(params):
                kwargs[params[i]] = arg
        await self._event._enqueue_handlers(kwargs, idempotency_key=idempotency_key)

    def send_sync(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """Send the event synchronously with typed parameters."""
        asyncio.run(self.send(*args, **kwargs))

    def send_idempotent_sync(
        self,
        idempotency_key: str,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        """Send the event synchronously with idempotency key."""
        asyncio.run(self.send_idempotent(idempotency_key, *args, **kwargs))


@dataclass
class EventHandle:
    """
    An event that handlers can subscribe to via .on decorator.

    Event handlers work like tasks - send kwargs are passed directly
    to the handler. Use get_current_context() inside handlers for context access.

    The @event.on decorator returns a TypedEvent with the handler's
    parameter types, giving you full IDE autocomplete on .send().

    Example:
        from upnext import get_current_context

        order_placed = worker.event("order.placed")

        # The decorator returns a typed event
        @order_placed.on
        async def send_confirmation(order_id: str):
            print(f"Order {order_id} placed!")

        # Now send_confirmation.send() knows it needs order_id: str
        await send_confirmation.send(order_id="123")  # ✓ Typed!

        # With context access
        @order_placed.on(retries=3)
        async def update_inventory(order_id: str):
            ctx = get_current_context()
            ctx.set_progress(50, "Updating inventory...")

        # You can also use the event's send (untyped, sends to all handlers)
        await order_placed.send(order_id="123")
    """

    pattern: str
    _worker: Worker
    _handlers: list[_Handler] = field(default_factory=list, init=False)
    _queue: BaseQueue | None = field(default=None, init=False)

    def _ensure_queue(self) -> BaseQueue:
        if self._queue is None:
            raise RuntimeError("Worker not started. Call worker.start() first.")
        return self._queue

    # Overload for bare decorator: @event.on
    @overload
    def on(self, __func: Callable[P, Any]) -> TypedEvent[P]: ...

    # Overload for decorator factory: @event.on() or @event.on(retries=3)
    @overload
    def on(
        self,
        __func: None = None,
        *,
        name: str | None = None,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float = 30 * 60,  # 30 minutes
        rate_limit: str | None = None,
        max_concurrency: int | None = None,
        routing_group: str | None = None,
        group_max_concurrency: int | None = None,
    ) -> Callable[[Callable[P, Any]], TypedEvent[P]]: ...

    def on(
        self,
        __func: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        timeout: float = 30 * 60,  # 30 minutes
        rate_limit: str | None = None,
        max_concurrency: int | None = None,
        routing_group: str | None = None,
        group_max_concurrency: int | None = None,
    ) -> Any:
        """
        Subscribe a handler to this event.

        Returns a TypedEvent with the handler's parameter types,
        so .send() has proper IDE autocomplete.

        Handlers receive send kwargs directly (like tasks).
        Use get_current_context() for context access.

            @my_event.on
            async def handler(order_id: str): ...
            # handler.send(order_id="123") is now typed!

            @my_event.on(retries=3)
            async def handler(**kwargs):
                ctx = get_current_context()
                ...
        """

        def decorator(fn: Callable[..., Any]) -> TypedEvent[Any]:
            handler_name = name or fn.__name__
            handler = _Handler(
                key=build_function_key(
                    "event",
                    module=fn.__module__,
                    qualname=fn.__qualname__,
                    name=handler_name,
                    pattern=self.pattern,
                ),
                display_name=handler_name,
                func=fn,
                is_async=asyncio.iscoroutinefunction(fn),
                retries=retries,
                retry_delay=retry_delay,
                retry_backoff=retry_backoff,
                timeout=timeout,
                rate_limit=rate_limit,
                max_concurrency=max_concurrency,
                routing_group=routing_group,
                group_max_concurrency=group_max_concurrency,
            )
            self._handlers.append(handler)

            # Register as a task so the job processor can execute it
            self._worker._registry.register_task(
                name=handler.key,
                display_name=handler.display_name,
                func=handler.func,
                retries=handler.retries,
                retry_delay=handler.retry_delay,
                retry_backoff=handler.retry_backoff,
                timeout=handler.timeout,
                rate_limit=handler.rate_limit,
                max_concurrency=handler.max_concurrency,
                routing_group=handler.routing_group,
                group_max_concurrency=handler.group_max_concurrency,
            )

            # Return typed event for this handler
            return TypedEvent(self, fn)

        if __func is not None:
            return decorator(__func)
        return decorator

    async def _enqueue_handlers(
        self,
        data: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> None:
        """Enqueue all handlers for this event."""
        queue = self._ensure_queue()
        normalized_key = (
            normalize_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else ""
        )
        for handler in self._handlers:
            # Pass event data directly as kwargs (like tasks)
            job = Job(
                function=handler.key,
                function_name=handler.display_name,
                kwargs=data,
                key=normalized_key,
                metadata={
                    "event_pattern": self.pattern,
                    "event_handler_key": handler.key,
                    "event_handler_name": handler.display_name,
                },
            )
            try:
                await queue.enqueue(job)
            except Exception as e:
                logger.error(
                    f"Failed to enqueue handler '{handler.display_name}' "
                    f"for event '{self.pattern}': {e}"
                )

    async def send(self, **data: Any) -> None:
        """Send event, enqueuing all handlers.

        Awaitable — returns once all handlers are enqueued.
        """
        await self._enqueue_handlers(data)

    async def send_idempotent(self, idempotency_key: str, **data: Any) -> None:
        """Send event with a caller-supplied idempotency key."""
        await self._enqueue_handlers(data, idempotency_key=idempotency_key)

    def send_sync(self, **data: Any) -> None:
        """Send event from a sync context.

        Blocks until all handlers are enqueued.
        Cannot be called from inside a running event loop.
        """
        asyncio.run(self._enqueue_handlers(data))

    def send_idempotent_sync(self, idempotency_key: str, **data: Any) -> None:
        """Send event with idempotency key from a sync context."""
        asyncio.run(self._enqueue_handlers(data, idempotency_key=idempotency_key))

    @property
    def handler_names(self) -> list[str]:
        """Display names of all registered handlers."""
        return [h.display_name for h in self._handlers]

    @property
    def handler_keys(self) -> list[str]:
        """Stable keys for all registered handlers."""
        return [h.key for h in self._handlers]

    def handler_configs(self) -> list[HandlerConfig]:
        """Handler config snapshots for worker registration/metadata export."""
        return [
            {
                "key": h.key,
                "name": h.display_name,
                "timeout": h.timeout,
                "max_retries": h.retries,
                "retry_delay": h.retry_delay,
                "rate_limit": h.rate_limit,
                "max_concurrency": h.max_concurrency,
                "routing_group": h.routing_group,
                "group_max_concurrency": h.group_max_concurrency,
            }
            for h in self._handlers
        ]

    def __repr__(self) -> str:
        return f"EventHandle(pattern={self.pattern!r}, handlers={len(self._handlers)})"
