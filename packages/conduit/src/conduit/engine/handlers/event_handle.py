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
    TypeVar,
    overload,
)

from shared.models import Job

from conduit.engine.queue.base import BaseQueue

if TYPE_CHECKING:
    from conduit.sdk.worker import Worker

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])
P = ParamSpec("P")


@dataclass
class _Handler:
    """Internal: a single subscriber to an event."""

    name: str
    func: Callable[..., Any]
    is_async: bool
    retries: int = 0
    retry_delay: float = 1.0
    retry_backoff: float = 2.0


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

    def send_sync(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """Send the event synchronously with typed parameters."""
        asyncio.run(self.send(*args, **kwargs))


@dataclass
class EventHandle:
    """
    An event that handlers can subscribe to via .on decorator.

    Event handlers work like tasks - send kwargs are passed directly
    to the handler. Use get_current_context() inside handlers for context access.

    The @event.on decorator returns a TypedEvent with the handler's
    parameter types, giving you full IDE autocomplete on .send().

    Example:
        from conduit import get_current_context

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
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
    ) -> Callable[[Callable[P, Any]], TypedEvent[P]]: ...

    def on(
        self,
        __func: Callable[..., Any] | None = None,
        *,
        retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
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
            handler = _Handler(
                name=fn.__name__,
                func=fn,
                is_async=asyncio.iscoroutinefunction(fn),
                retries=retries,
                retry_delay=retry_delay,
                retry_backoff=retry_backoff,
            )
            self._handlers.append(handler)

            # Register as a task so the job processor can execute it
            self._worker._registry.register_task(
                name=handler.name,
                func=handler.func,
                retries=handler.retries,
                retry_delay=handler.retry_delay,
                retry_backoff=handler.retry_backoff,
            )

            # Return typed event for this handler
            return TypedEvent(self, fn)

        if __func is not None:
            return decorator(__func)
        return decorator

    async def _enqueue_handlers(self, data: dict[str, Any]) -> None:
        """Enqueue all handlers for this event."""
        queue = self._ensure_queue()
        for handler in self._handlers:
            # Pass event data directly as kwargs (like tasks)
            job = Job(
                function=handler.name,
                kwargs=data,
            )
            try:
                await queue.enqueue(job)
            except Exception as e:
                logger.error(
                    f"Failed to enqueue handler '{handler.name}' "
                    f"for event '{self.pattern}': {e}"
                )

    async def send(self, **data: Any) -> None:
        """Send event, enqueuing all handlers.

        Awaitable — returns once all handlers are enqueued.
        """
        await self._enqueue_handlers(data)

    def send_sync(self, **data: Any) -> None:
        """Send event from a sync context.

        Blocks until all handlers are enqueued.
        Cannot be called from inside a running event loop.
        """
        asyncio.run(self._enqueue_handlers(data))

    @property
    def handler_names(self) -> list[str]:
        """Names of all registered handlers."""
        return [h.name for h in self._handlers]

    def __repr__(self) -> str:
        return f"EventHandle(pattern={self.pattern!r}, handlers={len(self._handlers)})"
