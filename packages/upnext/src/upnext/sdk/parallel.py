"""Parallel execution primitives for UpNext."""

import asyncio
from collections.abc import Awaitable
from typing import Any, Protocol, cast

from upnext.sdk.task import Future, TaskResult


class SubmittableTask[T](Protocol):
    """Protocol for tasks that can be submitted."""

    async def submit(self, **kwargs: Any) -> Future[T]: ...


def _require_task_value[T](future_result: TaskResult[T]) -> T:
    """Extract a successful task value or raise an explicit error."""
    if not getattr(future_result, "ok", False):
        raise RuntimeError(getattr(future_result, "error", "Task failed"))
    value = future_result.value
    if value is None:
        raise RuntimeError("Task completed without a value")
    return cast(T, value)


async def gather[T](
    *awaitables: Awaitable[T] | Future[T],
    return_exceptions: bool = False,
) -> list[T]:
    """
    Execute multiple tasks concurrently, wait for all.

    Similar to asyncio.gather() but works with both awaitables and UpNext Futures.

    Example:
        user, orders, notifications = await gather(
            fetch_user(user_id="123"),
            fetch_orders(user_id="123"),
            fetch_notifications(user_id="123"),
        )

    Args:
        *awaitables: Coroutines or Futures to execute concurrently
        return_exceptions: If True, exceptions are returned instead of raised

    Returns:
        List of results in the same order as input

    Raises:
        Exception: First exception encountered (if return_exceptions=False)
    """

    async def resolve(item: Awaitable[T] | Future[T]) -> T:
        if isinstance(item, Future):
            task_result = await item.result()
            return _require_task_value(task_result)
        return await item

    tasks = [asyncio.create_task(resolve(a)) for a in awaitables]

    if return_exceptions:
        results: list[T | BaseException] = []
        for task in tasks:
            try:
                results.append(await task)
            except Exception as e:
                results.append(e)
        return results  # type: ignore[return-value]

    return list(await asyncio.gather(*tasks))


async def map_tasks[T](
    task: SubmittableTask[T],
    inputs: list[dict[str, Any]],
    *,
    concurrency: int = 10,
) -> list[T]:
    """
    Execute a task over multiple inputs with concurrency control.

    Example:
        results = await map_tasks(
            process_item,  # TaskHandle from @worker.task()
            [{"item_id": i} for i in range(1000)],
            concurrency=10,
        )

    Args:
        task: Task handle (from @worker.task()) to execute
        inputs: List of kwargs dicts to pass to the task
        concurrency: Maximum number of concurrent executions

    Returns:
        List of results in the same order as inputs
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[T] = [cast(T, None)] * len(inputs)

    async def run_with_semaphore(index: int, kwargs: dict[str, Any]) -> None:
        async with semaphore:
            future = await task.submit(**kwargs)
            task_result = await future.result()
            results[index] = _require_task_value(task_result)

    tasks = [
        asyncio.create_task(run_with_semaphore(i, kwargs))
        for i, kwargs in enumerate(inputs)
    ]

    await asyncio.gather(*tasks)
    return results


async def first_completed[T](
    *awaitables: Awaitable[T] | Future[T],
    timeout: float | None = None,
) -> T:
    """
    Return first result, cancel the rest.

    Useful for racing multiple providers or implementations.

    Example:
        result = await first_completed(
            fetch_from_provider_a(query),
            fetch_from_provider_b(query),
            fetch_from_provider_c(query),
        )

    Args:
        *awaitables: Coroutines or Futures to race
        timeout: Maximum time to wait for any result

    Returns:
        Result from the first completed task

    Raises:
        TimeoutError: If timeout reached before any completion
        Exception: If all tasks fail
    """

    async def resolve(item: Awaitable[T] | Future[T]) -> T:
        if isinstance(item, Future):
            task_result = await item.result()
            return _require_task_value(task_result)
        return await item

    tasks = [asyncio.create_task(resolve(a)) for a in awaitables]

    try:
        done, pending = await asyncio.wait(
            tasks,
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if not done:
            raise TimeoutError("Timeout waiting for first completed task")

        # Get the first completed result
        first_task = next(iter(done))

        # Cancel remaining tasks
        for task in pending:
            task.cancel()

        # Wait for cancellations to complete
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        # Return result (may raise if the task failed)
        return first_task.result()

    except Exception:
        # Cancel all tasks on error
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def submit_many[T](
    task: SubmittableTask[T],
    inputs: list[dict[str, Any]],
) -> list[Future[T]]:
    """
    Submit multiple jobs for background execution.

    Unlike map_tasks(), this returns immediately with Futures
    instead of waiting for results.

    Example:
        futures = await submit_many(
            process_item,  # TaskHandle from @worker.task()
            [{"item_id": i} for i in range(1000)],
        )

        # Wait for all results later
        results = await gather(*futures)

    Args:
        task: Task handle (from @worker.task()) to submit
        inputs: List of kwargs dicts to pass to the task

    Returns:
        List of Futures in the same order as inputs
    """
    futures: list[Future[T]] = []
    for kwargs in inputs:
        future = await task.submit(**kwargs)
        futures.append(future)
    return futures
