"""Typed job source contract payloads."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from shared.domain import JobType


class TaskJobSource(BaseModel):
    """Typed source context for task jobs."""

    type: Literal[JobType.TASK] = JobType.TASK


class CronJobSource(BaseModel):
    """Typed source context for cron jobs."""

    type: Literal[JobType.CRON] = JobType.CRON
    schedule: str
    cron_window_at: float | None = None
    startup_reconciled: bool = False
    startup_policy: str | None = None


class EventJobSource(BaseModel):
    """Typed source context for event jobs."""

    type: Literal[JobType.EVENT] = JobType.EVENT
    event_pattern: str
    event_handler_name: str


JobSource = Annotated[
    TaskJobSource | CronJobSource | EventJobSource,
    Field(discriminator="type"),
]


__all__ = [
    "TaskJobSource",
    "CronJobSource",
    "EventJobSource",
    "JobSource",
]
