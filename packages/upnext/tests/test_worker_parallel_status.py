from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest
from shared.domain.jobs import Job, JobStatus
from upnext.engine.queue.base import BaseQueue
from upnext.engine.status import StatusPublisher, StatusPublisherConfig
from upnext.sdk.parallel import first_completed, gather, map_tasks, submit_many
from upnext.sdk.task import Future
from upnext.sdk.worker import Worker


class _FutureQueue:
    def __init__(self, value_by_id: dict[str, Any]):
        self.value_by_id = value_by_id

    async def subscribe_job(self, job_id: str, timeout: float | None = None) -> str:
        return JobStatus.COMPLETE.value

    async def get_job(self, job_id: str) -> Job:
        return Job(
            id=job_id,
            function="task_key",
            function_name="task",
            result=self.value_by_id[job_id],
            status=JobStatus.COMPLETE,
            root_id=job_id,
        )

    async def cancel(self, job_id: str) -> bool:
        return True


@dataclass
class _Submittable:
    values: list[int]

    async def submit(self, **kwargs: Any) -> Future[int]:
        idx = kwargs["idx"]
        queue = cast(BaseQueue, _FutureQueue({f"job-{idx}": self.values[idx]}))
        return Future(job_id=f"job-{idx}", queue=queue)


@pytest.mark.asyncio
async def test_worker_rejects_duplicate_task_names() -> None:
    worker = Worker(name="dup-worker")

    @worker.task(name="same")
    async def one() -> int:
        return 1

    with pytest.raises(ValueError, match="already registered"):

        @worker.task(name="same")
        async def two() -> int:  # pragma: no cover - only registration path
            return 2

    assert "same" in worker.tasks


def test_worker_event_reuses_existing_handle_for_pattern() -> None:
    worker = Worker(name="event-dedupe-worker")

    first = worker.event("order.created")
    second = worker.event("order.created")

    assert first is second
    assert worker.events["order.created"] is first


def test_worker_event_rejects_empty_pattern() -> None:
    worker = Worker(name="event-validate-worker")
    with pytest.raises(ValueError, match="non-empty"):
        worker.event("   ")


@pytest.mark.asyncio
async def test_parallel_helpers_cover_future_and_coroutine_paths() -> None:
    queue = cast(BaseQueue, _FutureQueue({"job-a": 10, "job-b": 20}))
    fut_a = Future[int](job_id="job-a", queue=queue)
    fut_b = Future[int](job_id="job-b", queue=queue)

    gathered = await gather(fut_a, fut_b, asyncio.sleep(0, result=30))
    assert gathered == [10, 20, 30]

    task = _Submittable(values=[3, 4, 5])
    mapped = await map_tasks(task, [{"idx": 0}, {"idx": 1}, {"idx": 2}], concurrency=2)
    assert mapped == [3, 4, 5]

    submitted = await submit_many(task, [{"idx": 0}, {"idx": 2}])
    assert len(submitted) == 2
    assert [result for result in await gather(*submitted)] == [3, 5]

    fastest = await first_completed(
        asyncio.sleep(0.001, result=9), asyncio.sleep(0.02, result=99)
    )
    assert fastest == 9


@pytest.mark.asyncio
async def test_status_publisher_records_required_job_fields(fake_redis) -> None:
    publisher = StatusPublisher(fake_redis, worker_id="worker-test")

    await publisher.record_job_started(
        job_id="job-1",
        function="task_key",
        function_name="task_name",
        attempt=1,
        max_retries=2,
        root_id="job-1",
        parent_id=None,
    )
    await publisher.record_job_completed(
        job_id="job-1",
        function="task_key",
        function_name="task_name",
        root_id="job-1",
        parent_id=None,
        attempt=1,
        result={"ok": True},
        duration_ms=12.5,
    )

    rows = await fake_redis.xrange("upnext:status:events", count=10)
    assert len(rows) == 2

    started_payload = rows[0][1]
    completed_payload = rows[1][1]

    assert started_payload[b"type"] == b"job.started"
    assert started_payload[b"job_id"] == b"job-1"
    assert completed_payload[b"type"] == b"job.completed"
    assert completed_payload[b"worker_id"] == b"worker-test"


@pytest.mark.asyncio
async def test_status_publisher_writes_lineage_for_all_lifecycle_events(
    fake_redis,
) -> None:
    publisher = StatusPublisher(fake_redis, worker_id="worker-test")

    await publisher.record_job_started(
        job_id="job-2",
        function="task_key",
        function_name="task_name",
        attempt=1,
        max_retries=2,
        root_id="job-root",
        parent_id="job-parent",
    )
    await publisher.record_job_retrying(
        job_id="job-2",
        function="task_key",
        function_name="task_name",
        root_id="job-root",
        parent_id="job-parent",
        error="boom",
        delay=1.5,
        current_attempt=1,
        next_attempt=2,
    )
    await publisher.record_job_progress(
        job_id="job-2",
        root_id="job-root",
        parent_id="job-parent",
        progress=0.5,
        message="halfway",
    )
    await publisher.record_job_checkpoint(
        job_id="job-2",
        root_id="job-root",
        parent_id="job-parent",
        state={"phase": "download"},
    )
    await publisher.record_job_failed(
        job_id="job-2",
        function="task_key",
        function_name="task_name",
        root_id="job-root",
        parent_id="job-parent",
        error="fatal",
        attempt=2,
        max_retries=2,
        will_retry=False,
    )

    rows = await fake_redis.xrange("upnext:status:events", count=20)
    assert len(rows) == 5

    payloads = [row[1] for row in rows]
    for payload in payloads:
        assert payload[b"job_id"] == b"job-2"
        assert payload[b"worker_id"] == b"worker-test"

    decoded_by_type = {}
    for payload in payloads:
        event_type = payload[b"type"].decode()
        decoded_by_type[event_type] = payload

    for event_type in ["job.started", "job.retrying", "job.failed"]:
        data = decoded_by_type[event_type][b"data"].decode()
        assert '"function": "task_key"' in data
        assert '"function_name": "task_name"' in data
        assert '"root_id": "job-root"' in data
        assert '"parent_id": "job-parent"' in data

    for event_type in ["job.progress", "job.checkpoint"]:
        data = decoded_by_type[event_type][b"data"].decode()
        assert '"root_id": "job-root"' in data
        assert '"parent_id": "job-parent"' in data


@pytest.mark.asyncio
async def test_status_publisher_uses_approximate_trim_when_supported() -> None:
    class _RedisStub:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def xadd(
            self, stream: str, payload: dict[str, str], **kwargs: Any
        ) -> str:
            self.calls.append({"stream": stream, "payload": payload, "kwargs": kwargs})
            return "1-0"

    redis_stub = _RedisStub()
    publisher = StatusPublisher(redis_stub, worker_id="worker-trim")

    await publisher.record("job.progress", "job-trim-1", progress=0.5)

    assert len(redis_stub.calls) == 1
    call = redis_stub.calls[0]
    assert call["kwargs"].get("approximate") is True
    assert call["kwargs"].get("maxlen") == publisher._config.max_stream_len  # noqa: SLF001


@pytest.mark.asyncio
async def test_status_publisher_buffers_and_flushes_after_transient_failure() -> None:
    class _FlakyRedis:
        def __init__(self) -> None:
            self.remaining_failures = 1
            self.calls: list[dict[str, Any]] = []

        async def xadd(
            self, stream: str, payload: dict[str, str], **kwargs: Any
        ) -> str:
            if self.remaining_failures > 0:
                self.remaining_failures -= 1
                raise RuntimeError("transient write failure")
            self.calls.append({"stream": stream, "payload": payload, "kwargs": kwargs})
            return "1-0"

    redis_stub = _FlakyRedis()
    publisher = StatusPublisher(
        redis_stub,
        worker_id="worker-buffer",
        config=StatusPublisherConfig(
            retry_attempts=0,
            pending_buffer_size=16,
            pending_flush_batch_size=16,
        ),
    )

    await publisher.record("job.progress", "job-1", progress=0.25)
    assert publisher.pending_count == 1

    await publisher.record("job.progress", "job-2", progress=0.5)
    assert publisher.pending_count == 0
    assert len(redis_stub.calls) == 2
    assert redis_stub.calls[0]["payload"]["job_id"] == "job-1"
    assert redis_stub.calls[1]["payload"]["job_id"] == "job-2"


@pytest.mark.asyncio
async def test_status_publisher_strict_mode_raises_on_publish_failure() -> None:
    class _AlwaysFailRedis:
        async def xadd(self, *_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("write failed")

    publisher = StatusPublisher(
        _AlwaysFailRedis(),
        worker_id="worker-strict",
        config=StatusPublisherConfig(
            retry_attempts=0,
            strict=True,
        ),
    )

    with pytest.raises(RuntimeError, match="Failed to publish status event"):
        await publisher.record("job.progress", "job-strict", progress=0.9)


@pytest.mark.asyncio
async def test_status_publisher_uses_durable_fallback_and_flushes_on_next_record(
    fake_redis, monkeypatch
) -> None:
    original_xadd = fake_redis.xadd
    state = {"should_fail": True}

    async def flaky_xadd(*args: Any, **kwargs: Any):  # noqa: ANN002, ANN003
        if state["should_fail"]:
            raise RuntimeError("stream unavailable")
        return await original_xadd(*args, **kwargs)

    monkeypatch.setattr(fake_redis, "xadd", flaky_xadd)

    durable_key = "upnext:status:pending:test-next-record"
    publisher = StatusPublisher(
        fake_redis,
        worker_id="worker-durable",
        config=StatusPublisherConfig(
            retry_attempts=0,
            pending_buffer_size=4,
            pending_flush_batch_size=8,
            durable_buffer_key=durable_key,
            durable_buffer_maxlen=32,
        ),
    )

    await publisher.record("job.progress", "job-1", progress=0.1)
    assert publisher.pending_count == 0
    assert await fake_redis.llen(durable_key) == 1

    state["should_fail"] = False
    await publisher.record("job.progress", "job-2", progress=0.2)
    assert await fake_redis.llen(durable_key) == 0

    rows = await fake_redis.xrange("upnext:status:events", count=10)
    assert len(rows) == 2
    assert rows[0][1][b"job_id"] == b"job-1"
    assert rows[1][1][b"job_id"] == b"job-2"


@pytest.mark.asyncio
async def test_status_publisher_close_flushes_durable_buffer(
    fake_redis, monkeypatch
) -> None:
    original_xadd = fake_redis.xadd
    state = {"should_fail": True}

    async def flaky_xadd(*args: Any, **kwargs: Any):  # noqa: ANN002, ANN003
        if state["should_fail"]:
            raise RuntimeError("stream unavailable")
        return await original_xadd(*args, **kwargs)

    monkeypatch.setattr(fake_redis, "xadd", flaky_xadd)

    durable_key = "upnext:status:pending:test-close"
    publisher = StatusPublisher(
        fake_redis,
        worker_id="worker-durable-close",
        config=StatusPublisherConfig(
            retry_attempts=0,
            pending_buffer_size=4,
            pending_flush_batch_size=8,
            durable_buffer_key=durable_key,
            durable_buffer_maxlen=32,
        ),
    )

    await publisher.record("job.progress", "job-close-1", progress=0.1)
    assert await fake_redis.llen(durable_key) == 1

    state["should_fail"] = False
    await publisher.close(timeout_seconds=1.0)

    assert await fake_redis.llen(durable_key) == 0
    rows = await fake_redis.xrange("upnext:status:events", count=10)
    assert len(rows) == 1
    assert rows[0][1][b"job_id"] == b"job-close-1"
