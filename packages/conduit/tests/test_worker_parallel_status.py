from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest

from conduit.engine.queue.base import BaseQueue
from conduit.sdk.parallel import first_completed, gather, map_tasks, submit_many
from conduit.sdk.task import Future
from conduit.sdk.worker import Worker
from conduit.engine.status import StatusPublisher
from shared.models import Job, JobStatus


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

    fastest = await first_completed(asyncio.sleep(0.001, result=9), asyncio.sleep(0.02, result=99))
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

    rows = await fake_redis.xrange("conduit:status:events", count=10)
    assert len(rows) == 2

    started_payload = rows[0][1]
    completed_payload = rows[1][1]

    assert started_payload[b"type"] == b"job.started"
    assert started_payload[b"job_id"] == b"job-1"
    assert completed_payload[b"type"] == b"job.completed"
    assert completed_payload[b"worker_id"] == b"worker-test"


@pytest.mark.asyncio
async def test_status_publisher_writes_lineage_for_all_lifecycle_events(fake_redis) -> None:
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

    rows = await fake_redis.xrange("conduit:status:events", count=20)
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

        async def xadd(self, stream: str, payload: dict[str, str], **kwargs: Any) -> str:
            self.calls.append({"stream": stream, "payload": payload, "kwargs": kwargs})
            return "1-0"

    redis_stub = _RedisStub()
    publisher = StatusPublisher(redis_stub, worker_id="worker-trim")

    await publisher.record("job.progress", "job-trim-1", progress=0.5)

    assert len(redis_stub.calls) == 1
    call = redis_stub.calls[0]
    assert call["kwargs"].get("approximate") is True
    assert call["kwargs"].get("maxlen") == publisher._config.max_stream_len  # noqa: SLF001
