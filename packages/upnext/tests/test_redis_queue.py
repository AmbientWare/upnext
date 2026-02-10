from __future__ import annotations

import asyncio
import time

import pytest
from shared.models import Job, JobStatus
from upnext.engine.queue.base import DuplicateJobError
from upnext.engine.queue.redis.queue import RedisQueue


@pytest.fixture
def queue(fake_redis):
    return RedisQueue(client=fake_redis, claim_timeout_ms=50, key_prefix="upnext-test")


@pytest.mark.asyncio
async def test_enqueue_duplicate_job_key_raises(queue: RedisQueue) -> None:
    job1 = Job(function="task_fn", function_name="task", key="dup-key")
    job2 = Job(function="task_fn", function_name="task", key="dup-key")

    await queue.enqueue(job1)
    with pytest.raises(DuplicateJobError):
        await queue.enqueue(job2)


@pytest.mark.asyncio
async def test_queue_lifecycle_enqueue_dequeue_finish_cleans_keys(
    queue: RedisQueue,
) -> None:
    job = Job(function="task_fn", function_name="task", key="job-key-1")
    await queue.enqueue(job)

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    assert active.id == job.id

    await queue.finish(active, JobStatus.COMPLETE, result={"ok": True})

    client = await queue._ensure_connected()  # noqa: SLF001
    result_data = await client.get(queue._result_key(job.id))  # noqa: SLF001
    job_data = await client.get(queue._job_key(job))  # noqa: SLF001
    index_data = await client.get(queue._job_index_key(job.id))  # noqa: SLF001
    dedup_exists = await client.sismember(queue._dedup_key(job.function), job.key)  # noqa: SLF001

    assert result_data is not None
    assert job_data is None
    assert index_data is None
    assert dedup_exists == 0


@pytest.mark.asyncio
async def test_retry_clears_stream_metadata_and_requeues_immediately(
    queue: RedisQueue,
) -> None:
    job = Job(function="task_fn", function_name="task", key="retry-key")
    await queue.enqueue(job)

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    old_msg_id = active.metadata.get("_stream_msg_id")

    await queue.retry(active, delay=0)

    # Retry should clear stream metadata from the job payload and put it back on stream.
    requeued = await queue.dequeue(["task_fn"], timeout=0.2)
    assert requeued is not None
    assert requeued.id == active.id
    assert requeued.metadata.get("_stream_msg_id") != old_msg_id


@pytest.mark.asyncio
async def test_retry_with_delay_goes_to_scheduled_set(queue: RedisQueue) -> None:
    job = Job(function="task_fn", function_name="task", key="retry-delay-key")
    await queue.enqueue(job)
    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None

    await queue.retry(active, delay=10)

    client = await queue._ensure_connected()  # noqa: SLF001
    scheduled_score = await client.zscore(queue._scheduled_key(job.function), job.id)  # noqa: SLF001
    assert scheduled_score is not None


@pytest.mark.asyncio
async def test_cancel_non_terminal_job_returns_true(queue: RedisQueue) -> None:
    queued_job = Job(function="task_fn", function_name="task", key="cancel-key")
    await queue.enqueue(queued_job)

    assert await queue.cancel(queued_job.id) is True
    cancelled = await queue.get_job(queued_job.id)
    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_terminal_job_returns_false(queue: RedisQueue) -> None:
    terminal_job = Job(function="task_fn", function_name="task", key="terminal-key")
    await queue.enqueue(terminal_job)
    active = None
    for _ in range(4):
        candidate = await queue.dequeue(["task_fn"], timeout=0.2)
        if candidate is None:
            continue
        if candidate.id == terminal_job.id:
            active = candidate
            break
    assert active is not None
    await queue.finish(active, JobStatus.COMPLETE)

    assert await queue.cancel(terminal_job.id) is False


@pytest.mark.asyncio
async def test_xautoclaim_recovers_stale_message(fake_redis) -> None:
    q1 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-claim")
    q2 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-claim")

    job = Job(function="task_fn", function_name="task", key="claim-key")
    await q1.enqueue(job)

    first = await q1.dequeue(["task_fn"], timeout=0.2)
    assert first is not None

    deadline = time.monotonic() + 1.0
    recovered = None
    while time.monotonic() < deadline:
        recovered = await q2.dequeue(["task_fn"], timeout=0.05)
        if recovered is not None:
            break
        await asyncio.sleep(0.01)

    assert recovered is not None
    assert recovered.id == job.id


@pytest.mark.asyncio
async def test_heartbeat_prevents_reclaim(fake_redis) -> None:
    q1 = RedisQueue(
        client=fake_redis, claim_timeout_ms=200, key_prefix="upnext-heartbeat"
    )
    q2 = RedisQueue(
        client=fake_redis, claim_timeout_ms=200, key_prefix="upnext-heartbeat"
    )

    job = Job(function="task_fn", function_name="task", key="heartbeat-key")
    await q1.enqueue(job)

    first = await q1.dequeue(["task_fn"], timeout=0.2)
    assert first is not None

    await asyncio.sleep(0.05)
    await q1.heartbeat_active_jobs([first])
    await asyncio.sleep(0.05)

    for _ in range(3):
        reclaimed = await q2.dequeue(["task_fn"], timeout=0.02)
        assert reclaimed is None
