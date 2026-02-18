from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable, Generic, ParamSpec, TypeVar, overload

from shared.domain import Job

from upnext.engine.handlers.idempotency import normalize_idempotency_key
from upnext.engine.queue.base import BaseQueue
from upnext.engine.registry import TaskDefinition
from upnext.sdk.context import Context, get_current_context, set_current_context
from upnext.sdk.task import Future, TaskResult

if TYPE_CHECKING:
    from upnext.sdk.worker import Worker

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class TaskHandle(Generic[P, T]):
    """Handle for a registered task, allowing typed .submit() and .wait() calls.

    The type parameter P represents the parameters needed to call the task.
    Use get_current_context() inside the task to access the runtime context.
    """

    def __init__(
        self,
        name: str,
        function_key: str,
        func: Callable[..., Any],
        definition: TaskDefinition,
        _worker: Worker,
        _queue: BaseQueue | None = None,
    ) -> None:
        self.name = name
        self.function_key = function_key
        self.func = func
        self.definition = definition
        self._worker = _worker
        self._queue = _queue
        # Copy function metadata for better IDE support
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__

    def _create_job(
        self,
        kwargs: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> Job:
        """Create a Job from this task's definition.

        Automatically sets lineage if called from inside a running task.
        """
        normalized_key = (
            normalize_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else ""
        )
        job = Job(
            function=self.function_key,
            function_name=self.name,
            kwargs=kwargs,
            key=normalized_key,
            timeout=self.definition.timeout,
            max_retries=self.definition.retries,
        )
        try:
            parent_ctx = get_current_context()
            job.parent_id = parent_ctx.job_id
            job.root_id = parent_ctx.root_id or parent_ctx.job_id
        except RuntimeError:
            # Top-level tasks are their own root.
            job.root_id = job.id
        return job

    def _ensure_queue(self) -> BaseQueue:
        """Get the queue, raising if worker not started."""
        if self._queue is None:
            raise RuntimeError("Worker not started. Call worker.start() first.")
        return self._queue

    async def _enqueue_future(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> Future[T]:
        queue = self._ensure_queue()
        merged_kwargs = self._merge_args_kwargs(args, kwargs)
        job = self._create_job(merged_kwargs, idempotency_key=idempotency_key)
        job_id = await queue.enqueue(job)
        return Future(job_id=job_id, queue=queue)

    async def submit(self, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        """Submit task for background execution, return a Future.

        Parameters are typed based on the original function signature.
        """
        return await self._enqueue_future(args, dict(kwargs))

    async def submit_idempotent(
        self,
        idempotency_key: str,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> Future[T]:
        """Submit task using a caller-supplied idempotency key."""
        return await self._enqueue_future(
            args,
            dict(kwargs),
            idempotency_key=idempotency_key,
        )

    @overload
    async def wait(self, *args: P.args, **kwargs: P.kwargs) -> TaskResult[T]: ...

    @overload
    async def wait(
        self,
        *args: Any,
        wait_timeout: float | None = None,
        **kwargs: Any,
    ) -> TaskResult[T]: ...

    async def wait(
        self,
        *args: Any,
        wait_timeout: float | None = None,
        **kwargs: Any,
    ) -> TaskResult[T]:
        """Submit and wait for a job to complete, returning the result.

        Parameters are typed based on the original function signature.
        By default, wait timeout matches the task definition timeout.
        Raises if the job finishes with failed/cancelled status.
        """
        future = await self._enqueue_future(args, kwargs)
        timeout = self.definition.timeout if wait_timeout is None else wait_timeout
        return await future.result(timeout=timeout)

    async def wait_idempotent(
        self,
        idempotency_key: str,
        *args: Any,
        wait_timeout: float | None = None,
        **kwargs: Any,
    ) -> TaskResult[T]:
        """Submit with idempotency key and wait for completion.

        Raises if the job finishes with failed/cancelled status.
        """
        future = await self._enqueue_future(
            args,
            kwargs,
            idempotency_key=idempotency_key,
        )
        timeout = self.definition.timeout if wait_timeout is None else wait_timeout
        return await future.result(timeout=timeout)

    def submit_sync(self, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        """Submit task for background execution from a sync context.

        Blocks until the job is enqueued and returns a Future.
        Cannot be called from inside a running event loop.
        """
        return asyncio.run(self.submit(*args, **kwargs))

    def submit_idempotent_sync(
        self,
        idempotency_key: str,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> Future[T]:
        """Submit task with idempotency key from a sync context."""
        return asyncio.run(self.submit_idempotent(idempotency_key, *args, **kwargs))

    @overload
    def wait_sync(self, *args: P.args, **kwargs: P.kwargs) -> TaskResult[T]: ...

    @overload
    def wait_sync(
        self,
        *args: Any,
        wait_timeout: float | None = None,
        **kwargs: Any,
    ) -> TaskResult[T]: ...

    def wait_sync(
        self,
        *args: Any,
        wait_timeout: float | None = None,
        **kwargs: Any,
    ) -> TaskResult[T]:
        """Submit and wait for completion from a sync context.

        Blocks until the job completes and returns the result.
        Cannot be called from inside a running event loop.
        """
        return asyncio.run(self.wait(*args, wait_timeout=wait_timeout, **kwargs))

    def wait_idempotent_sync(
        self,
        idempotency_key: str,
        *args: Any,
        wait_timeout: float | None = None,
        **kwargs: Any,
    ) -> TaskResult[T]:
        """Submit with idempotency key and wait from a sync context."""
        return asyncio.run(
            self.wait_idempotent(
                idempotency_key,
                *args,
                wait_timeout=wait_timeout,
                **kwargs,
            )
        )

    def _merge_args_kwargs(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge positional args into kwargs based on function signature."""
        sig = inspect.signature(self.func)
        params = list(sig.parameters.keys())
        # Convert positional args to kwargs
        merged = dict(kwargs)
        for i, arg in enumerate(args):
            if i < len(params):
                merged[params[i]] = arg
        return merged

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        """Direct call - execute inline (for testing/debugging).

        If no event loop is running, uses ``asyncio.run()`` for async tasks.
        If an event loop is already running (pytest-asyncio, Jupyter, etc.),
        raises a clear error directing the caller to ``await submit()`` or
        ``await wait()`` instead.
        """
        merged_kwargs = self._merge_args_kwargs(args, kwargs)
        job = Job(
            function=self.function_key,
            function_name=self.name,
            kwargs=merged_kwargs,
        )
        ctx = Context.from_job(job)
        set_current_context(ctx)

        try:
            if self.definition.is_async:
                # Check for a running event loop
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    pass  # No loop running — safe to use asyncio.run()
                else:
                    raise RuntimeError(
                        f"Cannot call {self.name}() directly inside a running "
                        f"event loop. Use 'await {self.name}.submit()' or "
                        f"'await {self.name}.wait()' instead."
                    )

                return asyncio.run(self.func(**merged_kwargs))
            else:
                return self.func(**merged_kwargs)
        finally:
            set_current_context(None)
