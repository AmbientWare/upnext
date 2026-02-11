from __future__ import annotations

import asyncio
import time

import pytest
from shared.models import Job
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

