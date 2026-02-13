"""Task utilities for UpNext."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from upnext.engine.queue.base import BaseQueue


@dataclass
class TaskResult[T]:
    """
    Result of a successful task execution.

    Example:
        result = await my_task.wait(order_id="123")
        print(result.value)
    """

    value: T | None
    """The return value from the task (None if failed/cancelled)."""

    job_id: str
    """Unique identifier for this job execution."""

    function: str
    """Stable function key that was executed."""

    function_name: str
    """Human-readable function name."""

    status: str = "complete"
    """Final status: 'complete', 'failed', or 'cancelled'."""

    error: str | None = None
    """Error message if the task failed."""

    started_at: datetime | None = None
    """When the job started executing."""

    completed_at: datetime | None = None
    """When the job completed."""

    attempts: int = 1
    """Number of attempts (including retries) it took to complete."""

    parent_id: str | None = None
    """Parent job ID if this was spawned from another task."""

    root_id: str = ""
    """Root job ID for the execution lineage."""

    @property
    def ok(self) -> bool:
        """Whether the task completed successfully."""
        return self.status == "complete"


class Future[T]:
    """
    Represents a pending job result.

    Use `.result()` to wait for the job to complete and get the result.
    """

    def __init__(self, job_id: str, queue: "BaseQueue") -> None:
        self._job_id = job_id
        self._queue = queue

    @property
    def job_id(self) -> str:
        """Get the job ID."""
        return self._job_id

    async def result(self, timeout: float | None = None) -> TaskResult[T]:
        """
        Wait for the job to complete and return the result.

        Args:
            timeout: Maximum time to wait in seconds (None waits indefinitely)

        Returns:
            TaskResult containing the value, status, and execution metadata

        Raises:
            TimeoutError: If timeout reached before completion
            TaskExecutionError: If the task completed with failed/cancelled status
        """
        status = await self._queue.subscribe_job(self._job_id, timeout=timeout)
        job = await self._queue.get_job(self._job_id)
        if not job:
            raise RuntimeError(f"Job {self._job_id} not found after completion")

        task_result = TaskResult(
            value=job.result,
            job_id=job.id,
            function=job.function,
            function_name=job.function_name,
            status=status,
            error=job.error,
            started_at=job.started_at,
            completed_at=job.completed_at,
            attempts=job.attempts,
            parent_id=job.parent_id,
            root_id=job.root_id,
        )
        if not task_result.ok:
            raise TaskExecutionError(task_result)
        return task_result

    async def cancel(self) -> bool:
        """
        Cancel the job.

        Returns:
            True if cancelled, False if already complete
        """
        return await self._queue.cancel(self._job_id)


class TaskExecutionError(RuntimeError):
    """Raised when a task finishes with failed/cancelled status."""

    def __init__(self, task_result: TaskResult[Any]) -> None:
        self.task_result = task_result
        self.job_id = task_result.job_id
        self.status = task_result.status
        self.error = task_result.error
        message = self.error or (
            f"Job {self.job_id} completed with non-success status '{self.status}'"
        )
        super().__init__(message)
