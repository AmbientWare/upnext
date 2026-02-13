"""Constants and data types for Redis queue."""

from dataclasses import dataclass
from typing import Any

from shared import Job, JobStatus

# Default settings
DEFAULT_CLAIM_TIMEOUT_MS = 30_000  # 30 seconds - reclaim dead consumer messages

# Batching defaults
DEFAULT_BATCH_SIZE = 100
DEFAULT_INBOX_SIZE = 1000
DEFAULT_OUTBOX_SIZE = 10000
DEFAULT_FLUSH_INTERVAL = 0.01  # 10ms


@dataclass
class CompletedJob:
    """A job that has finished processing."""

    job: Job
    status: JobStatus
    result: Any = None
    error: str | None = None
