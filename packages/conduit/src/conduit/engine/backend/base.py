"""Base backend class for job event reporting."""

from abc import ABC, abstractmethod
from typing import Any

from shared.models import Job


class BaseBackend(ABC):
    """
    Abstract base class for job event backends.

    Implementations report job lifecycle events to different backends:
    - ApiBackend: Sends to Conduit API (SaaS)
    - RedisBackend: Writes to Redis (self-hosted)

    The StatusBuffer flushes batched events to the backend via batch_send().
    """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if backend is connected and ready."""
        ...

    @abstractmethod
    async def connect(
        self,
        worker_id: str,
        worker_name: str,
        *,
        functions: list[str] | None = None,
        function_definitions: list[dict[str, Any]] | None = None,
        concurrency: int = 10,
    ) -> bool:
        """
        Connect/initialize the backend.

        Returns:
            True if connection successful, False otherwise
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect and cleanup."""
        ...

    @abstractmethod
    async def heartbeat(
        self,
        worker_id: str,
        active_jobs: int = 0,
        jobs_processed: int = 0,
        jobs_failed: int = 0,
        queued_jobs: int = 0,
    ) -> bool:
        """
        Send heartbeat to keep worker registered.

        Returns:
            True if heartbeat succeeded, False otherwise.
        """
        ...

    @abstractmethod
    async def batch_send(self, events: list[Any]) -> None:
        """
        Send multiple status events in one call.

        Used by StatusBuffer for efficient batched reporting.

        Args:
            events: List of StatusEvent objects to send
        """
        ...

    # Individual event methods (used for direct reporting, not batched)

    @abstractmethod
    async def job_started(
        self,
        job: "Job",
        *,
        worker_id: str | None = None,
    ) -> None:
        """Report that a job has started."""
        ...

    @abstractmethod
    async def job_completed(
        self,
        job: "Job",
        result: Any = None,
        duration_ms: float | None = None,
    ) -> None:
        """Report that a job completed successfully."""
        ...

    @abstractmethod
    async def job_failed(
        self,
        job: "Job",
        error: str,
        traceback: str | None = None,
        will_retry: bool = False,
    ) -> None:
        """Report that a job failed."""
        ...
