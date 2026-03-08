"""Backend-agnostic persistence models used by repositories/services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from shared.contracts import CronJobSource, EventJobSource, JobSource, TaskJobSource
from shared.domain import JobType
from shared.keys import DEFAULT_WORKSPACE_ID


@dataclass
class Job:
    id: str
    function: str
    function_name: str
    job_key: str
    workspace_id: str = DEFAULT_WORKSPACE_ID
    job_type: str = JobType.TASK.value
    status: str = "queued"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    queue_wait_ms: float | None = None
    attempts: int = 1
    max_retries: int = 0
    timeout: float | None = None
    worker_id: str | None = None
    parent_id: str | None = None
    root_id: str = ""
    progress: float = 0.0
    kwargs: dict[str, object] = field(default_factory=dict)
    schedule: str | None = None
    cron_window_at: float | None = None
    startup_reconciled: bool = False
    startup_policy: str | None = None
    checkpoint: dict[str, object] | None = None
    checkpoint_at: str | None = None
    event_pattern: str | None = None
    event_handler_name: str | None = None
    result: object | None = None
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None

    @property
    def source(self) -> JobSource:
        try:
            parsed = JobType(self.job_type)
        except (TypeError, ValueError):
            return TaskJobSource()
        if parsed == JobType.CRON and self.schedule:
            return CronJobSource(
                schedule=self.schedule,
                cron_window_at=self.cron_window_at,
                startup_reconciled=self.startup_reconciled,
                startup_policy=self.startup_policy,
            )
        if parsed == JobType.EVENT and self.event_pattern and self.event_handler_name:
            return EventJobSource(
                event_pattern=self.event_pattern,
                event_handler_name=self.event_handler_name,
            )
        return TaskJobSource()
