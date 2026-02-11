from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from shared.models import Job, JobStatus
from upnext.engine.job_processor import JobProcessor
from upnext.engine.queue.base import BaseQueue
from upnext.engine.registry import Registry
from upnext.sdk.context import get_current_context


@dataclass
class _QueueRecorder:
    finished: list[tuple[str, JobStatus, Any, str | None]] = field(default_factory=list)
    retried: list[tuple[str, float]] = field(default_factory=list)
    rescheduled: list[str] = field(default_factory=list)
    progresses: list[tuple[str, float]] = field(default_factory=list)
    metadata_updates: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def finish(
        self,
        job: Job,
        status: JobStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        self.finished.append((job.id, status, result, error))

    async def retry(self, job: Job, delay: float) -> None:
        self.retried.append((job.id, delay))

    async def reschedule_cron(self, job: Job, next_run_at: float) -> str:
        self.rescheduled.append(job.id)
        return f"{job.id}-next"

    async def update_progress(self, job_id: str, progress: float) -> None:
        self.progresses.append((job_id, progress))

    async def update_job_metadata(self, job_id: str, metadata: dict[str, Any]) -> None:
        self.metadata_updates.append((job_id, metadata))

    async def get_job(self, job_id: str) -> Job | None:
        return None


@dataclass
class _StatusRecorder:
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    retrying: list[tuple[str, float]] = field(default_factory=list)
    progress: list[tuple[str, float]] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    async def record_job_completed(
        self, job_id: str, *args: Any, **kwargs: Any
    ) -> None:
        self.completed.append(job_id)

    async def record_job_failed(self, job_id: str, *args: Any, **kwargs: Any) -> None:
        self.failed.append(job_id)

    async def record_job_retrying(
        self,
        job_id: str,
        function: str,
        function_name: str,
        root_id: str,
        error: str,
        delay: float,
        current_attempt: int,
        next_attempt: int,
        parent_id: str | None = None,
    ) -> None:
        self.retrying.append((job_id, delay))

    async def record_job_progress(
        self,
        job_id: str,
        root_id: str,
        progress: float,
        parent_id: str | None = None,
        message: str | None = None,
    ) -> None:
        self.progress.append((job_id, progress))

    async def record_job_checkpoint(
        self,
        job_id: str,
        root_id: str,
        state: dict[str, Any],
        parent_id: str | None = None,
    ) -> None:
        self.checkpoints.append(job_id)

    async def record_job_log(
        self, job_id: str, level: str, message: str, **extra: Any
    ) -> None:
        self.logs.append(job_id)


@pytest.mark.asyncio
async def test_execute_and_success_flow_calls_hooks_and_completes() -> None:
    queue = _QueueRecorder()
    status = _StatusRecorder()
    registry = Registry()
    calls: list[str] = []

    async def on_start(ctx):
        calls.append("on_start")

    async def on_success(ctx, result):
        calls.append("on_success")

    async def on_complete(ctx):
        calls.append("on_complete")

    async def task() -> str:
        calls.append("task")
        return "ok"

    task_def = registry.register_task(
        "task_key",
        task,
        on_start=on_start,
        on_success=on_success,
        on_complete=on_complete,
    )
    processor = JobProcessor(
        queue=cast(BaseQueue, queue), registry=registry, status_buffer=status
    )

    try:
        job = Job(function="task_key", function_name="task", kwargs={}, root_id="job-1")
        job.mark_started("worker")

        result = await processor._execute_job(job, task_def)  # noqa: SLF001
        await processor._handle_success(job, task_def, result, duration_ms=5)  # noqa: SLF001

        assert result == "ok"
        assert calls == ["on_start", "task", "on_success", "on_complete"]
        assert queue.finished == [(job.id, JobStatus.COMPLETE, "ok", None)]
        assert status.completed == [job.id]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_context_commands_are_drained_to_backend() -> None:
    queue = _QueueRecorder()
    status = _StatusRecorder()
    registry = Registry()

    async def task() -> str:
        ctx = get_current_context()
        ctx.set_progress(40)
        ctx.set_metadata("phase", "download")
        ctx.checkpoint({"offset": 10})
        ctx.send_log("info", "hello")
        return "done"

    task_def = registry.register_task("task_key", task)
    processor = JobProcessor(
        queue=cast(BaseQueue, queue), registry=registry, status_buffer=status
    )

    try:
        job = Job(
            function="task_key", function_name="task", kwargs={}, root_id="job-cmd"
        )
        job.mark_started("worker")

        result = await processor._execute_job(job, task_def)  # noqa: SLF001

        assert result == "done"
        assert queue.progresses == [(job.id, 0.4)]
        assert queue.metadata_updates == [
            (job.id, {"phase": "download"}),
            (job.id, {"_checkpoint": {"offset": 10}}),
        ]
        assert status.progress == [(job.id, 0.4)]
        assert status.checkpoints == [job.id]
        assert status.logs == [job.id]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_retry_path_uses_exponential_backoff() -> None:
    queue = _QueueRecorder()
    status = _StatusRecorder()
    registry = Registry()

    async def task() -> None:
        return None

    task_def = registry.register_task(
        "task_key",
        task,
        retries=3,
        retry_delay=2,
        retry_backoff=2,
    )
    processor = JobProcessor(
        queue=cast(BaseQueue, queue), registry=registry, status_buffer=status
    )

    try:
        job = Job(function="task_key", function_name="task", kwargs={}, root_id="job-r")
        job.mark_started("worker")
        job.attempts = 2

        await processor._handle_failure(job, task_def, RuntimeError("boom"))  # noqa: SLF001

        assert queue.retried == [(job.id, 4)]
        assert status.retrying == [(job.id, 4)]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_terminal_failure_marks_failed_once() -> None:
    queue = _QueueRecorder()
    status = _StatusRecorder()
    registry = Registry()
    calls: list[str] = []

    async def on_complete(ctx):
        calls.append("on_complete")

    async def task() -> None:
        return None

    task_def = registry.register_task(
        "task_key", task, retries=1, on_complete=on_complete
    )
    processor = JobProcessor(
        queue=cast(BaseQueue, queue), registry=registry, status_buffer=status
    )

    try:
        job = Job(function="task_key", function_name="task", kwargs={}, root_id="job-f")
        job.mark_started("worker")
        job.attempts = 3

        await processor._handle_failure(job, task_def, RuntimeError("fatal"))  # noqa: SLF001

        assert queue.finished == [(job.id, JobStatus.FAILED, None, "fatal")]
        assert status.failed == [job.id]
        assert calls == ["on_complete"]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_execute_job_timeout_raises_with_job_id() -> None:
    queue = _QueueRecorder()
    registry = Registry()

    async def slow_task() -> None:
        await asyncio.sleep(0.05)

    task_def = registry.register_task("task_key", slow_task, timeout=0.01)
    processor = JobProcessor(queue=cast(BaseQueue, queue), registry=registry)

    try:
        job = Job(
            function="task_key",
            function_name="task",
            kwargs={},
            root_id="job-timeout",
            timeout=0.01,
        )
        job.mark_started("worker")

        with pytest.raises(TimeoutError, match=f"Job {job.id} timed out after 0.01"):
            await processor._execute_job(job, task_def)  # noqa: SLF001
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_cron_jobs_reschedule_on_success_and_terminal_failure() -> None:
    queue = _QueueRecorder()
    status = _StatusRecorder()
    registry = Registry()

    async def task() -> str:
        return "ok"

    task_def = registry.register_task("task_key", task, retries=0)
    processor = JobProcessor(
        queue=cast(BaseQueue, queue), registry=registry, status_buffer=status
    )

    try:
        success_job = Job(
            function="task_key",
            function_name="task",
            kwargs={},
            root_id="cron-success",
            schedule="* * * * *",
            metadata={"cron": True},
        )
        success_job.mark_started("worker")

        await processor._handle_success(success_job, task_def, "ok", duration_ms=1)  # noqa: SLF001

        failed_job = Job(
            function="task_key",
            function_name="task",
            kwargs={},
            root_id="cron-failed",
            schedule="* * * * *",
            metadata={"cron": True},
        )
        failed_job.mark_started("worker")
        failed_job.attempts = 2

        await processor._handle_failure(failed_job, task_def, RuntimeError("fatal"))  # noqa: SLF001

        assert success_job.id in queue.rescheduled
        assert failed_job.id in queue.rescheduled
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@dataclass
class _CancelledQueue:
    job: Job | None
    finishes: list[tuple[str, JobStatus, Any, str | None]] = field(default_factory=list)

    async def dequeue(self, functions: list[str], *, timeout: float = 5.0) -> Job | None:  # noqa: ARG002
        current = self.job
        self.job = None
        return current

    async def is_cancelled(self, job_id: str) -> bool:
        return True

    async def finish(
        self,
        job: Job,
        status: JobStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        self.finishes.append((job.id, status, result, error))


@pytest.mark.asyncio
async def test_process_one_skips_jobs_marked_cancelled_before_start() -> None:
    registry = Registry()

    async def task() -> str:
        return "ok"

    registry.register_task("task_key", task)
    job = Job(function="task_key", function_name="task")
    queue = _CancelledQueue(job=job)
    processor = JobProcessor(queue=cast(BaseQueue, queue), registry=registry)

    try:
        await processor._process_one()  # noqa: SLF001
        assert queue.finishes == [
            (job.id, JobStatus.CANCELLED, None, "Cancelled before execution")
        ]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001
