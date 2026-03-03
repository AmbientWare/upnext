"""Constants and data types for Redis queue."""

from dataclasses import dataclass
from typing import Any

from shared import Job, JobStatus


@dataclass
class CompletedJob:
    """A job that has finished processing."""

    job: Job
    status: JobStatus
    result: Any = None
    error: str | None = None
