from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, cast

from redis import Redis

from ..models import BenchmarkConfig, BenchmarkProfile


def now() -> float:
    return time.perf_counter()


def _percentile_ms(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = max(0, min(len(ordered) - 1, int(pct * (len(ordered) - 1))))
    return ordered[idx] * 1000.0


def p50_ms(samples: list[float]) -> float:
    return _percentile_ms(samples, 0.50)


def p95_ms(samples: list[float]) -> float:
    return _percentile_ms(samples, 0.95)


def p99_ms(samples: list[float]) -> float:
    return _percentile_ms(samples, 0.99)


def max_ms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return max(samples) * 1000.0


def effective_prefetch(cfg: BenchmarkConfig) -> int:
    if cfg.consumer_prefetch > 0:
        return cfg.consumer_prefetch
    if cfg.profile == BenchmarkProfile.DURABILITY:
        return 1
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
    submit_one: Callable[[], Any],
) -> tuple[float, list[float]]:
    if producer_concurrency <= 1:
        serial_latencies: list[float] = []
        enqueue_start = now()
        for _ in range(total_jobs):
            t0 = now()
            await submit_one()
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
            await submit_one()
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


def threaded_produce_jobs(
    *,
    total_jobs: int,
    producer_concurrency: int,
    submit_one: Callable[[], None],
) -> tuple[float, list[float]]:
    if producer_concurrency <= 1:
        serial_latencies: list[float] = []
        enqueue_start = now()
        for _ in range(total_jobs):
            t0 = now()
            submit_one()
            serial_latencies.append(now() - t0)
        return now() - enqueue_start, serial_latencies

    def timed_submit() -> float:
        t0 = now()
        submit_one()
        return now() - t0

    enqueue_start = now()
    latencies: list[float] = []
    with ThreadPoolExecutor(max_workers=producer_concurrency) as pool:
        futures = [pool.submit(timed_submit) for _ in range(total_jobs)]
        for future in as_completed(futures):
            latencies.append(float(future.result()))
    return now() - enqueue_start, latencies
