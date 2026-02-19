from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Awaitable, Callable, cast

from redis import Redis

from ..models import BenchmarkConfig


def now() -> float:
    return time.perf_counter()


def effective_prefetch(cfg: BenchmarkConfig) -> int:
    if cfg.consumer_prefetch > 0:
        return cfg.consumer_prefetch
    return max(1, cfg.concurrency)


def ensure_redis(redis_url: str) -> None:
    client = Redis.from_url(redis_url, decode_responses=False)
    try:
        client.ping()
    finally:
        client.close()


def wait_for_counter_sync(
    client: Redis,
    key: str,
    target: int,
    *,
    timeout_seconds: float,
) -> None:
    deadline = now() + timeout_seconds
    while now() < deadline:
        raw_done = cast(Any, client.get(key))
        done = int(raw_done or 0)
        if done >= target:
            return
        time.sleep(0.01)
    raise TimeoutError(f"Timed out waiting for {target} completions on key '{key}'")


async def wait_for_counter_async(
    client: Any,  # redis.asyncio.Redis
    key: str,
    target: int,
    *,
    timeout_seconds: float,
) -> None:
    deadline = now() + timeout_seconds
    while now() < deadline:
        done = int((await client.get(key)) or 0)
        if done >= target:
            return
        await asyncio.sleep(0.01)
    raise TimeoutError(f"Timed out waiting for {target} completions on key '{key}'")


async def async_produce_jobs(
    *,
    total_jobs: int,
    producer_concurrency: int,
    submit_one: Callable[[int], Awaitable[Any]],
) -> tuple[float, list[float]]:
    if producer_concurrency <= 1:
        serial_latencies: list[float] = []
        enqueue_start = now()
        for idx in range(total_jobs):
            t0 = now()
            await submit_one(idx)
            serial_latencies.append(now() - t0)
        return now() - enqueue_start, serial_latencies

    queue: asyncio.Queue[int | None] = asyncio.Queue()
    for idx in range(total_jobs):
        queue.put_nowait(idx)
    for _ in range(producer_concurrency):
        queue.put_nowait(None)

    latency_lock = asyncio.Lock()
    latencies: list[float] = []

    async def producer() -> None:
        local: list[float] = []
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                break
            t0 = now()
            await submit_one(item)
            local.append(now() - t0)
            queue.task_done()
        if local:
            async with latency_lock:
                latencies.extend(local)

    workers = [asyncio.create_task(producer()) for _ in range(producer_concurrency)]
    enqueue_start = now()
    await queue.join()
    await asyncio.gather(*workers)
    return now() - enqueue_start, latencies


async def async_produce_jobs_sustained(
    *,
    total_jobs: int,
    arrival_rate: float,
    producer_concurrency: int,
    submit_one: Callable[[int], Awaitable[Any]],
) -> tuple[float, list[float]]:
    if total_jobs <= 0:
        return 0.0, []
    if arrival_rate <= 0:
        raise ValueError("arrival_rate must be > 0 for sustained producer")

    producer_concurrency = max(1, producer_concurrency)
    semaphore = asyncio.Semaphore(producer_concurrency)
    latency_lock = asyncio.Lock()
    latencies: list[float] = []
    pending: list[asyncio.Task[None]] = []

    async def timed_submit(idx: int) -> None:
        async with semaphore:
            t0 = now()
            await submit_one(idx)
            latency = now() - t0
            async with latency_lock:
                latencies.append(latency)

    enqueue_start = now()
    for idx in range(total_jobs):
        due_at = enqueue_start + (idx / arrival_rate)
        sleep_for = due_at - now()
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
        pending.append(asyncio.create_task(timed_submit(idx)))

    if pending:
        await asyncio.gather(*pending)
    return now() - enqueue_start, latencies


def threaded_produce_jobs(
    *,
    total_jobs: int,
    producer_concurrency: int,
    submit_one: Callable[[int], None],
) -> tuple[float, list[float]]:
    if producer_concurrency <= 1:
        serial_latencies: list[float] = []
        enqueue_start = now()
        for idx in range(total_jobs):
            t0 = now()
            submit_one(idx)
            serial_latencies.append(now() - t0)
        return now() - enqueue_start, serial_latencies

    def timed_submit(idx: int) -> float:
        t0 = now()
        submit_one(idx)
        return now() - t0

    enqueue_start = now()
    latencies: list[float] = []
    with ThreadPoolExecutor(max_workers=producer_concurrency) as pool:
        futures = [pool.submit(timed_submit, idx) for idx in range(total_jobs)]
        for future in as_completed(futures):
            latencies.append(float(future.result()))
    return now() - enqueue_start, latencies


def threaded_produce_jobs_sustained(
    *,
    total_jobs: int,
    arrival_rate: float,
    producer_concurrency: int,
    submit_one: Callable[[int], None],
) -> tuple[float, list[float]]:
    if total_jobs <= 0:
        return 0.0, []
    if arrival_rate <= 0:
        raise ValueError("arrival_rate must be > 0 for sustained producer")

    producer_concurrency = max(1, producer_concurrency)

    def timed_submit(idx: int) -> float:
        t0 = now()
        submit_one(idx)
        return now() - t0

    enqueue_start = now()
    latencies: list[float] = []
    with ThreadPoolExecutor(max_workers=producer_concurrency) as pool:
        futures = []
        for idx in range(total_jobs):
            due_at = enqueue_start + (idx / arrival_rate)
            sleep_for = due_at - now()
            if sleep_for > 0:
                time.sleep(sleep_for)
            futures.append(pool.submit(timed_submit, idx))
        for future in as_completed(futures):
            latencies.append(float(future.result()))
    return now() - enqueue_start, latencies


def record_queue_wait_sync(
    client: Redis,
    key: str,
    wait_ms: float,
    *,
    max_samples: int,
) -> None:
    if max_samples <= 0:
        return
    pipe = client.pipeline(transaction=False)
    pipe.lpush(key, f"{wait_ms:.6f}")
    pipe.ltrim(key, 0, max_samples - 1)
    pipe.execute()


async def record_queue_wait_async(
    client: Any,  # redis.asyncio.Redis
    key: str,
    wait_ms: float,
    *,
    max_samples: int,
) -> None:
    if max_samples <= 0:
        return
    pipe = client.pipeline(transaction=False)
    pipe.lpush(key, f"{wait_ms:.6f}")
    pipe.ltrim(key, 0, max_samples - 1)
    await pipe.execute()


def load_queue_wait_samples_sync(client: Redis, key: str) -> list[float]:
    rows = cast(list[bytes], client.lrange(key, 0, -1))
    out: list[float] = []
    for row in rows:
        try:
            out.append(float(row.decode()))
        except Exception:
            continue
    return out


async def load_queue_wait_samples_async(client: Any, key: str) -> list[float]:
    rows = await client.lrange(key, 0, -1)
    out: list[float] = []
    for row in rows:
        try:
            if isinstance(row, bytes):
                out.append(float(row.decode()))
            else:
                out.append(float(row))
        except Exception:
            continue
    return out
