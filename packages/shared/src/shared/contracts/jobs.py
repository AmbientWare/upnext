"""Job and run API contract payloads."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.source import JobSource, TaskJobSource
from shared.domain import JobType


class JobHistoryResponse(BaseModel):
    """Single job history response."""

    id: str
    function: str
    function_name: str
    status: str
    created_at: datetime | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempts: int = 1
    max_retries: int = 0
    timeout: float | None = None
    worker_id: str | None = None
    parent_id: str | None = None
    root_id: str
    progress: float = 0.0
    kwargs: dict[str, Any] = Field(default_factory=dict)
    job_type: JobType = JobType.TASK
    source: JobSource = Field(default_factory=TaskJobSource)
    checkpoint: dict[str, Any] | None = None
    checkpoint_at: str | None = None
    dlq_replayed_from: str | None = None
    dlq_failed_at: str | None = None
    queue_wait_ms: float | None = None
    result: Any = None
    error: str | None = None
    duration_ms: float | None = None

    model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
    """List of jobs response."""

    jobs: list[JobHistoryResponse]
    total: int
    has_more: bool = False
    next_cursor: str | None = None


class JobStatsResponse(BaseModel):
    """Job statistics response."""

    total: int
    success_count: int
    failure_count: int
    cancelled_count: int
    success_rate: float
    avg_duration_ms: float | None = None


class JobCancelResponse(BaseModel):
    """Response payload for a manual job cancellation request."""

    job_id: str
    cancelled: bool
    deleted_stream_entries: int


class JobRetryResponse(BaseModel):
    """Response payload for a manual job retry request."""

    job_id: str
    retried: bool


class JobTrendHour(BaseModel):
    """Hourly job counts by status."""

    hour: str
    complete: int = 0
    failed: int = 0
    retrying: int = 0
    active: int = 0


class JobTrendsResponse(BaseModel):
    """Job trends response."""

    hourly: list[JobTrendHour]


class JobTrendsSnapshotEvent(BaseModel):
    """Realtime snapshot event for job trends."""

    type: Literal["jobs.trends.snapshot"] = "jobs.trends.snapshot"
    at: str
    trends: JobTrendsResponse


class Run(BaseModel):
    """Run model for job executions."""

    id: str
    function: str
    function_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float | None = None
    error: str | None = None
    worker_id: str | None = None
    attempts: int = 1
    progress: float = 0.0


__all__ = [
    "JobHistoryResponse",
    "JobListResponse",
    "JobStatsResponse",
    "JobCancelResponse",
    "JobRetryResponse",
    "JobTrendHour",
    "JobTrendsResponse",
    "JobTrendsSnapshotEvent",
    "Run",
]
