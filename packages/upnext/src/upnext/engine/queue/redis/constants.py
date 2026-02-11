"""Constants and data types for Redis queue."""

from dataclasses import dataclass
from typing import Any

from shared import Job, JobStatus
from shared.queue import QUEUE_CONSUMER_GROUP, QUEUE_KEY_PREFIX

# Default settings
DEFAULT_KEY_PREFIX = QUEUE_KEY_PREFIX
DEFAULT_CONSUMER_GROUP = QUEUE_CONSUMER_GROUP
DEFAULT_CLAIM_TIMEOUT_MS = 30_000  # 30 seconds - reclaim dead consumer messages
DEFAULT_JOB_TTL_SECONDS = 86_400  # 24 hours - auto-cleanup old jobs
DEFAULT_RESULT_TTL_SECONDS = 3_600  # 1 hour - terminal result retention
# 0 disables trimming (preferred for job streams to avoid silent backlog loss).
# Set to a positive value to enable approximate MAXLEN trimming.
DEFAULT_STREAM_MAXLEN = 0
DEFAULT_DLQ_STREAM_MAXLEN = 10_000

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
