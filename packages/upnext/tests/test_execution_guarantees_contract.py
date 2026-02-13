from __future__ import annotations

import asyncio
import time

import pytest
from shared.domain.jobs import Job
from shared.domain.jobs import JobStatus
from upnext.engine.queue.redis.queue import RedisQueue


@pytest.mark.asyncio
async def test_contract_at_least_once_delivery_under_worker_loss(fake_redis) -> None:
    """
    Contract: delivery is at-least-once, not exactly-once.

    A dequeued but unacknowledged job can be reclaimed by another consumer.
    """
    q1 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-contract")
    q2 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-contract")

    job = Job(function="task_fn", function_name="task", key="contract-dup-key")
    await q1.enqueue(job)

    first = await q1.dequeue(["task_fn"], timeout=0.2)
    assert first is not None
    assert first.id == job.id

    recovered = None
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        recovered = await q2.dequeue(["task_fn"], timeout=0.05)
        if recovered is not None:
            break
        await asyncio.sleep(0.01)

    assert recovered is not None
    assert recovered.id == job.id


@pytest.mark.asyncio
async def test_contract_worker_loss_then_reclaim_then_retry_keeps_job_durable(
    fake_redis,
) -> None:
    """
    Contract: worker loss does not drop jobs; reclaimed jobs can be retried deterministically.
    """
    q1 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-contract")
    q2 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-contract")

    job = Job(function="task_fn", function_name="task", key="contract-retry-key")
    await q1.enqueue(job)

    first = await q1.dequeue(["task_fn"], timeout=0.2)
    assert first is not None

    recovered = None
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        recovered = await q2.dequeue(["task_fn"], timeout=0.05)
        if recovered is not None:
            break
        await asyncio.sleep(0.01)

    assert recovered is not None
    assert recovered.id == job.id

    await q2.retry(recovered, delay=0)

    requeued = await q2.dequeue(["task_fn"], timeout=0.2)
    assert requeued is not None
    assert requeued.id == job.id


@pytest.mark.asyncio
async def test_contract_cancel_after_worker_loss_is_terminal(fake_redis) -> None:
    """
    Contract: cancelling after worker loss produces a terminal cancelled job with no later execution.
    """
    q1 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-contract")
    q2 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-contract")

    job = Job(function="task_fn", function_name="task", key="contract-cancel-key")
    await q1.enqueue(job)

    first = await q1.dequeue(["task_fn"], timeout=0.2)
    assert first is not None

    cancelled = await q2.cancel(job.id)
    assert cancelled is True

    later = await q2.dequeue(["task_fn"], timeout=0.1)
    assert later is None

    stored = await q2.get_job(job.id)
    assert stored is not None
    assert stored.status == JobStatus.CANCELLED
