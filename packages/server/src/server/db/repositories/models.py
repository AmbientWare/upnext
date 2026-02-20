"""Typed repository-layer request/response models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared.domain import JobType


@dataclass(frozen=True)
class FunctionJobStats:
    """Aggregated execution stats for a single function."""

    function: str
    runs: int
    successes: int
    failures: int
    avg_duration_ms: float
    last_run_at: str | None
    last_run_status: str | None


@dataclass(frozen=True)
class FunctionWaitStats:
    """Aggregated queue wait-time stats for a single function."""

    function: str
    avg_wait_ms: float
    p95_wait_ms: float


@dataclass(frozen=True)
class JobStatsSummary:
    """Aggregate job stats returned by repository queries."""

    total: int
    success_count: int
    failure_count: int
    cancelled_count: int
    success_rate: float
    avg_duration_ms: float | None


@dataclass(frozen=True)
class JobHourlyTrendRow:
    """Per-hour status count row returned by jobs trend aggregation."""

    yr: int
    mo: int
    dy: int
    hr: int
    status: str
    cnt: int


@dataclass(frozen=True)
class ArtifactRecord:
    """Artifact row returned by repository read/write methods."""

    id: str
    job_id: str
    name: str
    type: str
    size_bytes: int | None
    content_type: str | None
    sha256: str | None
    storage_backend: str
    storage_key: str
    status: str
    error: str | None
    created_at: datetime


@dataclass(frozen=True)
class PendingArtifactRecord:
    """Pending artifact row returned by repository read/write methods."""

    id: str
    job_id: str
    name: str
    type: str
    size_bytes: int | None
    content_type: str | None
    sha256: str | None
    storage_backend: str
    storage_key: str
    status: str
    error: str | None
    created_at: datetime


class JobRecordCreate(BaseModel):
    """Validated payload for inserting a job_history row."""

    model_config = ConfigDict(
        extra="ignore", populate_by_name=True, use_enum_values=True
    )

    id: str = Field(min_length=1, validation_alias="job_id")
    job_key: str | None = None
    function: str = Field(min_length=1)
    function_name: str | None = None
    job_type: JobType = JobType.TASK
    status: str = Field(min_length=1)
    created_at: datetime | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempts: int = Field(default=1, ge=1)
    max_retries: int = Field(default=0, ge=0)
    timeout: float | None = Field(default=None, ge=0)
    worker_id: str | None = None
    parent_id: str | None = None
    root_id: str | None = None
    progress: float = Field(default=0.0, ge=0, le=1)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    schedule: str | None = None
    cron_window_at: float | None = Field(default=None, ge=0)
    startup_reconciled: bool = False
    startup_policy: str | None = None
    checkpoint: dict[str, Any] | None = None
    checkpoint_at: str | None = None
    event_pattern: str | None = None
    event_handler_name: str | None = None
    queue_wait_ms: float | None = Field(default=None, ge=0)
    result: Any = None
    error: str | None = None

    @model_validator(mode="after")
    def _apply_defaults(self) -> "JobRecordCreate":
        if not self.function_name:
            self.function_name = self.function
        if not self.job_key:
            self.job_key = self.id
        if not self.root_id:
            self.root_id = self.id
        return self


__all__ = [
    "ArtifactRecord",
    "PendingArtifactRecord",
    "FunctionJobStats",
    "FunctionWaitStats",
    "JobStatsSummary",
    "JobHourlyTrendRow",
    "JobRecordCreate",
]
