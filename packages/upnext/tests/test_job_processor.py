from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from shared.domain.jobs import CronSource, Job, JobStatus
from shared.contracts import DispatchReason
from upnext.engine.job_processor import JobProcessor
from upnext.engine.queue.base import BaseQueue
from upnext.engine.registry import Registry
from upnext.sdk.context import get_current_context
from upnext.types import SyncExecutor


def _process_sleep_task(delay: float = 0.2) -> str:
    import time

    time.sleep(delay)
    return "ok"


@dataclass
class _QueueRecorder:
    finished: list[tuple[str, JobStatus, Any, str | None]] = field(default_factory=list)
    retried: list[tuple[str, float]] = field(default_factory=list)
    rescheduled: list[str] = field(default_factory=list)
    progresses: list[tuple[str, float]] = field(default_factory=list)
    checkpoint_updates: list[tuple[str, dict[str, Any], str]] = field(
        default_factory=list
    )
    dispatch_reasons: list[tuple[str, DispatchReason, str | None]] = field(
        default_factory=list
    )

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

    async def update_job_checkpoint(
        self, job_id: str, state: dict[str, Any], checkpointed_at: str
    ) -> None:
        self.checkpoint_updates.append((job_id, state, checkpointed_at))

    async def get_job(self, job_id: str) -> Job | None:
        return None

    async def record_dispatch_reason(
        self,
        function: str,
        reason: DispatchReason,
        *,
        job_id: str | None = None,
    ) -> None:
        self.dispatch_reasons.append((function, reason, job_id))


@dataclass
class _StatusRecorder:
    started: list[dict[str, Any]] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    retrying: list[tuple[str, float]] = field(default_factory=list)
    progress: list[tuple[str, float]] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    async def record_job_started(
        self,
        job_id: str,
        job_key: str,
        function: str,
        function_name: str,
        attempt: int,
        max_retries: int,
        root_id: str,
        parent_id: str | None = None,
        source: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        checkpoint_at: str | None = None,
        scheduled_at: datetime | None = None,
        queue_wait_ms: float | None = None,
    ) -> None:
        _ = (
            function,
            function_name,
            attempt,
            max_retries,
            root_id,
            parent_id,
            job_key,
        )
        self.started.append(
            {
                "job_id": job_id,
                "source": source,
                "checkpoint": checkpoint,
                "checkpoint_at": checkpoint_at,
                "scheduled_at": scheduled_at,
                "queue_wait_ms": queue_wait_ms,
            }
        )

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


@dataclass
class _FlakyStatusRecorder(_StatusRecorder):
    fail_methods: set[str] = field(default_factory=set)

    def _should_fail(self, method_name: str) -> bool:
        return method_name in self.fail_methods

    async def record_job_started(self, *args: Any, **kwargs: Any) -> None:
        if self._should_fail("record_job_started"):
            raise RuntimeError("status unavailable")
        await super().record_job_started(*args, **kwargs)

    async def record_job_completed(self, job_id: str, *args: Any, **kwargs: Any) -> None:
        if self._should_fail("record_job_completed"):
            raise RuntimeError("status unavailable")
        await super().record_job_completed(job_id, *args, **kwargs)

    async def record_job_failed(self, job_id: str, *args: Any, **kwargs: Any) -> None:
        if self._should_fail("record_job_failed"):
            raise RuntimeError("status unavailable")
        await super().record_job_failed(job_id, *args, **kwargs)

    async def record_job_retrying(self, *args: Any, **kwargs: Any) -> None:
        if self._should_fail("record_job_retrying"):
            raise RuntimeError("status unavailable")
        await super().record_job_retrying(*args, **kwargs)

    async def record_job_progress(self, *args: Any, **kwargs: Any) -> None:
        if self._should_fail("record_job_progress"):
            raise RuntimeError("status unavailable")
        await super().record_job_progress(*args, **kwargs)


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
        assert len(queue.checkpoint_updates) == 1
        assert queue.checkpoint_updates[0][0] == job.id
        assert queue.checkpoint_updates[0][1] == {"offset": 10}
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
        assert queue.dispatch_reasons == [
            ("task_key", DispatchReason.RETRYING, job.id)
        ]
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
            source=CronSource(schedule="* * * * *"),
        )
        success_job.mark_started("worker")

        await processor._handle_success(success_job, task_def, "ok", duration_ms=1)  # noqa: SLF001

        failed_job = Job(
            function="task_key",
            function_name="task",
            kwargs={},
            root_id="cron-failed",
            source=CronSource(schedule="* * * * *"),
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
    dispatch_reasons: list[tuple[str, DispatchReason, str | None]] = field(
        default_factory=list
    )

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

    async def record_dispatch_reason(
        self,
        function: str,
        reason: DispatchReason,
        *,
        job_id: str | None = None,
    ) -> None:
        self.dispatch_reasons.append((function, reason, job_id))


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
        assert queue.dispatch_reasons == [
            ("task_key", DispatchReason.CANCELLED, job.id)
        ]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@dataclass
class _PausedQueue:
    job: Job | None
    retried: list[tuple[str, float]] = field(default_factory=list)
    dispatch_reasons: list[tuple[str, DispatchReason, str | None]] = field(
        default_factory=list
    )

    async def dequeue(
        self, functions: list[str], *, timeout: float = 5.0  # noqa: ARG002
    ) -> Job | None:
        current = self.job
        self.job = None
        return current

    async def is_cancelled(self, job_id: str) -> bool:  # noqa: ARG002
        return False

    async def is_function_paused(self, function: str) -> bool:  # noqa: ARG002
        return True

    async def retry(self, job: Job, delay: float) -> None:
        self.retried.append((job.id, delay))

    async def finish(
        self,
        job: Job,  # noqa: ARG002
        status: JobStatus,  # noqa: ARG002
        result: Any = None,  # noqa: ARG002
        error: str | None = None,  # noqa: ARG002
    ) -> None:
        return None

    async def record_dispatch_reason(
        self,
        function: str,
        reason: DispatchReason,
        *,
        job_id: str | None = None,
    ) -> None:
        self.dispatch_reasons.append((function, reason, job_id))


@dataclass
class _CooperativeCancelQueue:
    job: Job | None
    finished: list[tuple[str, JobStatus, Any, str | None]] = field(default_factory=list)
    cancel_checks: int = 0

    async def dequeue(self, functions: list[str], *, timeout: float = 5.0) -> Job | None:  # noqa: ARG002
        current = self.job
        self.job = None
        return current

    async def is_cancelled(self, job_id: str) -> bool:  # noqa: ARG002
        self.cancel_checks += 1
        return self.cancel_checks >= 2

    async def is_function_paused(self, function: str) -> bool:  # noqa: ARG002
        return False

    async def finish(
        self,
        job: Job,
        status: JobStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        self.finished.append((job.id, status, result, error))

    async def record_dispatch_reason(
        self,
        function: str,  # noqa: ARG002
        reason: DispatchReason,  # noqa: ARG002
        *,
        job_id: str | None = None,  # noqa: ARG002
    ) -> None:
        return None


@dataclass
class _SingleJobQueue:
    job: Job | None
    finished: list[tuple[str, JobStatus, Any, str | None]] = field(default_factory=list)

    async def dequeue(self, functions: list[str], *, timeout: float = 5.0) -> Job | None:  # noqa: ARG002
        current = self.job
        self.job = None
        return current

    async def is_cancelled(self, job_id: str) -> bool:  # noqa: ARG002
        return False

    async def is_function_paused(self, function: str) -> bool:  # noqa: ARG002
        return False

    async def finish(
        self,
        job: Job,
        status: JobStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        self.finished.append((job.id, status, result, error))

    async def record_dispatch_reason(
        self,
        function: str,  # noqa: ARG002
        reason: DispatchReason,  # noqa: ARG002
        *,
        job_id: str | None = None,  # noqa: ARG002
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_process_one_retries_jobs_for_paused_functions() -> None:
    registry = Registry()
    executed = {"value": False}

    async def task() -> str:
        executed["value"] = True
        return "ok"

    registry.register_task("task_key", task)
    job = Job(function="task_key", function_name="task")
    queue = _PausedQueue(job=job)
    processor = JobProcessor(queue=cast(BaseQueue, queue), registry=registry)

    try:
        await processor._process_one()  # noqa: SLF001
        assert queue.retried == [(job.id, 1.0)]
        assert queue.dispatch_reasons == [
            ("task_key", DispatchReason.PAUSED, job.id)
        ]
        assert executed["value"] is False
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_process_one_exposes_cooperative_cancellation_flag() -> None:
    registry = Registry()

    async def task() -> str:
        ctx = get_current_context()
        for _ in range(50):
            if ctx.is_cancelled:
                return "cancelled"
            await asyncio.sleep(0.01)
        return "not-cancelled"

    registry.register_task("task_key", task)
    job = Job(function="task_key", function_name="task")
    queue = _CooperativeCancelQueue(job=job)
    processor = JobProcessor(queue=cast(BaseQueue, queue), registry=registry)

    try:
        await processor._process_one()  # noqa: SLF001
        assert queue.finished == [(job.id, JobStatus.COMPLETE, "cancelled", None)]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_process_executor_timeout_hard_stops_and_marks_failed() -> None:
    registry = Registry()
    registry.register_task("task_key", _process_sleep_task)

    job = Job(
        function="task_key",
        function_name="task",
        kwargs={"delay": 0.5},
        timeout=0.05,
    )
    queue = _SingleJobQueue(job=job)
    processor = JobProcessor(
        queue=cast(BaseQueue, queue),
        registry=registry,
        sync_executor=SyncExecutor.PROCESS,
    )

    try:
        started = asyncio.get_running_loop().time()
        await processor._process_one()  # noqa: SLF001
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 1.0
        assert len(queue.finished) == 1
        _job_id, status, _result, error = queue.finished[0]
        assert status == JobStatus.FAILED
        assert error is not None
        assert "timed out after 0.05s" in error
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_process_executor_cancelled_mid_flight_marks_cancelled() -> None:
    registry = Registry()
    registry.register_task("task_key", _process_sleep_task)

    job = Job(
        function="task_key",
        function_name="task",
        kwargs={"delay": 2.0},
    )
    queue = _CooperativeCancelQueue(job=job)
    processor = JobProcessor(
        queue=cast(BaseQueue, queue),
        registry=registry,
        sync_executor=SyncExecutor.PROCESS,
    )

    try:
        started = asyncio.get_running_loop().time()
        await processor._process_one()  # noqa: SLF001
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 1.5
        assert queue.cancel_checks >= 2
        assert len(queue.finished) == 1
        _job_id, status, _result, error = queue.finished[0]
        assert status == JobStatus.CANCELLED
        assert error is not None
        assert "Cancelled during execution" in error
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_process_one_records_queue_wait_fields_on_started_event() -> None:
    registry = Registry()
    status = _StatusRecorder()

    async def task() -> str:
        return "ok"

    registry.register_task("task_key", task)
    job = Job(function="task_key", function_name="task")
    job.scheduled_at = datetime.now(UTC) - timedelta(seconds=2)

    queue = _SingleJobQueue(job=job)
    processor = JobProcessor(
        queue=cast(BaseQueue, queue),
        registry=registry,
        status_buffer=status,
    )

    try:
        await processor._process_one()  # noqa: SLF001

        assert len(status.started) == 1
        started = status.started[0]
        assert started["job_id"] == job.id
        assert started["scheduled_at"] == job.scheduled_at
        assert started["queue_wait_ms"] is not None
        assert float(started["queue_wait_ms"]) >= 1500.0
        assert started["source"] == {"type": "task"}
        assert started["checkpoint"] is None
        assert queue.finished == [(job.id, JobStatus.COMPLETE, "ok", None)]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@dataclass
class _IdleQueue:
    started: bool = False
    closed: bool = False

    async def start(self, functions: list[str] | None = None) -> None:  # noqa: ARG002
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def dequeue(
        self,
        functions: list[str],  # noqa: ARG002
        *,
        timeout: float = 5.0,  # noqa: ARG002
    ) -> Job | None:
        await asyncio.sleep(0.05)
        return None


@dataclass
class _ClosableStatusBuffer:
    close_calls: int = 0
    timeout_args: list[float] = field(default_factory=list)

    async def close(self, *, timeout_seconds: float = 2.0) -> None:
        self.close_calls += 1
        self.timeout_args.append(timeout_seconds)


@pytest.mark.asyncio
async def test_start_flushes_status_buffer_on_shutdown() -> None:
    queue = _IdleQueue()
    status = _ClosableStatusBuffer()
    processor = JobProcessor(
        queue=cast(BaseQueue, queue),
        registry=Registry(),
        concurrency=1,
        status_buffer=status,
        status_flush_timeout_seconds=1.5,
        handle_signals=False,
    )

    task = asyncio.create_task(processor.start())
    await asyncio.sleep(0.1)
    await processor.stop(timeout=1.0)
    await task

    assert queue.started is True
    assert queue.closed is True
    assert status.close_calls == 1
    assert status.timeout_args == [1.5]


@pytest.mark.asyncio
async def test_process_one_completes_when_status_started_event_fails() -> None:
    registry = Registry()
    status = _FlakyStatusRecorder(fail_methods={"record_job_started"})

    async def task() -> str:
        return "ok"

    registry.register_task("task_key", task)
    job = Job(function="task_key", function_name="task")
    queue = _SingleJobQueue(job=job)
    processor = JobProcessor(
        queue=cast(BaseQueue, queue),
        registry=registry,
        status_buffer=status,
    )

    try:
        await processor._process_one()  # noqa: SLF001
        assert queue.finished == [(job.id, JobStatus.COMPLETE, "ok", None)]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_handle_success_keeps_terminal_state_when_status_completed_fails() -> None:
    queue = _QueueRecorder()
    status = _FlakyStatusRecorder(fail_methods={"record_job_completed"})
    registry = Registry()

    async def task() -> str:
        return "ok"

    task_def = registry.register_task("task_key", task)
    processor = JobProcessor(
        queue=cast(BaseQueue, queue),
        registry=registry,
        status_buffer=status,
    )

    try:
        job = Job(function="task_key", function_name="task", kwargs={}, root_id="job-1")
        job.mark_started("worker")
        await processor._handle_success(job, task_def, "ok", duration_ms=1)  # noqa: SLF001
        assert queue.finished == [(job.id, JobStatus.COMPLETE, "ok", None)]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_handle_failure_retries_when_status_retrying_event_fails() -> None:
    queue = _QueueRecorder()
    status = _FlakyStatusRecorder(fail_methods={"record_job_retrying"})
    registry = Registry()

    async def task() -> None:
        return None

    task_def = registry.register_task(
        "task_key",
        task,
        retries=2,
        retry_delay=1,
        retry_backoff=2,
    )
    processor = JobProcessor(
        queue=cast(BaseQueue, queue),
        registry=registry,
        status_buffer=status,
    )

    try:
        job = Job(function="task_key", function_name="task", kwargs={}, root_id="job-r")
        job.mark_started("worker")
        job.attempts = 1
        await processor._handle_failure(job, task_def, RuntimeError("boom"))  # noqa: SLF001
        assert queue.retried == [(job.id, 1)]
        assert queue.dispatch_reasons == [
            ("task_key", DispatchReason.RETRYING, job.id)
        ]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001


@pytest.mark.asyncio
async def test_handle_failure_finishes_when_status_failed_event_fails() -> None:
    queue = _QueueRecorder()
    status = _FlakyStatusRecorder(fail_methods={"record_job_failed"})
    registry = Registry()

    async def task() -> None:
        return None

    task_def = registry.register_task("task_key", task, retries=0)
    processor = JobProcessor(
        queue=cast(BaseQueue, queue),
        registry=registry,
        status_buffer=status,
    )

    try:
        job = Job(function="task_key", function_name="task", kwargs={}, root_id="job-f")
        job.mark_started("worker")
        job.attempts = 2
        await processor._handle_failure(job, task_def, RuntimeError("fatal"))  # noqa: SLF001
        assert queue.finished == [(job.id, JobStatus.FAILED, None, "fatal")]
    finally:
        processor._sync_pool.shutdown(wait=False)  # noqa: SLF001
