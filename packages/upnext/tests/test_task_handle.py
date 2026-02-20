from __future__ import annotations

import pytest
from shared.domain.jobs import Job, JobStatus
from upnext.sdk.context import Context, set_current_context
from upnext.sdk.task import TaskExecutionError
from upnext.sdk.worker import Worker


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.subscribe_timeouts: list[float | None] = []
        self.terminal_status: str = JobStatus.COMPLETE.value

    async def enqueue(self, job: Job, *, delay: float = 0.0) -> str:
        assert delay == 0.0
        self.jobs[job.id] = job
        return job.id

    async def subscribe_job(self, job_id: str, timeout: float | None = None) -> str:
        self.subscribe_timeouts.append(timeout)
        return self.terminal_status

    async def get_job(self, job_id: str) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        if self.terminal_status == JobStatus.COMPLETE.value:
            job.status = JobStatus.COMPLETE
            job.result = {"job_id": job_id}
        elif self.terminal_status == JobStatus.FAILED.value:
            job.status = JobStatus.FAILED
            job.error = "child failed"
        elif self.terminal_status == JobStatus.CANCELLED.value:
            job.status = JobStatus.CANCELLED
            job.error = "child cancelled"
        return job

    async def cancel(self, job_id: str) -> bool:
        return job_id in self.jobs


@pytest.mark.asyncio
async def test_task_submit_inherits_parent_and_root_context() -> None:
    worker = Worker(name="test-worker")

    @worker.task(timeout=9)
    async def child_task(user_id: str) -> dict[str, str]:
        return {"user_id": user_id}

    queue = RecordingQueue()
    child_task._queue = queue  # type: ignore[assignment]

    parent = Context(job_id="job_parent", job_key="key_parent", root_id="job_root")
    set_current_context(parent)
    try:
        future = await child_task.submit("u-1")
    finally:
        set_current_context(None)

    enqueued = queue.jobs[future.job_id]
    assert enqueued.kwargs == {"user_id": "u-1"}
    assert enqueued.parent_id == "job_parent"
    assert enqueued.root_id == "job_root"


@pytest.mark.asyncio
async def test_task_wait_uses_default_timeout_and_override() -> None:
    worker = Worker(name="test-worker")

    @worker.task(timeout=12)
    async def process(v: int) -> int:
        return v + 1

    queue = RecordingQueue()
    process._queue = queue  # type: ignore[assignment]

    result = await process.wait(v=3)
    assert result.ok is True
    assert queue.subscribe_timeouts[-1] == 12

    result = await process.wait(v=4, wait_timeout=2.5)
    assert result.ok is True
    assert queue.subscribe_timeouts[-1] == 2.5


@pytest.mark.asyncio
async def test_task_submit_top_level_sets_root_to_own_job_id() -> None:
    worker = Worker(name="test-worker")

    @worker.task
    async def top(name: str) -> str:
        return name

    queue = RecordingQueue()
    top._queue = queue  # type: ignore[assignment]

    future = await top.submit(name="abc")
    job = queue.jobs[future.job_id]
    assert job.parent_id is None
    assert job.root_id == job.id


@pytest.mark.asyncio
async def test_task_submit_idempotent_sets_stable_key() -> None:
    worker = Worker(name="test-worker")

    @worker.task
    async def process(name: str) -> str:
        return name

    queue = RecordingQueue()
    process._queue = queue  # type: ignore[assignment]

    future = await process.submit_idempotent(" customer:123 ", name="abc")
    job = queue.jobs[future.job_id]
    assert job.key == "customer:123"


@pytest.mark.asyncio
async def test_task_wait_idempotent_uses_timeout_and_validates_key() -> None:
    worker = Worker(name="test-worker")

    @worker.task(timeout=7)
    async def process(name: str) -> str:
        return name

    queue = RecordingQueue()
    process._queue = queue  # type: ignore[assignment]

    result = await process.wait_idempotent("tenant:xyz", name="abc")
    assert result.ok is True
    assert queue.subscribe_timeouts[-1] == 7

    with pytest.raises(ValueError, match="idempotency_key must be a non-empty string"):
        await process.submit_idempotent("   ", name="abc")


@pytest.mark.asyncio
async def test_task_wait_bubbles_failed_child_status_as_exception() -> None:
    worker = Worker(name="test-worker")

    @worker.task(timeout=12)
    async def process(v: int) -> int:
        return v + 1

    queue = RecordingQueue()
    queue.terminal_status = JobStatus.FAILED.value
    process._queue = queue  # type: ignore[assignment]

    with pytest.raises(TaskExecutionError, match="child failed"):
        await process.wait(v=3)


@pytest.mark.asyncio
async def test_task_submit_rejects_too_many_positional_args() -> None:
    worker = Worker(name="test-worker")

    @worker.task
    async def process(name: str) -> str:
        return name

    queue = RecordingQueue()
    process._queue = queue  # type: ignore[assignment]

    with pytest.raises(TypeError, match="too many positional arguments"):
        await process.submit("a", "b")


@pytest.mark.asyncio
async def test_task_submit_rejects_duplicate_positional_and_keyword_arg() -> None:
    worker = Worker(name="test-worker")

    @worker.task
    async def process(name: str) -> str:
        return name

    queue = RecordingQueue()
    process._queue = queue  # type: ignore[assignment]

    with pytest.raises(TypeError, match="multiple values for argument"):
        await process.submit("a", name="b")


def test_task_handle_does_not_expose_run_after_api() -> None:
    worker = Worker(name="test-worker")

    @worker.task
    async def process(name: str) -> str:
        return name

    assert not hasattr(process, "submit_after")
    assert not hasattr(process, "wait_after")
