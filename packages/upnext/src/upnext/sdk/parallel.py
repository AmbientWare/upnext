"""Parallel execution primitives for UpNext."""

import asyncio
from collections.abc import Awaitable
from typing import Any, Protocol, cast, overload

from upnext.sdk.task import Future, _require_task_value


class SubmittableTask[T](Protocol):
    """Protocol for tasks that can be submitted."""

    async def submit(self, **kwargs: Any) -> Future[T]: ...


@overload
async def gather[T1](
    a1: Awaitable[T1] | Future[T1],
    /,
    *,
    return_exceptions: bool = ...,
) -> list[T1]: ...


@overload
async def gather[T1, T2](
    a1: Awaitable[T1] | Future[T1],
    a2: Awaitable[T2] | Future[T2],
    /,
    *,
    return_exceptions: bool = ...,
) -> list[T1 | T2]: ...


@overload
async def gather[T1, T2, T3](
    a1: Awaitable[T1] | Future[T1],
    a2: Awaitable[T2] | Future[T2],
    a3: Awaitable[T3] | Future[T3],
    /,
    *,
    return_exceptions: bool = ...,
) -> list[T1 | T2 | T3]: ...


@overload
async def gather[T1, T2, T3, T4](
    a1: Awaitable[T1] | Future[T1],
    a2: Awaitable[T2] | Future[T2],
    a3: Awaitable[T3] | Future[T3],
    a4: Awaitable[T4] | Future[T4],
    /,
    *,
    return_exceptions: bool = ...,
) -> list[T1 | T2 | T3 | T4]: ...


@overload
async def gather[T1, T2, T3, T4, T5](
    a1: Awaitable[T1] | Future[T1],
    a2: Awaitable[T2] | Future[T2],
    a3: Awaitable[T3] | Future[T3],
    a4: Awaitable[T4] | Future[T4],
    a5: Awaitable[T5] | Future[T5],
    /,
    *,
    return_exceptions: bool = ...,
) -> list[T1 | T2 | T3 | T4 | T5]: ...


@overload
async def gather(
    *awaitables: Awaitable[Any] | Future[Any],
    return_exceptions: bool = ...,
) -> list[Any]: ...


async def gather(
    *awaitables: Awaitable[Any] | Future[Any],
    return_exceptions: bool = False,
) -> list[Any]:
    """Execute multiple tasks concurrently, wait for all."""

    async def resolve(item: Awaitable[Any] | Future[Any]) -> Any:
        if isinstance(item, Future):
            task_result = await item.result()
            return _require_task_value(task_result)
        return await item

    tasks = [asyncio.create_task(resolve(a)) for a in awaitables]

    if return_exceptions:
        results: list[Any] = []
        for task in tasks:
            try:
                results.append(await task)
            except Exception as e:
                results.append(e)
        return results

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
