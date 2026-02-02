"""Base storage protocol for job history."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass
class JobRecord:
    """
    A completed job record for history/analytics.

    This is a simplified view of a Job, optimized for storage and querying.
    """

    id: str
    function: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    attempts: int
    max_retries: int
    worker_id: str | None
    result: Any | None
    error: str | None
    error_traceback: str | None
    kwargs: dict[str, Any]
    metadata: dict[str, Any]


@dataclass
class JobFilter:
    """Filters for querying job history."""

    status: str | None = None
    function: str | None = None
    worker_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class Storage(Protocol):
    """
    Protocol for job history storage backends.

    Implementations provide persistent storage for completed jobs,
    enabling history views, analytics, and debugging.
    """

    async def record_started(
        self,
        job_id: str,
        function: str,
        worker_id: str,
        attempt: int,
        max_retries: int,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        """Record that a job has started."""
        ...

    async def record_completed(
        self,
        job_id: str,
        result: Any,
        duration_ms: int,
    ) -> None:
        """Record that a job completed successfully."""
        ...

    async def record_failed(
        self,
        job_id: str,
        error: str,
        error_traceback: str | None,
        duration_ms: int,
    ) -> None:
        """Record that a job failed."""
        ...

    async def record_retrying(
        self,
        job_id: str,
        attempt: int,
        delay: float,
    ) -> None:
        """Record that a job is being retried."""
        ...

    async def get_job(self, job_id: str) -> JobRecord | None:
        """Get a job by ID."""
        ...

    async def get_jobs(
        self,
        filter: JobFilter | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobRecord]:
        """Get jobs matching filter criteria."""
        ...

    async def get_stats(
        self,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """Get aggregate statistics."""
        ...
