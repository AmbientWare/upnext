"""Event schemas for job tracking between workers and API."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

EVENTS_STREAM = "conduit:status:events"
API_REQUESTS_STREAM = "conduit:api:requests"
EVENTS_PUBSUB_CHANNEL = "conduit:status:events:pubsub"


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

    job_id: str
    function: str
    kwargs: dict[str, Any] = {}
    attempt: int = 1
    max_retries: int = 0
    worker_id: str | None = None
    started_at: datetime


class JobCompletedEvent(BaseModel):
    """Event data for job.completed."""

    job_id: str
    function: str
    result: Any = None
    duration_ms: float | None = None
    attempt: int = 1
    completed_at: datetime


class JobFailedEvent(BaseModel):
    """Event data for job.failed."""

    job_id: str
    function: str
    error: str
    traceback: str | None = None
    attempt: int = 1
    max_retries: int = 0
    will_retry: bool = False
    failed_at: datetime


class JobRetryingEvent(BaseModel):
    """Event data for job.retrying."""

    job_id: str
    function: str
    error: str
    delay_seconds: float
    current_attempt: int
    next_attempt: int
    retry_at: datetime


class JobProgressEvent(BaseModel):
    """Event data for job.progress."""

    job_id: str
    progress: float
    message: str | None = None
    updated_at: datetime


class JobCheckpointEvent(BaseModel):
    """Event data for job.checkpoint."""

    job_id: str
    state: dict[str, Any]
    checkpointed_at: datetime


class SSEJobEvent(BaseModel):
    """Event payload streamed to browser clients via SSE.

    Only includes fields the dashboard needs — sensitive data like
    kwargs, result, traceback, and checkpoint state are excluded.
    Extra fields from the source event are silently dropped.
    """

    model_config = ConfigDict(extra="ignore")

    type: str
    job_id: str = ""
    worker_id: str = ""
    function: str | None = None
    # job.started / job.completed / job.failed
    attempt: int | None = None
    max_retries: int | None = None
    started_at: datetime | None = None
    # job.completed
    duration_ms: float | None = None
    completed_at: datetime | None = None
    # job.failed
    error: str | None = None
    failed_at: datetime | None = None
    # job.retrying
    current_attempt: int | None = None
    next_attempt: int | None = None
    # job.progress
    progress: float | None = None
    message: str | None = None


class EventRequest(BaseModel):
    """Generic event request from workers."""

    type: str
    data: dict[str, Any]
    worker_id: str | None = None


class BatchEventItem(BaseModel):
    """Single event in a batch."""

    type: str
    job_id: str
    worker_id: str
    timestamp: float
    data: dict[str, Any] = {}


class BatchEventRequest(BaseModel):
    """Batch of events from workers."""

    events: list[BatchEventItem]
    worker_id: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str
    tier: str = "free"
    features: list[str] = []
