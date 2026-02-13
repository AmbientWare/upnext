"""Runtime event contract payloads emitted by workers."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.source import JobSource, TaskJobSource
from shared.domain import JobType


class EventType(StrEnum):
    """Event types sent from workers to API."""

    JOB_STARTED = "job.started"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    JOB_RETRYING = "job.retrying"
    JOB_PROGRESS = "job.progress"
    JOB_CHECKPOINT = "job.checkpoint"


class JobStartedEvent(BaseModel):
    """Event data for job.started."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    function: str = Field(min_length=1)
    function_name: str = Field(min_length=1)
    parent_id: str | None = None
    root_id: str = Field(min_length=1)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    source: JobSource = Field(default_factory=TaskJobSource)
    checkpoint: dict[str, Any] | None = None
    checkpoint_at: str | None = None
    dlq_replayed_from: str | None = None
    dlq_failed_at: str | None = None
    scheduled_at: datetime | None = None
    queue_wait_ms: float | None = Field(default=None, ge=0)
    attempt: int = Field(default=1, ge=1)
    max_retries: int = Field(default=0, ge=0)
    worker_id: str | None = None
    started_at: datetime

    @property
    def job_type(self) -> JobType:
        """Expose source type directly for persistence layers."""
        return self.source.type


class JobCompletedEvent(BaseModel):
    """Event data for job.completed."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    function: str = Field(min_length=1)
    function_name: str = Field(min_length=1)
    parent_id: str | None = None
    root_id: str = Field(min_length=1)
    result: Any = None
    duration_ms: float | None = Field(default=None, ge=0)
    attempt: int = Field(default=1, ge=1)
    completed_at: datetime


class JobFailedEvent(BaseModel):
    """Event data for job.failed."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    function: str = Field(min_length=1)
    function_name: str = Field(min_length=1)
    parent_id: str | None = None
    root_id: str = Field(min_length=1)
    error: str = Field(min_length=1)
    traceback: str | None = None
    attempt: int = Field(default=1, ge=1)
    max_retries: int = Field(default=0, ge=0)
    will_retry: bool = False
    failed_at: datetime


class JobRetryingEvent(BaseModel):
    """Event data for job.retrying."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    function: str = Field(min_length=1)
    function_name: str = Field(min_length=1)
    parent_id: str | None = None
    root_id: str = Field(min_length=1)
    error: str = Field(min_length=1)
    delay_seconds: float = Field(ge=0)
    current_attempt: int = Field(ge=1)
    next_attempt: int = Field(ge=1)
    retry_at: datetime


class JobProgressEvent(BaseModel):
    """Event data for job.progress."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    parent_id: str | None = None
    root_id: str = Field(min_length=1)
    progress: float = Field(ge=0, le=1)
    message: str | None = None
    updated_at: datetime


class JobCheckpointEvent(BaseModel):
    """Event data for job.checkpoint."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    parent_id: str | None = None
    root_id: str = Field(min_length=1)
    state: dict[str, Any]
    checkpointed_at: datetime


class SSEJobEvent(BaseModel):
    """Event payload streamed to browser clients via SSE."""

    model_config = ConfigDict(extra="ignore")

    type: str
    job_id: str = ""
    worker_id: str = ""
    function: str | None = None
    function_name: str | None = None
    parent_id: str | None = None
    root_id: str
    attempt: int | None = None
    max_retries: int | None = None
    started_at: datetime | None = None
    duration_ms: float | None = None
    completed_at: datetime | None = None
    error: str | None = None
    failed_at: datetime | None = None
    current_attempt: int | None = None
    next_attempt: int | None = None
    progress: float | None = None
    message: str | None = None


__all__ = [
    "EventType",
    "JobStartedEvent",
    "JobCompletedEvent",
    "JobFailedEvent",
    "JobRetryingEvent",
    "JobProgressEvent",
    "JobCheckpointEvent",
    "SSEJobEvent",
]
