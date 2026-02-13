from __future__ import annotations

import os
from time import perf_counter

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from shared.domain import Job, JobStatus
from upnext.engine.queue.redis.queue import RedisQueue


@pytest_asyncio.fixture
async def perf_redis() -> Redis:
    redis_url = os.getenv("UPNEXT_PERF_REDIS_URL", "redis://localhost:6379/15")
    client = Redis.from_url(redis_url, decode_responses=False)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"Redis not available for perf benchmark ({redis_url}): {exc}")

    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.mark.performance
@pytest.mark.integration
@pytest.mark.asyncio
async def test_perf_queue_idle_dequeue_avoids_busy_poll(
    perf_redis,
    monkeypatch,
) -> None:
    queue = RedisQueue(client=perf_redis, key_prefix="upnext-perf-idle")

    xreadgroup_calls = 0
    original_xreadgroup = perf_redis.xreadgroup

    async def tracked_xreadgroup(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal xreadgroup_calls
        xreadgroup_calls += 1
        return await original_xreadgroup(*args, **kwargs)

    monkeypatch.setattr(perf_redis, "xreadgroup", tracked_xreadgroup)

    start = perf_counter()
    job = await queue.dequeue(["fn.idle"], timeout=0.5)
    elapsed = perf_counter() - start
    print(
        f"queue_idle_perf elapsed_s={elapsed:.3f} xreadgroup_calls={xreadgroup_calls}"
    )

    assert job is None
    assert xreadgroup_calls <= 2
    await queue.close()


@pytest.mark.performance
@pytest.mark.integration
@pytest.mark.asyncio
async def test_perf_queue_mixed_load_dequeue_throughput(perf_redis) -> None:
    queue = RedisQueue(client=perf_redis, key_prefix="upnext-perf-mixed")
    function_key = "fn.perf.mixed"
    total_jobs = 400

    for idx in range(total_jobs):
        await queue.enqueue(
            Job(
                function=function_key,
                function_name="perf_mixed",
                kwargs={"idx": idx},
            )
        )

    dequeued = 0
    start = perf_counter()
    while dequeued < total_jobs:
        jobs = await queue._dequeue_batch(  # noqa: SLF001
            [function_key],
            count=50,
            timeout=1.0,
        )
        if not jobs:
            break
        dequeued += len(jobs)
        for job in jobs:
            await queue.finish(job, JobStatus.COMPLETE, result={"ok": True})
    elapsed = max(perf_counter() - start, 1e-9)
    jobs_per_second = dequeued / elapsed
    print(
        f"queue_mixed_perf dequeued={dequeued} elapsed_s={elapsed:.3f} "
        f"jobs_per_second={jobs_per_second:.1f}"
    )

    assert dequeued == total_jobs
    assert jobs_per_second > 0
    await queue.close()
