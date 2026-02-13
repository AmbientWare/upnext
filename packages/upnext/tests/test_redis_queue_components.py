from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from shared.domain.jobs import Job, JobStatus
from upnext.engine.queue.redis.constants import CompletedJob
from upnext.engine.queue.redis.fetcher import Fetcher
from upnext.engine.queue.redis.finisher import Finisher
from upnext.engine.queue.redis.queue import RedisQueue
from upnext.engine.queue.redis.sweeper import Sweeper


@dataclass
class _BatchQueueStub:
    batches: list[list[Job]] = field(default_factory=list)
    calls: int = 0
    fail_next: bool = False

    async def _dequeue_batch(
        self,
        functions: list[str],  # noqa: ARG002
        *,
        count: int,  # noqa: ARG002
        timeout: float,  # noqa: ARG002
    ) -> list[Job]:
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("transient dequeue failure")
        if self.batches:
            return self.batches.pop(0)
        await asyncio.sleep(0)
        return []


async def _wait_for(
    predicate: Any,
    *,
    timeout: float = 1.0,
    interval: float = 0.01,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False


@pytest.mark.asyncio
async def test_fetcher_skips_dequeue_when_inbox_has_too_little_capacity() -> None:
    queue = _BatchQueueStub()
    fetcher = Fetcher(queue=cast(RedisQueue, queue), batch_size=2, inbox_size=1)

    await fetcher.start(["task_fn"])
    try:
        await asyncio.sleep(0.05)
    finally:
        await fetcher.stop()

    assert queue.calls == 0


@pytest.mark.asyncio
async def test_fetcher_recovers_after_transient_dequeue_error() -> None:
    job = Job(function="task_fn", function_name="task", key="fetcher-recovery")
    queue = _BatchQueueStub(batches=[[job]], fail_next=True)
    fetcher = Fetcher(queue=cast(RedisQueue, queue), batch_size=1, inbox_size=4)

    await fetcher.start(["task_fn"])
    try:

        async def inbox_has_item() -> bool:
            return not fetcher.inbox.empty()

        assert await _wait_for(inbox_has_item)
        received = await fetcher.inbox.get()
    finally:
        await fetcher.stop()

    assert queue.calls >= 2
    assert received.id == job.id


@pytest.mark.asyncio
async def test_finisher_fallback_pipeline_flushes_and_acks(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-finisher-fallback")
    queue._scripts_loaded = True  # noqa: SLF001
    queue._enqueue_sha = None  # noqa: SLF001
    queue._finish_sha = None  # noqa: SLF001

    job = Job(function="task_fn", function_name="task", key="finisher-key")
    await queue.enqueue(job)
    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None

    finisher = Finisher(queue=queue, batch_size=8, outbox_size=8, flush_interval=0.01)
    await finisher.start()
    try:
        await finisher.put(
            CompletedJob(
                job=active,
                status=JobStatus.COMPLETE,
                result={"ok": True},
            )
        )

        client = await queue._ensure_connected()  # noqa: SLF001

        async def result_written() -> bool:
            return await client.get(queue._result_key(job.id)) is not None  # noqa: SLF001

        assert await _wait_for(result_written)
    finally:
        await finisher.stop()

    persisted = await queue.get_job(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.COMPLETE

    client = await queue._ensure_connected()  # noqa: SLF001
    pending = await client.xpending(
        queue._stream_key(job.function), queue._consumer_group
    )  # noqa: SLF001
    assert pending["pending"] == 0
    assert await client.sismember(queue._dedup_key(job.function), job.key) == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_finisher_retries_flush_without_dropping_batch(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-finisher-retry")

    job = Job(function="task_fn", function_name="task", key="finisher-retry-key")
    await queue.enqueue(job)
    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None

    finisher = Finisher(queue=queue, batch_size=8, outbox_size=8, flush_interval=0.01)
    await finisher.start()
    try:
        original_flush = finisher._flush_batch  # noqa: SLF001
        state = {"calls": 0}

        async def flaky_flush(batch):  # type: ignore[no-untyped-def]
            state["calls"] += 1
            if state["calls"] == 1:
                raise RuntimeError("transient redis failure")
            await original_flush(batch)

        finisher._flush_batch = flaky_flush  # type: ignore[method-assign]  # noqa: SLF001

        await finisher.put(
            CompletedJob(
                job=active,
                status=JobStatus.COMPLETE,
                result={"ok": True},
            )
        )

        client = await queue._ensure_connected()  # noqa: SLF001

        async def result_written() -> bool:
            return await client.get(queue._result_key(job.id)) is not None  # noqa: SLF001

        assert await _wait_for(result_written)
        assert state["calls"] >= 2
    finally:
        await finisher.stop()


@pytest.mark.asyncio
async def test_sweeper_fallback_moves_due_job_to_stream(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-sweeper-fallback")
    queue._scripts_loaded = True  # noqa: SLF001
    queue._enqueue_sha = None  # noqa: SLF001
    queue._sweep_sha = None  # noqa: SLF001

    job = Job(function="task_fn", function_name="task", key="sweep-key")
    await queue.enqueue(job, delay=1.0)
    client = await queue._ensure_connected()  # noqa: SLF001
    await client.zadd(queue._scheduled_key(job.function), {job.id: time.time() - 1.0})  # noqa: SLF001

    sweeper = Sweeper(queue=queue, sweep_interval=1.0)
    await sweeper._do_sweep()  # noqa: SLF001

    moved = await queue.dequeue(["task_fn"], timeout=0.2)
    assert moved is not None
    assert moved.id == job.id

    client = await queue._ensure_connected()  # noqa: SLF001
    score = await client.zscore(queue._scheduled_key(job.function), job.id)  # noqa: SLF001
    assert score is None
