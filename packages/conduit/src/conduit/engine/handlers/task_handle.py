from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable, Generic, ParamSpec

from shared.models import Job

from conduit.engine.queue.base import BaseQueue
from conduit.engine.registry import TaskDefinition
from conduit.sdk.context import Context, get_current_context, set_current_context
from conduit.sdk.task import Future, TaskResult

if TYPE_CHECKING:
    from conduit.sdk.worker import Worker

logger = logging.getLogger(__name__)

P = ParamSpec("P")


class TaskHandle(Generic[P]):
    """Handle for a registered task, allowing typed .submit() and .wait() calls.

    The type parameter P represents the parameters needed to call the task.
    Use get_current_context() inside the task to access the runtime context.
    """

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        definition: TaskDefinition,
        _worker: Worker,
        _queue: BaseQueue | None = None,
    ) -> None:
        self.name = name
        self.func = func
        self.definition = definition
        self._worker = _worker
        self._queue = _queue
        # Copy function metadata for better IDE support
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__

    def _create_job(self, kwargs: dict[str, Any]) -> Job:
        """Create a Job from this task's definition.

        Automatically sets parent_id if called from inside a running task.
        """
        job = Job(
            function=self.name,
            kwargs=kwargs,
            timeout=self.definition.timeout,
            max_retries=self.definition.retries,
        )
        try:
            parent_ctx = get_current_context()
            job.metadata["parent_id"] = parent_ctx.job_id
        except RuntimeError:
            pass  # Not inside a task — no parent
        return job

    def _ensure_queue(self) -> BaseQueue:
        """Get the queue, raising if worker not started."""
        if self._queue is None:
            raise RuntimeError("Worker not started. Call worker.start() first.")
        return self._queue

    async def submit(self, *args: P.args, **kwargs: P.kwargs) -> Future[Any]:
        """Submit task for background execution, return a Future.

        Parameters are typed based on the original function signature.
        """
        queue = self._ensure_queue()
        # Convert positional args to kwargs based on function signature
        merged_kwargs = self._merge_args_kwargs(args, kwargs)
        job = self._create_job(merged_kwargs)
        job_id = await queue.enqueue(job)
        return Future(job_id=job_id, queue=queue)

    async def wait(self, *args: P.args, **kwargs: P.kwargs) -> TaskResult[Any]:
        """Submit and wait for a job to complete, returning the result.

        Parameters are typed based on the original function signature.
        """
        future = await self.submit(*args, **kwargs)
        return await future.result()

    def submit_sync(self, *args: P.args, **kwargs: P.kwargs) -> Future[Any]:
        """Submit task for background execution from a sync context.

        Blocks until the job is enqueued and returns a Future.
        Cannot be called from inside a running event loop.
        """
        return asyncio.run(self.submit(*args, **kwargs))

    def wait_sync(self, *args: P.args, **kwargs: P.kwargs) -> TaskResult[Any]:
        """Submit and wait for completion from a sync context.

        Blocks until the job completes and returns the result.
        Cannot be called from inside a running event loop.
        """
        return asyncio.run(self.wait(*args, **kwargs))

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
        job = Job(function=self.name, kwargs=merged_kwargs)
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
